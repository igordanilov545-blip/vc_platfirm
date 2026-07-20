"""Потоки модерации: блэклист, вывод из ЧС, верификация для ПГАС, churn-журнал.

Фиксируют инварианты ПЕРЕД выносом этой изменяющей логики из views в сервисы
(Фаза 2, вариант «всё сразу»). Особое внимание:
- блокировка пишет запись в ChurnLog как СОБЫТИЕ (delta=0), несмотря на то что
  churn_score не меняется — раньше это делалось сырым ORM в обход log_churn_change;
- вывод из ЧС ОБНУЛЯЕТ churn_score (иначе автопересчёт вернёт в блэклист);
- верификация ПГАС резолвит связанный инцидент.
"""
from django.test import TestCase
from django.urls import reverse

from blog.models import ChurnLog, Incident
from . import factories as f


def _prime_captcha(client, session_key, answer=7):
    """Кладёт в сессию ожидаемый ответ капчи, чтобы POST прошёл двухфакторку."""
    session = client.session
    session[session_key] = answer
    session.save()


class BlacklistFlowTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.volunteer = f.make_user(status='active')

    def test_blacklist_sets_status_and_logs_event(self):
        _prime_captcha(self.client, f'captcha_user_blacklist_{self.volunteer.id}', answer=7)
        url = reverse('user_blacklist', args=[self.volunteer.id])
        r = self.client.post(url, {'reason': 'нарушение', 'captcha_answer': '7'})
        self.assertIn(r.status_code, (200, 302))

        self.volunteer.refresh_from_db()
        self.assertEqual(self.volunteer.status, 'blacklisted')
        self.assertEqual(self.volunteer.comment, 'нарушение')
        # Блокировка фиксируется в журнале churn как событие (delta=0).
        log = ChurnLog.objects.filter(user=self.volunteer, reason='blacklist').first()
        self.assertIsNotNone(log, 'блокировка должна записать событие в ChurnLog')
        self.assertEqual(log.delta, 0)
        self.assertEqual(log.note, 'нарушение')

    def test_blacklist_requires_reason(self):
        _prime_captcha(self.client, f'captcha_user_blacklist_{self.volunteer.id}', answer=7)
        url = reverse('user_blacklist', args=[self.volunteer.id])
        r = self.client.post(url, {'reason': '', 'captcha_answer': '7'})
        self.assertEqual(r.status_code, 302)
        self.volunteer.refresh_from_db()
        self.assertEqual(self.volunteer.status, 'active')  # не заблокирован

    def test_blacklist_wrong_captcha_aborts(self):
        _prime_captcha(self.client, f'captcha_user_blacklist_{self.volunteer.id}', answer=7)
        url = reverse('user_blacklist', args=[self.volunteer.id])
        self.client.post(url, {'reason': 'нарушение', 'captcha_answer': '999'})
        self.volunteer.refresh_from_db()
        self.assertEqual(self.volunteer.status, 'active')  # капча неверна — не заблокирован

    def test_unblacklist_resets_churn(self):
        self.volunteer.status = 'blacklisted'
        self.volunteer.churn_score = 42
        self.volunteer.save(update_fields=['status', 'churn_score'])

        url = reverse('user_unblacklist', args=[self.volunteer.id])
        self.client.post(url)
        self.volunteer.refresh_from_db()
        self.assertEqual(self.volunteer.status, 'active')
        self.assertEqual(self.volunteer.churn_score, 0)
        # Событие вывода тоже в журнале.
        self.assertTrue(ChurnLog.objects.filter(user=self.volunteer, reason='unblacklist').exists())


class PgasVerificationFlowTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.volunteer = f.make_user()

    def test_verify_sets_timestamp_and_resolves_incident(self):
        incident = Incident.objects.create(
            kind='pgas_verification', related_user=self.volunteer,
        )
        url = reverse('pgas_verify_user', args=[self.volunteer.id])
        self.client.post(url)

        self.volunteer.refresh_from_db()
        self.assertIsNotNone(self.volunteer.verified_by_manager_at)
        self.assertEqual(self.volunteer.verified_by_manager_by, self.manager)

        incident.refresh_from_db()
        self.assertIsNotNone(incident.resolved_at, 'верификация должна зарезолвить инцидент')

    def test_unverify_clears(self):
        from django.utils import timezone
        self.volunteer.verified_by_manager_at = timezone.now()
        self.volunteer.verified_by_manager_by = self.manager
        self.volunteer.save(update_fields=['verified_by_manager_at', 'verified_by_manager_by'])

        url = reverse('pgas_unverify_user', args=[self.volunteer.id])
        self.client.post(url)
        self.volunteer.refresh_from_db()
        self.assertIsNone(self.volunteer.verified_by_manager_at)
