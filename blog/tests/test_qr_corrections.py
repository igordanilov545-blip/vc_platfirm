"""Повторное изменение всех QR-отметок без блокировки сохранённых галочек."""
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from blog.models import EventGroup, ShiftAttendance, ShiftMeal, EventBadge
from blog.services import qr_attendance as qr
from . import factories as f


class QRCorrectionTests(TestCase):
    def setUp(self):
        self.manager, self.user = f.make_manager(), f.make_user()
        self.group = EventGroup.objects.create(title='Корректируемые отметки')
        self.event = f.make_event(event_group=self.group)
        self.shift = f.make_shift(self.event)
        self.part = f.make_participation(self.user, self.shift, status='pending', hours=0)
        self.token = qr.personal_token(self.user)

    def commit(self, kind, checked=True):
        ticket = qr.scan_context(self.manager, self.token)['scan_ticket']
        qr.commit_scan(self.manager, self.token, ticket, [{'kind': kind, 'shift_id': self.shift.pk, 'checked': checked}])

    def test_old_mark_url_accepts_lunch_badge_and_revocation(self):
        self.client.force_login(self.manager)
        for kind, model in (('lunch', ShiftMeal), ('badge', EventBadge)):
            response = self.client.post(reverse('qr_mark'), {'token': self.token, 'shift_id': self.shift.pk, 'action': kind})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(model.objects.filter(user=self.user).exists())
            response = self.client.post(reverse('qr_mark'), {'token': self.token, 'shift_id': self.shift.pk, 'action': kind, 'checked': 'false'})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(model.objects.filter(user=self.user).exists())

    def test_saved_handouts_can_be_removed_and_set_again(self):
        for kind, model in (('lunch', ShiftMeal), ('badge', EventBadge)):
            self.commit(kind)
            self.commit(kind, False)
            self.assertFalse(model.objects.filter(user=self.user).exists())
            self.commit(kind)
            self.assertEqual(model.objects.filter(user=self.user).count(), 1)

    def test_entry_exit_reopen_and_clear_recalculate_hours(self):
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            self.commit('in')
        with patch('django.utils.timezone.now', return_value=now + timedelta(hours=2)):
            self.commit('out')
        self.part.refresh_from_db()
        self.assertEqual(float(self.part.hours), 2)
        self.commit('out', False)
        self.part.refresh_from_db()
        record = ShiftAttendance.objects.get(user=self.user, shift=self.shift)
        self.assertIsNone(record.exited_at)
        self.assertEqual(float(self.part.hours), 0)
        with patch('django.utils.timezone.now', return_value=now + timedelta(hours=3)):
            self.commit('out')
        self.part.refresh_from_db()
        self.assertEqual(float(self.part.hours), 3)
        self.commit('in', False)
        self.part.refresh_from_db()
        self.user.refresh_from_db()
        record.refresh_from_db()
        self.assertIsNone(record.entered_at)
        self.assertIsNone(record.exited_at)
        self.assertEqual((self.part.status, float(self.part.hours), float(self.user.total_hours)), ('pending', 0, 0))
        self.commit('in')
        record.refresh_from_db()
        self.assertIsNotNone(record.entered_at)

    def test_saved_checkboxes_are_enabled_and_old_shift_stays_editable(self):
        self.commit('in')
        self.commit('out')
        self.commit('lunch')
        self.commit('badge')
        self.shift.start_time = timezone.now() - timedelta(days=2)
        self.shift.end_time = timezone.now() - timedelta(days=1)
        self.shift.save(update_fields=['start_time', 'end_time'])
        self.client.force_login(self.manager)
        response = self.client.post(reverse('qr_scan'), {'token': self.token})
        self.assertContains(response, f'data-shift-id="{self.shift.pk}"')
        self.assertNotContains(response, 'checked disabled')
        self.commit('in', False)
        rows = qr.scan_context(self.manager, self.token)['shift_rows']
        self.assertIn(self.shift.pk, [row['shift'].pk for row in rows])
