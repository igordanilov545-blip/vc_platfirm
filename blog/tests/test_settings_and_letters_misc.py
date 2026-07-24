"""Оставшиеся непокрытые маршруты хаба настроек и конструктора писем: const_edit
(двухшаговое подтверждение капчей), verify_telegram_start (deep-link в бота),
webapp_entry (лоадер Mini App), letter_font_delete, letter_template_delete.
"""
from django.test import TestCase, override_settings
from django.urls import reverse

from blog.models import Const, LetterFont, ThankYouLetterTemplate
from . import factories as f


class ConstEditTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.const = Const.objects.create(name='late_cancel_hours', value=24)

    def test_unchanged_value_saves_without_captcha(self):
        r = self.client.post(reverse('const_edit', args=[self.const.id]), {'value': '24'})
        self.assertIn(r.status_code, (200, 302))
        self.const.refresh_from_db()
        self.assertEqual(self.const.value, 24)

    def test_changed_value_requires_captcha_first(self):
        r = self.client.post(reverse('const_edit', args=[self.const.id]), {'value': '48'})
        self.assertEqual(r.status_code, 200)
        self.const.refresh_from_db()
        self.assertEqual(self.const.value, 24, 'без капчи значение меняться не должно')

    def test_changed_value_with_correct_captcha_saves(self):
        session_key = f'captcha_const_{self.const.id}'
        session = self.client.session
        session[session_key] = 5
        session.save()
        r = self.client.post(reverse('const_edit', args=[self.const.id]), {
            'value': '48', 'captcha_answer': '5',
        })
        self.assertIn(r.status_code, (200, 302))
        self.const.refresh_from_db()
        self.assertEqual(self.const.value, 48)

    def test_forbidden_for_volunteer(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.get(reverse('const_edit', args=[self.const.id]))
        self.assertEqual(r.status_code, 403)


@override_settings(TG_BOT_USERNAME='test_vc_bot')
class VerifyTelegramStartTests(TestCase):
    def test_authenticated_user_redirected_to_bot(self):
        user = f.make_user()
        self.client.force_login(user)
        r = self.client.post(reverse('verify_telegram_start'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('t.me/test_vc_bot', r['Location'])
        self.assertIn('verify_', r['Location'])

    def test_anonymous_redirected_to_login(self):
        r = self.client.post(reverse('verify_telegram_start'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_get_not_allowed(self):
        user = f.make_user()
        self.client.force_login(user)
        r = self.client.get(reverse('verify_telegram_start'))
        self.assertEqual(r.status_code, 405)


class WebappEntryTests(TestCase):
    def test_renders_with_allowall_frame_header(self):
        r = self.client.get(reverse('webapp_entry'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['X-Frame-Options'], 'ALLOWALL')


class LetterTemplateDeleteTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_delete_removes_template(self):
        tpl = ThankYouLetterTemplate.objects.create(title='Удаляемый')
        r = self.client.post(reverse('letter_template_delete', args=[tpl.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ThankYouLetterTemplate.objects.filter(id=tpl.id).exists())

    def test_forbidden_for_volunteer(self):
        tpl = ThankYouLetterTemplate.objects.create(title='Не тронь')
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.post(reverse('letter_template_delete', args=[tpl.id]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(ThankYouLetterTemplate.objects.filter(id=tpl.id).exists())


class LetterFontDeleteTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_delete_custom_font(self):
        font = LetterFont.objects.create(name='Мой шрифт', font_file=b'fake', is_builtin=False)
        r = self.client.post(reverse('letter_font_delete', args=[font.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(LetterFont.objects.filter(id=font.id).exists())

    def test_builtin_font_cannot_be_deleted(self):
        font = LetterFont.objects.create(name='Встроенный', font_file=b'fake', is_builtin=True)
        r = self.client.post(reverse('letter_font_delete', args=[font.id]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(LetterFont.objects.filter(id=font.id).exists())
