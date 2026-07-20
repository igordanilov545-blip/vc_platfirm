"""Контракт слоя доступа к данным (`data_base/data_controller`).

Страхует распил монолита на пакет (Фаза 1) и последующий перенос ORM (Фаза 2):
проверяет, что публичные функции контроллера читают/пишут ровно то, что должны.
"""
from django.test import TestCase
from django.utils import timezone

from data_base import data_controller as dc
from blog.models import Application, Participation
from . import factories as f


class FacadeContractTests(TestCase):
    """Фасад пакета сохраняет прежний публичный контракт (обратная совместимость)."""

    def test_all_exports_are_callable(self):
        for name in dc.__all__:
            self.assertTrue(hasattr(dc, name), f'потерян экспорт: {name}')

    def test_expected_core_functions_present(self):
        for name in ['get_user_by_telegram_id', 'create_event', 'events_qs',
                     'get_const', 'create_record_generic', 'update_application_status']:
            self.assertIn(name, dc.__all__)


class UserControllerTests(TestCase):
    def test_get_user_by_telegram_id(self):
        u = f.make_user(telegram_id='555777')
        self.assertEqual(dc.get_user_by_telegram_id('555777'), u)
        self.assertIsNone(dc.get_user_by_telegram_id('nope'))

    def test_get_or_create_is_idempotent(self):
        u1, created1 = dc.get_or_create_user_by_telegram_id('42', telegram_username='foo')
        u2, created2 = dc.get_or_create_user_by_telegram_id('42')
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(u1.pk, u2.pk)

    def test_get_or_create_fills_empty_only(self):
        u, _ = dc.get_or_create_user_by_telegram_id('7', first_name='Аня')
        # Повторный вызов с другим именем НЕ перетирает уже заполненное.
        dc.get_or_create_user_by_telegram_id('7', first_name='Петя')
        u.refresh_from_db()
        self.assertEqual(u.first_name, 'Аня')

    def test_update_user_fields_whitelists(self):
        u = f.make_user()
        dc.update_user_fields(u, phone='+70000000000', nonexistent_field='x')
        u.refresh_from_db()
        self.assertEqual(u.phone, '+70000000000')


class EventControllerTests(TestCase):
    def test_create_and_get_event(self):
        ev = dc.create_event(title='Тест-меро')
        self.assertIn(ev, dc.get_events())
        self.assertEqual(dc.get_event_by_id(ev.id), ev)

    def test_get_open_events_requires_open_shift_and_published(self):
        published = f.make_event(published=True)
        f.make_shift(published, recruit_status='open')
        unpublished = f.make_event(published=False)
        f.make_shift(unpublished, recruit_status='open')
        closed = f.make_event(published=True)
        f.make_shift(closed, recruit_status='closed')

        open_ids = {e.id for e in dc.get_open_events()}
        self.assertIn(published.id, open_ids)
        self.assertNotIn(unpublished.id, open_ids)
        self.assertNotIn(closed.id, open_ids)

    def test_publish_event_sets_timestamp(self):
        ev = f.make_event(published=False)
        self.assertIsNone(ev.published_at)
        dc.publish_event(ev)
        ev.refresh_from_db()
        self.assertIsNotNone(ev.published_at)


class ApplicationControllerTests(TestCase):
    def setUp(self):
        self.event = f.make_event()
        self.shift = f.make_shift(self.event)

    def test_create_application_defaults_new(self):
        app = dc.create_application(event=self.event, first_name='Ваня', last_name='П')
        self.assertEqual(app.status, 'new')
        self.assertIsNotNone(app.submitted_at)

    def test_update_application_status_stamps_assigned(self):
        app = f.make_application(self.event)
        mgr = f.make_manager()
        dc.update_application_status(app, 'approved', assigned_by=mgr)
        app.refresh_from_db()
        self.assertEqual(app.status, 'approved')
        self.assertIsNotNone(app.assigned_at)
        self.assertEqual(app.assigned_by, mgr)

    def test_count_applications_by_status(self):
        f.make_application(self.event, status='new')
        f.make_application(self.event, status='approved')
        self.assertEqual(dc.count_applications(), 2)
        self.assertEqual(dc.count_applications(status_filter='new'), 1)

    def test_set_application_shifts_writes_summary(self):
        app = f.make_application(self.event)
        dc.set_application_shifts(app, [self.shift])
        app.refresh_from_db()
        self.assertIn(self.shift.day.isoformat(), app.shifts)
        self.assertIn(self.shift, app.selected_shifts.all())


class ParticipationControllerTests(TestCase):
    def test_update_participation_status_and_hours(self):
        event = f.make_event()
        shift = f.make_shift(event)
        user = f.make_user()
        part = f.make_participation(user, shift, status='attended', hours=0)
        dc.update_participation_status(part, 'attended', hours=6)
        part.refresh_from_db()
        self.assertEqual(part.hours, 6)


class ConstControllerTests(TestCase):
    def test_get_const_with_default(self):
        self.assertEqual(dc.get_const('nonexistent_threshold', default=42), 42)
        f.make_const('late_cancel_hours', 12)
        self.assertEqual(dc.get_const('late_cancel_hours'), 12)


class QuerysetAccessorTests(TestCase):
    def test_qs_accessors_return_lazy_querysets(self):
        f.make_event()
        # *_qs — ленивые queryset'ы (для композиции в отчётах), не list.
        self.assertGreaterEqual(dc.events_qs().count(), 1)
        self.assertEqual(list(dc.events_qs())[0].__class__.__name__, 'Event')
        self.assertTrue(hasattr(dc.applications_qs(), 'filter'))
