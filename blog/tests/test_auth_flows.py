"""Тесты каналов входа (blog/views/auth.py) — самый чувствительный код в проекте
(coding-principles.md §3): HMAC-проверка подписи Telegram (Mini App/Login Widget) и
одноразовые токены. Ни один из 4 каналов входа не был покрыт тестами.

Инвариант из coding-principles §3, который явно проверяется: «блэклист закрывает
вход по всем каналам» — застраховано отдельным тестом на каждый канал.
"""
import hashlib
import hmac
import time
from urllib.parse import urlencode

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from blog.models import TelegramAuthToken
from blog.services.web_auth import issue_auth_token
from . import factories as f

BOT_TOKEN = 'test-bot-token-123'


def _webapp_init_data(user_id, username='tguser', first_name='Имя', bot_token=BOT_TOKEN, auth_date=None):
    auth_date = auth_date or int(time.time())
    import json
    user_json = json.dumps({'id': user_id, 'username': username, 'first_name': first_name})
    pairs = {'auth_date': str(auth_date), 'user': user_json, 'query_id': 'AAA'}
    data_check_string = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    pairs['hash'] = computed_hash
    return urlencode(pairs)


def _login_widget_payload(user_id, username='tguser', first_name='Имя', bot_token=BOT_TOKEN, auth_date=None):
    auth_date = auth_date or int(time.time())
    pairs = {'id': str(user_id), 'first_name': first_name, 'username': username, 'auth_date': str(auth_date)}
    data_check_string = '\n'.join(f'{k}={pairs[k]}' for k in sorted(pairs))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    pairs['hash'] = computed_hash
    return pairs


@override_settings(TG_BOT_TOKEN=BOT_TOKEN)
class WebappAuthTests(TestCase):
    def test_valid_init_data_logs_in_new_guest(self):
        r = self.client.post(reverse('webapp_auth'), {'init_data': _webapp_init_data(999001)})
        self.assertEqual(r.status_code, 200)
        self.assertIn('redirect', r.json())
        from blog.models import User
        self.assertTrue(User.objects.filter(telegram_id='999001').exists())

    def test_invalid_signature_rejected(self):
        bad = _webapp_init_data(999002).replace('hash=', 'hash=deadbeef')
        r = self.client.post(reverse('webapp_auth'), {'init_data': bad})
        self.assertEqual(r.status_code, 400)

    def test_missing_init_data_rejected(self):
        r = self.client.post(reverse('webapp_auth'), {})
        self.assertEqual(r.status_code, 400)

    def test_get_not_allowed(self):
        r = self.client.get(reverse('webapp_auth'))
        self.assertEqual(r.status_code, 405)

    def test_blacklisted_user_rejected(self):
        user = f.make_user(telegram_id='999003', status='blacklisted')
        r = self.client.post(reverse('webapp_auth'), {'init_data': _webapp_init_data(999003)})
        self.assertEqual(r.status_code, 403)

    def test_stale_auth_date_rejected(self):
        old = int(time.time()) - 90000  # больше MAX_AUTH_AGE_SECONDS (сутки)
        r = self.client.post(reverse('webapp_auth'), {'init_data': _webapp_init_data(999004, auth_date=old)})
        self.assertEqual(r.status_code, 400)


@override_settings(TG_BOT_TOKEN=BOT_TOKEN)
class TelegramLoginCallbackTests(TestCase):
    def test_valid_widget_login(self):
        payload = _login_widget_payload(999011)
        r = self.client.get(reverse('telegram_login_callback'), payload)
        self.assertEqual(r.status_code, 302)
        from blog.models import User
        self.assertTrue(User.objects.filter(telegram_id='999011').exists())

    def test_invalid_signature_redirects_to_login(self):
        payload = _login_widget_payload(999012)
        payload['hash'] = 'wrong'
        r = self.client.get(reverse('telegram_login_callback'), payload)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_blacklisted_user_rejected(self):
        f.make_user(telegram_id='999013', status='blacklisted')
        payload = _login_widget_payload(999013)
        r = self.client.get(reverse('telegram_login_callback'), payload)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])


class TgLinkLoginTests(TestCase):
    def test_valid_token_logs_in(self):
        user = f.make_user()
        token = issue_auth_token(user)
        r = self.client.get(reverse('tg_link_login', args=[token.token]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue('_auth_user_id' in self.client.session)

    def test_token_is_single_use(self):
        user = f.make_user()
        token = issue_auth_token(user)
        self.client.get(reverse('tg_link_login', args=[token.token]))
        self.client.get(reverse('logout'))
        r = self.client.get(reverse('tg_link_login', args=[token.token]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_unknown_token_redirects_to_login(self):
        import uuid
        r = self.client.get(reverse('tg_link_login', args=[uuid.uuid4()]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_blacklisted_user_rejected(self):
        user = f.make_user(status='blacklisted')
        token = issue_auth_token(user)
        r = self.client.get(reverse('tg_link_login', args=[token.token]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])


class LoginPasswordTests(TestCase):
    def setUp(self):
        self.user = f.make_user(login='ivanov', system_username='ivanov')
        self.user.set_password('correct-pass')
        self.user.save()

    def test_correct_credentials_logs_in(self):
        r = self.client.post(reverse('login'), {'login': 'ivanov', 'password': 'correct-pass'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue('_auth_user_id' in self.client.session)

    def test_wrong_password_rejected(self):
        r = self.client.post(reverse('login'), {'login': 'ivanov', 'password': 'wrong'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_already_authenticated_redirects_to_dashboard(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('login'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/', r['Location'])

    def test_blacklisted_user_cannot_login(self):
        self.user.status = 'blacklisted'
        self.user.save(update_fields=['status'])
        r = self.client.post(reverse('login'), {'login': 'ivanov', 'password': 'correct-pass'})
        self.assertFalse('_auth_user_id' in self.client.session)


class RegisterViewTests(TestCase):
    def test_register_creates_account_and_logs_in(self):
        r = self.client.post(reverse('register'), {
            'first_name': 'Новый', 'last_name': 'Пользователь', 'middle_name': '',
            'telegram_username': 'newbie', 'phone': '+79990001122',
            'birthday': '2000-01-01', 'login': 'newbie_login',
            'password': 'SecurePass123', 'password2': 'SecurePass123',
        })
        self.assertEqual(r.status_code, 302)
        from blog.models import User
        self.assertTrue(User.objects.filter(login='newbie_login').exists())

    def test_already_authenticated_redirects(self):
        user = f.make_user()
        self.client.force_login(user)
        r = self.client.get(reverse('register'))
        self.assertEqual(r.status_code, 302)


class LogoutViewTests(TestCase):
    def test_logout_clears_session(self):
        user = f.make_user()
        self.client.force_login(user)
        r = self.client.get(reverse('logout'))
        self.assertEqual(r.status_code, 302)
        self.assertFalse('_auth_user_id' in self.client.session)
