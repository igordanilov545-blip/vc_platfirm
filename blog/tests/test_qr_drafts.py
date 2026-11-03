"""Черновик QR: отметки при закрытии, время сканирования и выдача по уровням."""
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from blog.models import EventGroup, ShiftAttendance
from blog.services import qr_attendance as qr
from . import factories as f


class QRDraftTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.user = f.make_user(tshirt_size='XL', motivation='Личная анкета')
        self.group = EventGroup.objects.create(title='Одно мероприятие')
        self.events = [f.make_event(event_group=self.group), f.make_event(event_group=self.group)]
        self.shifts = [f.make_shift(self.events[i % 2]) for i in range(3)]
        for shift in self.shifts:
            f.make_participation(self.user, shift, status='pending', hours=0)
        self.token = qr.personal_token(self.user)

    def test_scan_is_read_only_and_commit_uses_original_scan_time(self):
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            card = qr.scan_context(self.manager, self.token)
        self.assertFalse(ShiftAttendance.objects.exists())
        with patch('django.utils.timezone.now', return_value=now + timedelta(minutes=20)):
            qr.commit_scan(self.manager, self.token, card['scan_ticket'], [{'kind': 'in', 'shift_id': self.shifts[0].pk}])
        entry = ShiftAttendance.objects.get(user=self.user)
        self.assertEqual(entry.entered_at, now)

    def test_three_meals_but_one_badge_across_positions_and_retries(self):
        from blog.models import ShiftMeal, EventBadge
        card = qr.scan_context(self.manager, self.token)
        changes = [{'kind': 'lunch', 'shift_id': shift.pk} for shift in self.shifts]
        changes += [{'kind': 'badge', 'shift_id': shift.pk} for shift in self.shifts]
        qr.commit_scan(self.manager, self.token, card['scan_ticket'], changes)
        qr.commit_scan(self.manager, self.token, card['scan_ticket'], changes)
        self.assertEqual(ShiftMeal.objects.filter(user=self.user).count(), 3)
        self.assertEqual(EventBadge.objects.filter(user=self.user, event_group=self.group).count(), 1)
        self.assertFalse(ShiftAttendance.objects.exists())

    def test_bad_ticket_other_operator_and_atomic_failure(self):
        card = qr.scan_context(self.manager, self.token)
        changes = [{'kind': 'in', 'shift_id': self.shifts[0].pk}]
        with self.assertRaises(ValidationError):
            qr.commit_scan(self.manager, self.token, card['scan_ticket'] + 'bad', changes)
        with self.assertRaises(PermissionDenied):
            qr.commit_scan(f.make_manager(), self.token, card['scan_ticket'], changes)
        with self.assertRaises(ValidationError):
            qr.commit_scan(self.manager, self.token, card['scan_ticket'], changes + [{'kind': 'out', 'shift_id': self.shifts[1].pk}])
        self.assertFalse(ShiftAttendance.objects.exists())

    def test_exit_hours_use_scanning_time_not_closing_time(self):
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            card = qr.scan_context(self.manager, self.token)
            qr.commit_scan(self.manager, self.token, card['scan_ticket'], [{'kind': 'in', 'shift_id': self.shifts[0].pk}])
        with patch('django.utils.timezone.now', return_value=now + timedelta(hours=2)):
            card = qr.scan_context(self.manager, self.token)
        with patch('django.utils.timezone.now', return_value=now + timedelta(hours=3)):
            qr.commit_scan(self.manager, self.token, card['scan_ticket'], [{'kind': 'out', 'shift_id': self.shifts[0].pk}])
        self.assertEqual(float(self.shifts[0].participations.get(user=self.user).hours), 2)

    def test_card_size_ticket_and_commit_csrf(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('qr_scan'), {'token': self.token})
        self.assertContains(response, 'Размер футболки')
        self.assertContains(response, 'XL')
        self.assertContains(response, 'data-qr-mark="lunch"')
        self.assertContains(response, 'data-qr-mark="badge"')
        self.assertTrue(response.context['scan_ticket'])
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        self.assertEqual(client.post(reverse('qr_commit'), {}).status_code, 403)

    def test_owner_questionnaire_hidden_but_manager_and_team_leader_see_it(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('profile_detail', args=[self.user.pk]))
        self.assertNotContains(response, 'Личная анкета')
        self.assertContains(response, 'profile-completion--compact')
        for operator in (self.manager, f.make_team_leader()):
            self.client.force_login(operator)
            self.assertContains(self.client.get(reverse('profile_detail', args=[self.user.pk])), 'Личная анкета')

    def test_restore_keeps_ticket_timestamp_and_no_attendance_is_written(self):
        card = qr.scan_context(self.manager, self.token)
        again = qr.scan_context(self.manager, self.token, scan_ticket=card['scan_ticket'])
        self.assertEqual(again['scanned_at'], card['scanned_at'])
        self.assertFalse(ShiftAttendance.objects.exists())

    def test_enrollment_near_start_suggests_entry_without_recording_it(self):
        shift = f.make_shift(self.events[0], start_time=timezone.now() + timedelta(minutes=10))
        card = qr.scan_context(self.manager, self.token)
        context = qr.enroll_scan_context(self.manager, self.token, shift.pk, scan_ticket=card['scan_ticket'])
        self.assertEqual(context['suggested_entry_shift'], shift.pk)
        self.assertFalse(ShiftAttendance.objects.filter(user=self.user, shift=shift).exists())
        self.assertEqual(shift.participations.get(user=self.user).status, 'pending')

    def test_handouts_reject_someone_elses_shift_and_scope_is_rechecked(self):
        from blog.models import ShiftMeal, Const
        other = f.make_shift(self.events[0])
        card = qr.scan_context(self.manager, self.token)
        with self.assertRaises(ValidationError):
            qr.commit_scan(self.manager, self.token, card['scan_ticket'], [{'kind': 'lunch', 'shift_id': other.pk}])
        delegate = f.make_team_leader()
        card = qr.scan_context(delegate, self.token)
        Const.objects.update_or_create(name='qr_scanner_scoped_access', defaults={'value': 1})
        with self.assertRaises(PermissionDenied):
            qr.commit_scan(delegate, self.token, card['scan_ticket'], [{'kind': 'lunch', 'shift_id': self.shifts[0].pk}])
        self.assertFalse(ShiftMeal.objects.exists())
