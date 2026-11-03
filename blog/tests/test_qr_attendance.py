"""Персональный QR, доступ к сканеру, фактический вход/выход и московская дата."""
import asyncio
from datetime import datetime, timedelta, timezone as dt_timezone
from io import BytesIO
from unittest.mock import AsyncMock, Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.test import Client
from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from blog.models import EventGroup, EventStaff, UserQRCode, ScannerGrant, ShiftAttendance, Participation, Const
from blog.services import qr_attendance as qr
from blog.services.applications import process_application, process_shift_decision
from blog.services.applications import event_closing_checklist
from blog.services.formatting import fmt_dt, fmt_date
from . import factories as f


class PersonalQRTests(TestCase):
    def test_qr_is_stable_individual_and_exactly_32_ascii_bytes(self):
        first, second = f.make_user(registration_status='guest'), f.make_user()
        token = qr.personal_token(first)
        self.assertEqual(len(token.encode('ascii')), 32)
        self.assertEqual(qr.personal_token(first), token)
        self.assertNotEqual(qr.personal_token(second), token)
        self.assertEqual(UserQRCode.objects.filter(user=first).count(), 1)
        png = qr.personal_qr_png(first)
        self.assertEqual(Image.open(BytesIO(png)).size, (396, 396))
        self.assertEqual(qr.qr_matrix(token).version, 2)
        self.assertEqual(qr.qr_matrix(token).modules_count, 25)

    def test_qr_modal_is_private_and_contains_only_image(self):
        self.client.force_login(f.make_user(registration_status='guest', phone=None))
        response = self.client.get(reverse('personal_qr'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, '<img')
        self.assertNotContains(response, '<form')
        response = self.client.get(reverse('personal_qr_png'))
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('no-store', response['Cache-Control'])
        self.client.logout()
        self.assertEqual(self.client.get(reverse('personal_qr_png')).status_code, 302)

    def test_bot_photo_uses_existing_telegram_user_even_when_guest(self):
        from tg_bot.services import qr_png_for_telegram
        user = f.make_user(registration_status='guest')
        self.assertTrue(qr_png_for_telegram(user.telegram_id).startswith(b'\x89PNG'))
        self.assertIsNone(qr_png_for_telegram('not-in-database'))

    def test_bot_handler_sends_photo(self):
        from tg_bot.handlers.common import cmd_get_qr
        message = Mock()
        message.from_user.id = 123
        message.answer_photo = AsyncMock()
        with patch('tg_bot.services.qr_png_for_telegram', return_value=b'png'):
            asyncio.run(cmd_get_qr(message))
        message.answer_photo.assert_awaited_once()

    def test_profile_does_not_query_qr_table_before_user_opens_qr(self):
        user = f.make_user()
        self.client.force_login(user)
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse('profile_detail', args=[user.pk]))
        self.assertFalse(any('user_qr_codes' in query['sql'] for query in queries))
        self.assertFalse(UserQRCode.objects.exists())


class QRCheckInTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.volunteer = f.make_user()
        self.group = EventGroup.objects.create(title='Фестиваль')
        self.position = f.make_event(event_group=self.group)
        self.shift = f.make_shift(self.position)
        self.part = f.make_participation(self.volunteer, self.shift, status='pending', hours=0)
        self.token = qr.personal_token(self.volunteer)

    def test_approval_is_neutral_until_attendance_is_marked(self):
        user = f.make_user()
        app = f.make_application(self.position, user=user, shifts=[self.shift])
        process_application(app, 'approved', self.manager)
        part = Participation.objects.get(user=user, event_day=self.shift)
        self.assertEqual((part.status, part.hours, part.full_shift), ('pending', 0, False))
        user.refresh_from_db()
        self.assertEqual(user.total_hours, 0)

    def test_entry_exit_are_idempotent_and_do_not_reset_entry_time(self):
        first_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=first_time):
            qr.mark_scan(self.manager, self.token, self.shift.pk, 'in')
        qr.mark_scan(self.manager, self.token, self.shift.pk, 'in')
        record = ShiftAttendance.objects.get(user=self.volunteer, shift=self.shift)
        self.assertEqual(record.entered_at, first_time)
        self.assertIsNone(record.exited_at)
        self.part.refresh_from_db()
        self.assertEqual((self.part.status, self.part.hours), ('attended', 0))
        with patch('django.utils.timezone.now', return_value=first_time + timedelta(hours=2, minutes=30)):
            qr.mark_scan(self.manager, self.token, self.shift.pk, 'out')
        qr.mark_scan(self.manager, self.token, self.shift.pk, 'out')
        record.refresh_from_db()
        self.assertEqual(record.exited_at, first_time + timedelta(hours=2, minutes=30))
        self.part.refresh_from_db()
        self.volunteer.refresh_from_db()
        self.assertEqual(float(self.part.hours), 2.5)
        self.assertEqual(float(self.volunteer.total_hours), 2.5)
        self.assertEqual(ShiftAttendance.objects.count(), 1)

    def test_delegated_access_is_scoped_and_can_be_revoked(self):
        Const.objects.update_or_create(name='qr_scanner_scoped_access', defaults={'value': 1})
        delegate = f.make_user()
        with self.assertRaises(PermissionDenied):
            qr.scan_context(delegate, self.token)
        grant = qr.grant_scanner(self.manager, delegate, self.group)
        self.assertTrue(qr.can_scan(delegate))
        qr.mark_scan(delegate, self.token, self.shift.pk, 'in')
        other = f.make_event(event_group=EventGroup.objects.create(title='Другой'))
        other_shift = f.make_shift(other)
        f.make_participation(self.volunteer, other_shift, status='pending')
        self.assertIn(other_shift.pk, [row['shift'].pk for row in qr.scan_context(delegate, self.token)['shift_rows']])
        with self.assertRaises(PermissionDenied):
            qr.mark_scan(delegate, self.token, other_shift.pk, 'in')
        qr.revoke_scanner(self.manager, grant.pk)
        self.assertFalse(qr.can_scan(delegate))

    def test_default_mode_allows_scanner_operator_to_mark_other_events(self):
        delegate = f.make_user()
        qr.grant_scanner(self.manager, delegate, self.group)
        other = f.make_event(event_group=EventGroup.objects.create(title='Другой'))
        shift = f.make_shift(other)
        f.make_participation(self.volunteer, shift, status='pending', hours=0)
        qr.mark_scan(delegate, self.token, shift.pk, 'in')
        self.assertTrue(ShiftAttendance.objects.filter(user=self.volunteer, shift=shift).exists())

    def test_exit_without_entry_unknown_qr_and_closed_position_are_rejected(self):
        with self.assertRaises(ValidationError):
            qr.mark_scan(self.manager, self.token, self.shift.pk, 'out')
        with self.assertRaises(ValidationError):
            qr.scan_context(self.manager, 'not-a-token')
        self.position.event_status = 'finished'
        self.position.save()
        with self.assertRaises(ValidationError):
            qr.mark_scan(self.manager, self.token, self.shift.pk, 'in')

    def test_scan_is_csrf_protected_and_requires_scanner_permission(self):
        self.client.force_login(self.volunteer)
        self.assertEqual(self.client.get(reverse('qr_scanner')).status_code, 403)
        self.assertEqual(self.client.post(reverse('qr_scan'), {'token': self.token}).status_code, 403)
        self.client.force_login(self.manager)
        response = self.client.post(reverse('qr_scan'), {'token': self.token})
        self.assertContains(response, self.volunteer.full_name)
        self.assertContains(response, 'Ближайшая смена')
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager)
        self.assertEqual(csrf_client.post(reverse('qr_scan'), {'token': self.token}).status_code, 403)

    def test_team_leader_uses_scanner_but_only_manager_grants_access(self):
        self.client.force_login(f.make_team_leader())
        self.assertEqual(self.client.get(reverse('qr_scanner')).status_code, 200)
        self.assertEqual(self.client.get(reverse('qr_scanner_grant')).status_code, 403)
        self.client.force_login(self.manager)
        response = self.client.post(reverse('qr_scanner_grant'), {
            'user': self.volunteer.pk, 'event_group': self.group.pk,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['redirect'], reverse('qr_scanner'))
        self.assertTrue(ScannerGrant.objects.filter(user=self.volunteer, revoked_at=None).exists())

    def test_shift_order_future_then_earliest_past_of_ongoing_event(self):
        now = timezone.now()
        old = f.make_shift(self.position, start_time=now - timedelta(days=2), end_time=now - timedelta(days=2, hours=-1))
        recent = f.make_shift(self.position, start_time=now - timedelta(days=1), end_time=now - timedelta(days=1, hours=-1))
        for shift in (old, recent):
            f.make_participation(self.volunteer, shift, status='pending', hours=0)
        rows = qr.scan_context(self.manager, self.token)['shift_rows']
        self.assertEqual([r['shift'].pk for r in rows], [self.shift.pk, old.pk, recent.pk])

    def test_manually_marked_shift_is_not_offered_for_registration(self):
        self.part.status = 'attended'
        self.part.save()
        self.assertEqual(qr.scan_context(self.manager, self.token)['shift_rows'], [])


class QRCardAndEnrollmentTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.volunteer = f.make_user()
        self.group = EventGroup.objects.create(title='Фестиваль')
        self.position = f.make_event(event_group=self.group)
        self.token = qr.personal_token(self.volunteer)
        self.client.force_login(self.manager)

    def shift_at(self, start, **kwargs):
        return f.make_shift(self.position, day=timezone.localdate(start), start_time=start,
                            end_time=start + timedelta(hours=2), **kwargs)

    def test_card_has_profile_link_table_and_latest_mark_after_exit(self):
        shift = self.shift_at(timezone.now() + timedelta(minutes=15))
        f.make_participation(self.volunteer, shift, status='pending', hours=0)
        qr.mark_scan(self.manager, self.token, shift.pk, 'in')
        qr.mark_scan(self.manager, self.token, shift.pk, 'out')
        response = self.client.post(reverse('qr_scan'), {'token': self.token})
        self.assertContains(response, reverse('profile_detail', args=[self.volunteer.pk]))
        self.assertContains(response, 'Последняя отмеченная смена')
        self.assertContains(response, 'data-qr-shifts-table')
        self.assertEqual(response.context['last_attendance'].shift_id, shift.pk)

    def test_existing_entry_is_checked_and_exit_uses_checkbox(self):
        shift = self.shift_at(timezone.now() + timedelta(minutes=10))
        f.make_participation(self.volunteer, shift, status='pending', hours=0)
        qr.mark_scan(self.manager, self.token, shift.pk, 'in')
        response = self.client.post(reverse('qr_scan'), {'token': self.token})
        self.assertContains(response, 'type="checkbox"')
        self.assertContains(response, 'data-qr-mark="out"')
        self.assertContains(response, 'checked disabled')

    def test_card_opens_for_registered_user_with_incomplete_name(self):
        self.volunteer.first_name = None
        self.volunteer.last_name = None
        self.volunteer.save(update_fields=['first_name', 'last_name'])
        response = self.client.post(reverse('qr_scan'), {'token': self.token})
        self.assertContains(response, 'data-qr-result')

    def test_enroll_tomorrow_is_approved_but_has_no_entry(self):
        from blog.models import Application, ApplicationShiftDecision
        shift = self.shift_at(timezone.now() + timedelta(days=1))
        qr.enroll_scanned_user(self.manager, self.token, shift.pk)
        part = Participation.objects.get(user=self.volunteer, event_day=shift)
        self.assertEqual((part.status, part.hours), ('pending', 0))
        self.assertFalse(ShiftAttendance.objects.filter(user=self.volunteer, shift=shift).exists())
        self.assertTrue(ApplicationShiftDecision.objects.filter(application__user=self.volunteer, shift=shift, status='approved').exists())
        qr.enroll_scanned_user(self.manager, self.token, shift.pk)
        self.assertEqual(Application.objects.filter(user=self.volunteer, event=self.position).count(), 1)
        self.assertEqual(Participation.objects.filter(user=self.volunteer, event_day=shift).count(), 1)

    def test_enroll_ongoing_or_within_one_hour_records_entry_once(self):
        now = timezone.now()
        for offset in (-30, 30, 60):
            with self.subTest(offset=offset):
                shift = self.shift_at(now + timedelta(minutes=offset))
                with patch('django.utils.timezone.now', return_value=now):
                    qr.enroll_scanned_user(self.manager, self.token, shift.pk)
                entry = ShiftAttendance.objects.get(user=self.volunteer, shift=shift)
                self.assertEqual(entry.entered_at, now)
                qr.enroll_scanned_user(self.manager, self.token, shift.pk)
                entry.refresh_from_db()
                self.assertEqual(entry.entered_at, now)

    def test_enrolling_another_shift_preserves_existing_application_selections(self):
        from blog.models import Application, ApplicationShiftDecision
        first = self.shift_at(timezone.now() + timedelta(days=1))
        second = self.shift_at(timezone.now() + timedelta(days=2))
        app = f.make_application(self.position, user=self.volunteer, shifts=[first], status='new')
        qr.enroll_scanned_user(self.manager, self.token, second.pk)
        self.assertEqual(Application.objects.filter(user=self.volunteer).count(), 1)
        self.assertEqual(set(app.selected_shifts.values_list('pk', flat=True)), {first.pk, second.pk})
        self.assertEqual(ApplicationShiftDecision.objects.get(application=app, shift=first).status, 'new')
        self.assertEqual(ApplicationShiftDecision.objects.get(application=app, shift=second).status, 'approved')

    def test_picker_lists_only_open_not_ended_not_already_enrolled_shifts(self):
        open_shift = self.shift_at(timezone.now() + timedelta(days=1))
        self.shift_at(timezone.now() + timedelta(days=1), recruit_status='closed')
        self.shift_at(timezone.now() - timedelta(days=1))
        enrolled = self.shift_at(timezone.now() + timedelta(days=2))
        f.make_participation(self.volunteer, enrolled, status='pending')
        context = qr.scan_context(self.manager, self.token)
        self.assertEqual([shift.pk for shift in context['enrollment_shifts']], [open_shift.pk])

    def test_enrollment_rejects_closed_shift_and_non_scanner_user(self):
        shift = self.shift_at(timezone.now() + timedelta(days=1), recruit_status='closed')
        with self.assertRaises(ValidationError):
            qr.enroll_scanned_user(self.manager, self.token, shift.pk)
        self.client.force_login(f.make_user())
        response = self.client.post(reverse('qr_enroll'), {'token': self.token, 'shift_id': shift.pk})
        self.assertEqual(response.status_code, 403)

    def test_enrollment_endpoint_returns_refreshed_card_and_notice(self):
        shift = self.shift_at(timezone.now() + timedelta(days=1))
        response = self.client.post(reverse('qr_enroll'), {'token': self.token, 'shift_id': shift.pk})
        self.assertContains(response, 'data-qr-result')
        self.assertContains(response, 'Записан на смену')
        self.assertEqual(response.context['nearest_shift'].pk, shift.pk)

    def test_enrollment_scope_is_enforced_for_picker_and_direct_request(self):
        operator = f.make_user()
        qr.grant_scanner(self.manager, operator, self.group)
        own = self.shift_at(timezone.now() + timedelta(days=1))
        other = f.make_shift(f.make_event(event_group=EventGroup.objects.create(title='Другое')))
        Const.objects.update_or_create(name='qr_scanner_scoped_access', defaults={'value': 1})
        self.assertEqual([s.pk for s in qr.scan_context(operator, self.token)['enrollment_shifts']], [own.pk])
        with self.assertRaises(PermissionDenied):
            qr.enroll_scanned_user(operator, self.token, other.pk)
        qr.enroll_scanned_user(operator, self.token, own.pk)
        self.assertTrue(Participation.objects.filter(user=self.volunteer, event_day=own).exists())

    def test_enrollment_checks_requirements_before_approving_existing_application(self):
        from blog.models import EventRequirementMap, UserRequirementException
        requirement = f.make_requirement(title='Допуск')
        EventRequirementMap.objects.create(event=self.position, requirement=requirement)
        UserRequirementException.objects.create(user=self.volunteer, requirement=requirement)
        shift = self.shift_at(timezone.now() + timedelta(days=1))
        app = f.make_application(self.position, user=self.volunteer, shifts=[shift])
        with self.assertRaises(ValidationError):
            qr.enroll_scanned_user(self.manager, self.token, shift.pk)
        app.refresh_from_db()
        self.assertEqual(app.status, 'new')
        self.assertFalse(Participation.objects.filter(user=self.volunteer).exists())

    def test_checkin_lead_time_is_configurable_and_later_shift_stays_pending(self):
        Const.objects.create(name='qr_enroll_checkin_lead_minutes', value=30)
        shift = self.shift_at(timezone.now() + timedelta(minutes=45))
        qr.enroll_scanned_user(self.manager, self.token, shift.pk)
        self.assertEqual(Participation.objects.get(user=self.volunteer, event_day=shift).status, 'pending')
        self.assertFalse(ShiftAttendance.objects.filter(user=self.volunteer).exists())

    def test_enrollment_requires_session_and_csrf(self):
        shift = self.shift_at(timezone.now() + timedelta(days=1))
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('qr_enroll'), {'token': self.token, 'shift_id': shift.pk}).status_code, 403)
        client.force_login(self.manager)
        self.assertEqual(client.post(reverse('qr_enroll'), {'token': self.token, 'shift_id': shift.pk}).status_code, 403)
        self.assertEqual(self.client.get(reverse('qr_enroll')).status_code, 405)


