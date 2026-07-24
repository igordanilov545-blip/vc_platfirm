"""Заявки от лица волонтёра (создание/редактирование/отмена), массовая обработка
заявок менеджером/ТЛ, и правки явки/часов участия — до этого теста были покрыты
только `application_shift_process` (обработка по одной смене, test_web_flows.py) и
косвенно бизнес-логика сервисов (test_bot_applications.py). Сами HTTP-вьюхи создания
заявки волонтёром, ручного добавления менеджером, массового approve и правки явки
через форму/AJAX не имели ни одного теста.
"""
from django.test import TestCase
from django.urls import reverse

from blog.models import Application, Participation
from . import factories as f


class ApplicationCreateTests(TestCase):
    def setUp(self):
        self.volunteer = f.make_user()
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=5)

    def test_create_application_via_web(self):
        self.client.force_login(self.volunteer)
        r = self.client.post(reverse('application_create'), {
            'event': self.event.id, 'functions': '', 'role_in_event': '',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Application.objects.filter(event=self.event, user=self.volunteer).exists())

    def test_incomplete_profile_blocked_with_json_hint(self):
        incomplete = f.make_user(first_name='', telegram_username='', phone='')
        self.client.force_login(incomplete)
        r = self.client.post(reverse('application_create'), {
            'event': self.event.id,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('profile_incomplete'))
        self.assertFalse(Application.objects.filter(event=self.event, user=incomplete).exists())

    def test_duplicate_application_redirects_to_edit(self):
        existing = f.make_application(self.event, user=self.volunteer, shifts=[self.shift], status='new')
        self.client.force_login(self.volunteer)
        r = self.client.post(reverse('application_create'), {
            'event': self.event.id,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertIn(str(existing.id), r.json().get('redirect', ''))

    def test_cannot_apply_to_unpublished_event(self):
        unpublished = f.make_event(published=False)
        self.client.force_login(self.volunteer)
        r = self.client.post(reverse('application_create'), {'event': unpublished.id})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Application.objects.filter(event=unpublished, user=self.volunteer).exists())

    def test_cannot_apply_to_unpublished_event_ajax_returns_json_redirect(self):
        """Модалка application_create открывается по data-modal (AJAX) — голый
        HTTP-redirect() тут «проглатывается» fetch'ем (coding-principles.md §7)."""
        unpublished = f.make_event(published=False)
        self.client.force_login(self.volunteer)
        r = self.client.post(reverse('application_create'), {'event': unpublished.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertIn('redirect', r.json())

    def test_closed_recruit_goes_to_reserve(self):
        self.shift.recruit_status = 'closed'
        self.shift.save(update_fields=['recruit_status'])
        self.client.force_login(self.volunteer)
        self.client.post(reverse('application_create'), {'event': self.event.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        app = Application.objects.get(event=self.event, user=self.volunteer)
        self.assertEqual(app.status, 'rejected')
        self.assertIn('закрыт', app.auto_reject_reason)


class ApplicationManualCreateTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        f.make_shift(self.event, days_from_now=3)

    def test_manager_adds_volunteers_manually(self):
        v1 = f.make_user()
        v2 = f.make_user()
        r = self.client.post(reverse('application_manual_create'), {
            'event': self.event.id, 'users': [v1.id, v2.id],
        })
        self.assertIn(r.status_code, (200, 302))
        self.assertEqual(Application.objects.filter(event=self.event).count(), 2)

    def test_missing_users_returns_400(self):
        r = self.client.post(reverse('application_manual_create'), {'event': self.event.id, 'users': []})
        self.assertEqual(r.status_code, 400)

    def test_missing_event_returns_400(self):
        r = self.client.post(reverse('application_manual_create'), {'users': [f.make_user().id]})
        self.assertEqual(r.status_code, 400)

    def test_forbidden_for_volunteer(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.get(reverse('application_manual_create'))
        self.assertEqual(r.status_code, 403)


class ApplicationEditTests(TestCase):
    def setUp(self):
        self.volunteer = f.make_user()
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=5)
        self.app = f.make_application(self.event, user=self.volunteer, shifts=[self.shift], status='new')

    def test_owner_can_edit(self):
        self.client.force_login(self.volunteer)
        r = self.client.post(reverse('application_edit', args=[self.app.id]), {
            'event': self.event.id, 'functions': 'Новая функция', 'role_in_event': '',
        })
        self.assertIn(r.status_code, (200, 302))
        self.app.refresh_from_db()
        self.assertEqual(self.app.functions, 'Новая функция')

    def test_cannot_edit_others_application(self):
        outsider = f.make_user()
        self.client.force_login(outsider)
        r = self.client.get(reverse('application_edit', args=[self.app.id]))
        self.assertEqual(r.status_code, 404)

    def test_inactive_application_cannot_be_edited(self):
        self.app.status = 'cancelled'
        self.app.save(update_fields=['status'])
        self.client.force_login(self.volunteer)
        r = self.client.get(reverse('application_edit', args=[self.app.id]))
        self.assertEqual(r.status_code, 302)


class ApplicationCancelTests(TestCase):
    def test_cancel_far_shift(self):
        f.make_const('late_cancel_hours', 24)
        volunteer = f.make_user()
        event = f.make_event()
        shift = f.make_shift(event, days_from_now=5)
        app = f.make_application(event, user=volunteer, shifts=[shift], status='new')
        self.client.force_login(volunteer)
        r = self.client.post(reverse('application_cancel', args=[app.id]), {'reason': 'передумал'})
        self.assertIn(r.status_code, (200, 302))
        app.refresh_from_db()
        self.assertEqual(app.status, 'cancelled')

    def test_cancel_others_application_404(self):
        volunteer = f.make_user()
        event = f.make_event()
        app = f.make_application(event, user=volunteer)
        outsider = f.make_user()
        self.client.force_login(outsider)
        r = self.client.get(reverse('application_cancel', args=[app.id]))
        self.assertEqual(r.status_code, 404)


class EventShiftsJsonTests(TestCase):
    def test_returns_upcoming_shifts(self):
        volunteer = f.make_user()
        event = f.make_event()
        f.make_shift(event, days_from_now=3)
        self.client.force_login(volunteer)
        r = self.client.get(reverse('event_shifts_json', args=[event.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['shifts']), 1)


class ApplicationProcessTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=3)
        self.volunteer = f.make_user()
        self.app = f.make_application(self.event, user=self.volunteer, shifts=[self.shift], status='new')

    def test_approve_application(self):
        r = self.client.post(reverse('application_process', args=[self.app.id]), {'status': 'approved'})
        self.assertEqual(r.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'approved')

    def test_invalid_status_rejected(self):
        r = self.client.post(reverse('application_process', args=[self.app.id]), {'status': 'garbage'})
        self.assertEqual(r.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'new')

    def test_forbidden_on_finished_event(self):
        self.event.event_status = 'finished'
        self.event.save(update_fields=['event_status'])
        r = self.client.post(reverse('application_process', args=[self.app.id]), {'status': 'approved'})
        self.assertEqual(r.status_code, 403)


class ShiftApplicationsApproveAllTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=3)

    def test_approve_all_on_shift(self):
        for _ in range(3):
            f.make_application(self.event, shifts=[self.shift], status='new')
        r = self.client.post(reverse('shift_applications_approve_all', args=[self.event.id, self.shift.id]))
        self.assertEqual(r.status_code, 302)
        from blog.models import ApplicationShiftDecision
        approved = ApplicationShiftDecision.objects.filter(shift=self.shift, status='approved').count()
        self.assertEqual(approved, 3)

    def test_no_pending_is_noop(self):
        r = self.client.post(reverse('shift_applications_approve_all', args=[self.event.id, self.shift.id]))
        self.assertEqual(r.status_code, 302)


class ApplicationProcessAllTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=3, volunteer_needed=10)

    def test_approve_all_no_overflow(self):
        for _ in range(2):
            f.make_application(self.event, shifts=[self.shift], status='new')
        r = self.client.post(reverse('event_application_process_all', args=[self.event.id]), {'confirm': 'yes'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Application.objects.filter(event=self.event, status='approved').count(), 2)

    def test_overflow_shows_confirmation_first(self):
        self.shift.volunteer_needed = 1
        self.shift.save(update_fields=['volunteer_needed'])
        for _ in range(3):
            f.make_application(self.event, shifts=[self.shift], status='new')
        r = self.client.post(reverse('event_application_process_all', args=[self.event.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Application.objects.filter(event=self.event, status='approved').count(), 0)

    def test_no_pending_applications_noop(self):
        r = self.client.post(reverse('event_application_process_all', args=[self.event.id]))
        self.assertEqual(r.status_code, 302)

    def test_global_process_all_requires_manager(self):
        tl = f.make_team_leader()
        self.client.force_login(tl)
        r = self.client.post(reverse('application_process_all'))
        self.assertEqual(r.status_code, 403)


class ParticipationEditTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=-1)
        self.volunteer = f.make_user()
        self.part = f.make_participation(self.volunteer, self.shift, status='attended', hours=4)

    def test_set_status_updates_hours_and_recalcs(self):
        url = reverse('participation_set_status', args=[self.part.id])
        r = self.client.post(url, {'status': 'absent_excused'})
        self.assertEqual(r.status_code, 200)
        self.part.refresh_from_db()
        self.assertEqual(self.part.status, 'absent_excused')
        self.assertEqual(self.part.hours, 0)

    def test_set_status_no_show_applies_churn(self):
        url = reverse('participation_set_status', args=[self.part.id])
        r = self.client.post(url, {'status': 'absent_unexcused'})
        self.assertEqual(r.status_code, 200)
        self.volunteer.refresh_from_db()
        self.assertGreater(self.volunteer.churn_score or 0, 0)

    def test_set_status_invalid_value(self):
        r = self.client.post(reverse('participation_set_status', args=[self.part.id]), {'status': 'bogus'})
        self.assertEqual(r.status_code, 400)

    def test_set_status_forbidden_on_finished_event(self):
        self.event.event_status = 'finished'
        self.event.save(update_fields=['event_status'])
        r = self.client.post(reverse('participation_set_status', args=[self.part.id]), {'status': 'attended'})
        self.assertEqual(r.status_code, 403)

    def test_participation_edit_form(self):
        r = self.client.post(reverse('participation_edit', args=[self.part.id]), {
            'status': 'attended', 'hours': '6', 'full_shift': 'on',
        })
        self.assertIn(r.status_code, (200, 302))
        self.part.refresh_from_db()
        self.assertEqual(self.part.hours, 6)
        self.assertTrue(self.part.hours_overridden)

    def test_volunteer_cannot_edit_participation(self):
        outsider = f.make_user()
        self.client.force_login(outsider)
        r = self.client.post(reverse('participation_set_status', args=[self.part.id]), {'status': 'attended'})
        self.assertEqual(r.status_code, 403)


class ProfileCommentAddTests(TestCase):
    def setUp(self):
        self.target = f.make_user()

    def test_manager_can_comment(self):
        manager = f.make_manager()
        self.client.force_login(manager)
        r = self.client.post(reverse('profile_comment_add', args=[self.target.id]), {'text': 'Заметка'})
        self.assertIn(r.status_code, (200, 302))
        from blog.models import UserComment
        self.assertTrue(UserComment.objects.filter(target_user=self.target, text='Заметка').exists())

    def test_plain_volunteer_forbidden(self):
        author = f.make_user()
        self.client.force_login(author)
        r = self.client.post(reverse('profile_comment_add', args=[self.target.id]), {'text': 'x'})
        self.assertEqual(r.status_code, 403)

    def test_cannot_comment_on_self(self):
        self.client.force_login(self.target)
        r = self.client.post(reverse('profile_comment_add', args=[self.target.id]), {'text': 'x'})
        self.assertEqual(r.status_code, 403)


class IncidentResolveTests(TestCase):
    def test_manager_resolves_incident(self):
        from blog.models import Incident
        manager = f.make_manager()
        incident = Incident.objects.create(kind='pgas_verification', related_user=f.make_user())
        self.client.force_login(manager)
        r = self.client.post(reverse('incident_resolve', args=[incident.id]))
        self.assertEqual(r.status_code, 302)
        incident.refresh_from_db()
        self.assertIsNotNone(incident.resolved_at)

    def test_volunteer_forbidden(self):
        from blog.models import Incident
        incident = Incident.objects.create(kind='pgas_verification', related_user=f.make_user())
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.post(reverse('incident_resolve', args=[incident.id]))
        self.assertEqual(r.status_code, 403)
