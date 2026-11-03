"""Сквозные веб-потоки — самая ценная страховка перед переносом ORM (Фаза 2).

Гоняют реальный пайплайн через HTTP-эндпоинты (как менеджер в браузере) и проверяют,
что данные обрабатываются правильно: обработка заявки создаёт участие и пересчитывает
агрегаты; корректировка часов меняет total_hours; отклонение убирает участие.
Инварианты — из blog/services/applications.py и stats.py.
"""
from django.test import TestCase
from django.urls import reverse

from blog.models import Participation, ApplicationShiftDecision
from . import factories as f


class ApplicationApprovalFlowTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        # Смена в прошлом? Нет — набор открыт (будущее). Длительность 4ч (start..end).
        self.shift = f.make_shift(self.event, days_from_now=2)
        self.volunteer = f.make_user()
        self.application = f.make_application(
            self.event, user=self.volunteer, shifts=[self.shift], status='new'
        )

    def test_approve_shift_creates_participation_and_recalcs(self):
        url = reverse('application_shift_process', args=[self.application.id, self.shift.id])
        r = self.client.post(url, {'status': 'approved'})
        self.assertEqual(r.status_code, 302)

        # Участие создано по выбранной смене.
        part = Participation.objects.filter(user=self.volunteer, event_day=self.shift).first()
        self.assertIsNotNone(part, 'approve должен создать Participation')
        self.assertEqual(part.status, 'pending')

        # Решение по смене зафиксировано.
        dec = ApplicationShiftDecision.objects.get(application=self.application, shift=self.shift)
        self.assertEqual(dec.status, 'approved')

        # Одобрение ещё не подтверждает присутствие и не начисляет часы.
        self.volunteer.refresh_from_db()
        self.assertEqual(self.volunteer.total_hours, part.hours)
        self.assertEqual(self.volunteer.total_event_count, 0)

    def test_reject_shift_removes_participation(self):
        # Сначала одобряем — появляется участие.
        approve = reverse('application_shift_process', args=[self.application.id, self.shift.id])
        self.client.post(approve, {'status': 'approved'})
        self.assertTrue(Participation.objects.filter(user=self.volunteer, event_day=self.shift).exists())

        # Затем отклоняем (резерв) — участие должно исчезнуть.
        self.client.post(approve, {'status': 'rejected'})
        self.assertFalse(
            Participation.objects.filter(user=self.volunteer, event_day=self.shift).exists(),
            'reject должен убрать участие из этой смены',
        )
        self.volunteer.refresh_from_db()
        self.assertEqual(self.volunteer.total_hours, 0)

    def test_invalid_status_rejected(self):
        url = reverse('application_shift_process', args=[self.application.id, self.shift.id])
        r = self.client.post(url, {'status': 'garbage'})
        self.assertEqual(r.status_code, 302)  # редирект с messages.error
        self.assertFalse(
            ApplicationShiftDecision.objects.filter(
                application=self.application, shift=self.shift
            ).exclude(status='new').exists()
        )


class ParticipationHoursFlowTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=1)
        self.volunteer = f.make_user()
        self.part = f.make_participation(self.volunteer, self.shift, status='attended', hours=4)
        # Пересчитываем базовые агрегаты.
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(self.volunteer)

    def test_set_hours_updates_aggregates(self):
        url = reverse('participation_set_hours', args=[self.part.id])
        r = self.client.post(url, {'hours': '7'})
        self.assertEqual(r.status_code, 200)
        self.part.refresh_from_db()
        self.assertEqual(self.part.hours, 7)
        self.assertTrue(self.part.hours_overridden)
        self.volunteer.refresh_from_db()
        self.assertEqual(self.volunteer.total_hours, 7)

    def test_negative_hours_rejected(self):
        url = reverse('participation_set_hours', args=[self.part.id])
        r = self.client.post(url, {'hours': '-3'})
        self.assertEqual(r.status_code, 400)
        self.part.refresh_from_db()
        self.assertEqual(self.part.hours, 4)  # не изменилось


class AccessControlFlowTests(TestCase):
    """Волонтёр не может обрабатывать чужие заявки (ACL на бэкенде)."""

    def test_volunteer_cannot_process_application(self):
        event = f.make_event()
        shift = f.make_shift(event)
        applicant = f.make_user()
        app = f.make_application(event, user=applicant, shifts=[shift])

        outsider = f.make_user()
        self.client.force_login(outsider)
        url = reverse('application_shift_process', args=[app.id, shift.id])
        r = self.client.post(url, {'status': 'approved'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Participation.objects.filter(user=applicant, event_day=shift).exists())