class MoscowTimeTests(TestCase):
    def test_incidents_do_not_include_yesterday_in_moscow(self):
        from blog.services.incidents import sync_ongoing_event_incidents
        from blog.models import Incident
        event = f.make_event()
        f.make_shift(event, day=datetime(2026, 11, 2).date())
        instant = datetime(2026, 11, 2, 22, 30, tzinfo=dt_timezone.utc)
        with patch('django.utils.timezone.now', return_value=instant):
            sync_ongoing_event_incidents()
        self.assertFalse(Incident.objects.filter(related_event=event, kind='event_ongoing', resolved_at=None).exists())

    def test_application_shift_picker_shows_moscow_time(self):
        event = f.make_event()
        start = datetime(2026, 11, 2, 22, 30, tzinfo=dt_timezone.utc)
        f.make_shift(event, day=datetime(2026, 11, 3).date(), start_time=start, end_time=start + timedelta(hours=2))
        self.client.force_login(f.make_user())
        with patch('django.utils.timezone.now', return_value=start - timedelta(hours=1)):
            response = self.client.get(reverse('event_shifts_json', args=[event.pk]))
        self.assertIn('01:30', response.json()['shifts'][0]['label'])

    def test_calendar_status_and_formatters_use_moscow_after_utc_midnight_boundary(self):
        instant = datetime(2026, 11, 2, 22, 30, tzinfo=dt_timezone.utc)
        event = f.make_event()
        shift = f.make_shift(event, day=datetime(2026, 11, 3).date())
        with patch('django.utils.timezone.now', return_value=instant):
            self.assertEqual(event.compute_status(), 'ongoing')
            self.assertEqual(shift.compute_status(), 'ongoing')
        self.assertEqual(fmt_dt(instant), '03.11.2026 01:30')
        self.assertEqual(fmt_date(instant), '03.11.2026')


class AttendanceClosingTests(TestCase):
    def test_pending_attendance_and_open_entry_block_closing(self):
        event = f.make_event()
        shift = f.make_shift(event, days_from_now=-2)
        user = f.make_user()
        part = f.make_participation(user, shift, status='pending', hours=0)
        self.assertFalse(event_closing_checklist(event)['ready'])
        part.status = 'attended'
        part.save()
        entry = ShiftAttendance.objects.create(user=user, shift=shift)
        self.assertFalse(event_closing_checklist(event)['ready'])
        entry.exited_at = timezone.now()
        entry.save()
        self.assertTrue(event_closing_checklist(event)['ready'])
