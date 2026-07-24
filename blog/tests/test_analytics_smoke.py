"""Smoke-тесты аналитики (blog/views/analytics.py).

Технический дашборд закрыт отдельным списком telegram_id (ANALYTICS_ADMIN_TG_IDS в
.env), НЕ ролью менеджера — decorators.tech_admin_required. Тесты подставляют себя в
список через override_settings, чтобы не зависеть от реального .env, и отдельно
фиксируют, что обычный менеджер БЕЗ этого telegram_id доступа не имеет (частый повод
для путаницы — «менеджер» тут не значит «пройдёт» ACL).
"""
from django.test import TestCase, override_settings
from django.urls import reverse

from . import factories as f


class TechAdminAccessTests(TestCase):
    def setUp(self):
        self.admin = f.make_manager()

    def test_manager_without_tg_id_forbidden(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('analytics_dashboard'))
        self.assertEqual(r.status_code, 403)

    @override_settings(ANALYTICS_ADMIN_TG_IDS=['555'])
    def test_allowed_tg_id_can_access(self):
        self.admin.telegram_id = '555'
        self.admin.save(update_fields=['telegram_id'])
        self.client.force_login(self.admin)
        r = self.client.get(reverse('analytics_dashboard'))
        self.assertEqual(r.status_code, 200)


@override_settings(ANALYTICS_ADMIN_TG_IDS=['777'])
class AnalyticsDataEndpointsTests(TestCase):
    def setUp(self):
        self.admin = f.make_manager(telegram_id='777')
        self.client.force_login(self.admin)

    def test_online_data_web_and_bot(self):
        for source in ('web', 'bot'):
            r = self.client.get(reverse('analytics_online_data'), {'source': source})
            self.assertEqual(r.status_code, 200, source)

    def test_clicks_data_requires_source(self):
        r = self.client.get(reverse('analytics_clicks_data'))
        self.assertEqual(r.status_code, 400)
        r = self.client.get(reverse('analytics_clicks_data'), {'source': 'web'})
        self.assertEqual(r.status_code, 200)

    def test_load_data(self):
        r = self.client.get(reverse('analytics_load_data'))
        self.assertEqual(r.status_code, 200)

    def test_duration_data(self):
        r = self.client.get(reverse('analytics_duration_data'))
        self.assertEqual(r.status_code, 200)

    def test_top_pages_data(self):
        r = self.client.get(reverse('analytics_top_pages_data'))
        self.assertEqual(r.status_code, 200)

    def test_top_bot_commands_data(self):
        r = self.client.get(reverse('analytics_top_bot_commands_data'))
        self.assertEqual(r.status_code, 200)

    def test_downtimes_data(self):
        r = self.client.get(reverse('analytics_downtimes_data'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('downtimes', r.json())


@override_settings(ANALYTICS_ADMIN_TG_IDS=['777'])
class AnalyticsDowntimeCrudTests(TestCase):
    """Добавление/удаление простоя — доступно менеджеру (manager_required), а не
    только техадмину, в отличие от остальной аналитики."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_add_downtime(self):
        r = self.client.post(reverse('analytics_downtime_add'), {
            'kind': 'crash', 'started_at': '2026-01-01T10:00:00', 'ended_at': '2026-01-01T10:30:00',
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])

    def test_add_downtime_invalid_kind(self):
        r = self.client.post(reverse('analytics_downtime_add'), {
            'kind': 'oops', 'started_at': '2026-01-01T10:00:00', 'ended_at': '2026-01-01T10:30:00',
        })
        self.assertEqual(r.status_code, 400)

    def test_add_downtime_end_before_start_rejected(self):
        r = self.client.post(reverse('analytics_downtime_add'), {
            'kind': 'crash', 'started_at': '2026-01-01T10:30:00', 'ended_at': '2026-01-01T10:00:00',
        })
        self.assertEqual(r.status_code, 400)

    def test_delete_downtime(self):
        from data_base import data_controller as dc
        import datetime
        from django.utils import timezone
        downtime = dc.create_downtime(
            'crash', timezone.now() - datetime.timedelta(hours=1), timezone.now(),
        )
        r = self.client.post(reverse('analytics_downtime_delete', args=[downtime.id]))
        self.assertEqual(r.status_code, 200)


class AnalyticsTrackingEndpointsTests(TestCase):
    """ping/leave/click — публичные (без login_required), их дёргает JS у любого
    посетителя, включая гостя без сессии на бэкенде."""

    def test_click_requires_action_key(self):
        r = self.client.post(reverse('analytics_click'), {})
        self.assertEqual(r.status_code, 400)

    def test_click_records_event(self):
        session = self.client.session
        session.save()
        r = self.client.post(reverse('analytics_click'), {'action_key': 'btn.test', 'label': 'Тест'})
        self.assertEqual(r.status_code, 200)

    def test_ping_without_session_returns_204(self):
        r = self.client.post(reverse('analytics_ping'), {})
        self.assertEqual(r.status_code, 204)

    def test_leave_is_noop_safe(self):
        r = self.client.post(reverse('analytics_leave'), {})
        self.assertEqual(r.status_code, 200)

    def test_ping_get_not_allowed(self):
        r = self.client.get(reverse('analytics_ping'))
        self.assertEqual(r.status_code, 405)
