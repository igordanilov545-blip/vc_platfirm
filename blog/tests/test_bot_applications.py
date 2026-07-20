"""Тесты бизнес-логики сервис-слоя бота: подача/отмена/обработка заявок.

Покрывают реальную логику (не тонкие обёртки): ветвления apply_to_event, авторезерв
по требованиям, правило late-cancel, ACL обработки. Хендлеры aiogram тонкие —
sync_to_async(services.X) — и отдельно не тестируются (логика здесь).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from tg_bot import services
from blog.models import Application, UserRequirementException, Participation
from . import factories as f


class ApplyToEventTests(TestCase):
    def setUp(self):
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=5, recruit_status='open')
        self.user = f.make_user(registration_status='registered')

    def test_apply_creates_new_application(self):
        app, err = services.apply_to_event(self.user.id, self.event.id)
        self.assertIsNone(err)
        self.assertEqual(app.status, 'new')
        self.assertIn(self.shift, app.selected_shifts.all())

    def test_apply_event_not_found(self):
        app, err = services.apply_to_event(self.user.id, 999999)
        self.assertEqual(err, 'not_found')

    def test_apply_closed_when_no_open_shifts(self):
        self.shift.recruit_status = 'closed'
        self.shift.save(update_fields=['recruit_status'])
        app, err = services.apply_to_event(self.user.id, self.event.id)
        self.assertEqual(err, 'closed')

    def test_apply_blacklisted_rejected(self):
        self.user.status = 'blacklisted'
        self.user.save(update_fields=['status'])
        app, err = services.apply_to_event(self.user.id, self.event.id)
        self.assertEqual(err, 'blacklisted')

    def test_apply_guest_needs_registration(self):
        guest = f.make_user(registration_status='guest')
        app, err = services.apply_to_event(guest.id, self.event.id)
        self.assertEqual(err, 'need_registration')

    def test_apply_already_applied_returns_existing(self):
        first, _ = services.apply_to_event(self.user.id, self.event.id)
        again, err = services.apply_to_event(self.user.id, self.event.id)
        self.assertEqual(err, 'already_applied')
        self.assertEqual(again.id, first.id)

    def test_apply_auto_reserve_when_requirement_not_met(self):
        # у меро есть требование, которому пользователь НЕ соответствует → авторезерв
        req = f.make_requirement(title='18+')
        from blog.models import EventRequirementMap
        EventRequirementMap.objects.create(event=self.event, requirement=req)
        UserRequirementException.objects.create(user=self.user, requirement=req, reason='нет 18')

        app, err = services.apply_to_event(self.user.id, self.event.id)
        self.assertIsNone(err)  # пользователю обычное «принято»
        self.assertEqual(app.status, 'rejected')  # но фактически в резерве
        self.assertTrue(app.auto_reject_reason)


class CancelOwnApplicationTests(TestCase):
    def test_cancel_far_shift_allowed(self):
        f.make_const('late_cancel_hours', 24)
        event = f.make_event()
        shift = f.make_shift(event, days_from_now=5)  # далеко → отмена можно
        user = f.make_user(registration_status='registered')
        app = f.make_application(event, user=user, shifts=[shift], status='new')

        result, err = services.cancel_own_application(user.id, app.id, reason='передумал')
        self.assertIsNone(err)
        app.refresh_from_db()
        self.assertEqual(app.status, 'cancelled')
        self.assertEqual(app.cancel_reason, 'передумал')

    def test_cancel_late_shift_blocked(self):
        f.make_const('late_cancel_hours', 24)
        event = f.make_event()
        # смена уже завтра < 24ч? нет — сделаем смену через 1 час (поздний слив)
        shift = f.make_shift(event, days_from_now=0)
        shift.start_time = timezone.now() + timedelta(hours=1)
        shift.save(update_fields=['start_time'])
        user = f.make_user(registration_status='registered')
        app = f.make_application(event, user=user, shifts=[shift], status='new')

        result, err = services.cancel_own_application(user.id, app.id, reason='x')
        self.assertIsNone(result)
        self.assertIsNotNone(err)  # late_cancel — отмена заблокирована
        app.refresh_from_db()
        self.assertEqual(app.status, 'new')  # не отменена

    def test_cancel_foreign_application_not_found(self):
        event = f.make_event()
        shift = f.make_shift(event)
        owner = f.make_user()
        outsider = f.make_user()
        app = f.make_application(event, user=owner, shifts=[shift])
        result, err = services.cancel_own_application(outsider.id, app.id, reason='x')
        self.assertEqual(err, 'not_found')


class ProcessApplicationsAclTests(TestCase):
    def test_pending_applications_forbidden_for_plain_user(self):
        event = f.make_event()
        outsider = f.make_user()
        apps, err = services.event_pending_applications(outsider.id, event.id)
        self.assertEqual(err, 'forbidden')

    def test_process_all_manager_approves(self):
        manager = f.make_manager()
        event = f.make_event()
        shift = f.make_shift(event)
        applicant = f.make_user()
        f.make_application(event, user=applicant, shifts=[shift], status='new')

        approved, err = services.process_all_applications(manager.id, event.id)
        self.assertIsNone(err)
        self.assertEqual(len(approved), 1)
        # участие создано (approve через process_application)
        self.assertTrue(Participation.objects.filter(user=applicant, event_day=shift).exists())


class UserStatsTests(TestCase):
    def test_user_stats_returns_expected_keys(self):
        f.make_const('pgas_hours_threshold', 100)
        user = f.make_user()
        stats = services.user_stats(user.id)
        self.assertIsInstance(stats, dict)
        # ключевые поля статистики (сезон/всё время) присутствуют
        self.assertIn('total_hours', stats)
