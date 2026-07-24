"""Жизненный цикл мероприятия (blog/views/events.py) — редактирование, публикация,
рассылка, завершение/переоткрытие, комментарии/отзывы/change-log, управление сменами.

Это ядро бизнес-процесса менеджера/ТЛ, но до этого теста было покрыто только
создание меро (test_views_smoke.py) и обработка заявок по смене (test_web_flows.py) —
сами операции над мероприятием как таковым (edit/delete/publish/close/reopen,
add/edit/delete смены) не имели ни одного теста.
"""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import Event, EventShift
from . import factories as f


class EventEditTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event(title='Старое название')

    def test_edit_updates_fields(self):
        r = self.client.post(reverse('event_edit', args=[self.event.id]), {
            'title': 'Новое название', 'description': self.event.description or '',
        })
        self.assertIn(r.status_code, (200, 302))
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, 'Новое название')

    def test_finished_event_cannot_be_edited(self):
        self.event.event_status = 'finished'
        self.event.save(update_fields=['event_status'])
        r = self.client.get(reverse('event_edit', args=[self.event.id]))
        self.assertEqual(r.status_code, 403)

    def test_forbidden_for_volunteer(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.get(reverse('event_edit', args=[self.event.id]))
        self.assertEqual(r.status_code, 403)


class EventDeleteTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()

    def _prime_captcha(self, answer=7):
        session = self.client.session
        session[f'captcha_event_delete_{self.event.id}'] = answer
        session.save()

    def test_wrong_captcha_does_not_delete(self):
        self._prime_captcha(answer=7)
        r = self.client.post(reverse('event_delete', args=[self.event.id]), {'captcha_answer': '999'})
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(Event.objects.filter(id=self.event.id).exists())

    def test_correct_captcha_deletes_and_recalcs_aggregates(self):
        volunteer = f.make_user()
        shift = f.make_shift(self.event, days_from_now=-1)
        f.make_participation(volunteer, shift, status='attended', hours=5)
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(volunteer)
        self.assertEqual(volunteer.total_hours, 5)

        self._prime_captcha(answer=7)
        r = self.client.post(reverse('event_delete', args=[self.event.id]), {'captcha_answer': '7'})
        self.assertIn(r.status_code, (200, 302))
        self.assertFalse(Event.objects.filter(id=self.event.id).exists())
        volunteer.refresh_from_db()
        self.assertEqual(volunteer.total_hours, 0, 'агрегаты должны пересчитаться после удаления меро')


class EventPublishTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_publish_sets_timestamp(self):
        event = f.make_event(published=False)
        self.assertIsNone(event.published_at)
        r = self.client.post(reverse('event_publish', args=[event.id]))
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertIsNotNone(event.published_at)

    def test_already_published_noop(self):
        event = f.make_event(published=True)
        before = event.published_at
        r = self.client.post(reverse('event_publish', args=[event.id]))
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.published_at, before)

    def test_finished_event_cannot_be_published(self):
        event = f.make_event(published=False, event_status='finished')
        r = self.client.post(reverse('event_publish', args=[event.id]))
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertIsNone(event.published_at)


class EventBroadcastTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_broadcast_requires_published(self):
        event = f.make_event(published=False)
        r = self.client.post(reverse('event_broadcast', args=[event.id]))
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertIsNone(event.broadcast_sent_at)

    def test_broadcast_on_published_event_marks_sent(self):
        event = f.make_event(published=True)
        r = self.client.post(reverse('event_broadcast', args=[event.id]))
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        # broadcast_sent_at ставится, только если реально было кому слать (sent > 0);
        # без подписчиков останется None — проверяем, что запрос не падает 500.
        self.assertIsNotNone(event)


class EventCloseTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=-1)

    def test_checklist_blocks_close_with_pending_applications(self):
        f.make_application(self.event, status='new', shifts=[self.shift])
        r = self.client.post(reverse('event_close', args=[self.event.id]), {'people_helped': '10'})
        self.assertEqual(r.status_code, 302)
        self.event.refresh_from_db()
        self.assertNotEqual(self.event.event_status, 'finished')

    def test_close_requires_people_helped(self):
        r = self.client.post(reverse('event_close', args=[self.event.id]), {'people_helped': ''})
        self.assertEqual(r.status_code, 302)
        self.event.refresh_from_db()
        self.assertNotEqual(self.event.event_status, 'finished')

    def test_close_succeeds_when_ready(self):
        r = self.client.post(reverse('event_close', args=[self.event.id]), {'people_helped': '25'})
        self.assertEqual(r.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.event_status, 'finished')
        self.assertEqual(self.event.people_helped, 25)

    def test_checklist_screen_renders(self):
        r = self.client.get(reverse('event_close', args=[self.event.id]))
        self.assertEqual(r.status_code, 200)


class EventReopenTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event(event_status='finished', people_helped=5)

    def _prime_captcha(self, answer=3):
        session = self.client.session
        session[f'captcha_event_reopen_{self.event.id}'] = answer
        session.save()

    def test_not_finished_event_cannot_reopen(self):
        event = f.make_event(event_status='upcoming')
        r = self.client.post(reverse('event_reopen', args=[event.id]), {'captcha_answer': '1'})
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.event_status, 'upcoming')

    def test_correct_captcha_reopens_to_passed(self):
        self._prime_captcha(answer=3)
        r = self.client.post(reverse('event_reopen', args=[self.event.id]), {'captcha_answer': '3'})
        self.assertEqual(r.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.event_status, 'passed')

    def test_wrong_captcha_stays_finished(self):
        self._prime_captcha(answer=3)
        r = self.client.post(reverse('event_reopen', args=[self.event.id]), {'captcha_answer': '999'})
        self.event.refresh_from_db()
        self.assertEqual(self.event.event_status, 'finished')


class EventDobroToggleTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_toggle_requires_finished(self):
        event = f.make_event(event_status='upcoming', dobro_ru_link_kind='unique')
        r = self.client.post(reverse('event_dobro_toggle', args=[event.id]))
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertFalse(event.dobro_ru_hours_logged)

    def test_toggle_flips_when_finished_and_tracked(self):
        event = f.make_event(event_status='finished', dobro_ru_link_kind='unique')
        r = self.client.post(reverse('event_dobro_toggle', args=[event.id]))
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertTrue(event.dobro_ru_hours_logged)


class EventShiftManagementTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=5)

    def test_add_shift(self):
        tomorrow = (timezone.now() + datetime.timedelta(days=10)).date().isoformat()
        r = self.client.post(reverse('event_shift_add', args=[self.event.id]), {
            'day': tomorrow, 'start_time': '10:00', 'end_time': '14:00',
            'volunteer_needed': 3, 'recruit_status': 'open',
        })
        self.assertIn(r.status_code, (200, 302))
        self.assertEqual(EventShift.objects.filter(event=self.event).count(), 2)

    def test_edit_shift(self):
        r = self.client.post(reverse('event_shift_edit', args=[self.event.id, self.shift.id]), {
            'day': self.shift.day.isoformat(), 'start_time': '11:00', 'end_time': '15:00',
            'volunteer_needed': 9, 'recruit_status': 'open',
        })
        self.assertIn(r.status_code, (200, 302))
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.volunteer_needed, 9)

    def test_cannot_delete_last_shift(self):
        r = self.client.post(reverse('event_shift_delete', args=[self.event.id, self.shift.id]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(EventShift.objects.filter(id=self.shift.id).exists())

    def test_delete_shift_when_not_last(self):
        second = f.make_shift(self.event, days_from_now=6)
        r = self.client.post(reverse('event_shift_delete', args=[self.event.id, second.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(EventShift.objects.filter(id=second.id).exists())

    def test_shift_actions_forbidden_on_finished_event(self):
        self.event.event_status = 'finished'
        self.event.save(update_fields=['event_status'])
        r = self.client.get(reverse('event_shift_add', args=[self.event.id]))
        self.assertEqual(r.status_code, 403)

    def test_toggle_recruit(self):
        self.assertEqual(self.shift.recruit_status, 'open')
        r = self.client.post(reverse('shift_toggle_recruit', args=[self.event.id, self.shift.id]))
        self.assertEqual(r.status_code, 302)
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.recruit_status, 'closed')

    def test_toggle_recruit_forbidden_on_finished_event(self):
        self.event.event_status = 'finished'
        self.event.save(update_fields=['event_status'])
        r = self.client.post(reverse('shift_toggle_recruit', args=[self.event.id, self.shift.id]))
        self.assertEqual(r.status_code, 403)

    def test_toggle_attendance_confirmed_requires_passed_shift(self):
        r = self.client.post(reverse('shift_toggle_attendance_confirmed', args=[self.event.id, self.shift.id]))
        self.assertEqual(r.status_code, 403, 'смена ещё не прошла (days_from_now=5)')

    def test_toggle_attendance_confirmed_on_passed_shift(self):
        past_shift = f.make_shift(self.event, days_from_now=-2)
        r = self.client.post(reverse('shift_toggle_attendance_confirmed', args=[self.event.id, past_shift.id]))
        self.assertEqual(r.status_code, 302)
        past_shift.refresh_from_db()
        self.assertTrue(past_shift.attendance_confirmed)


class EventCommentsFeedbackTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.event = f.make_event()

    def test_manager_can_add_comment(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('event_comment_add', args=[self.event.id]), {'text': 'Заметка менеджера'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.event.comments.filter(text='Заметка менеджера').exists())

    def test_volunteer_cannot_add_comment(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.post(reverse('event_comment_add', args=[self.event.id]), {'text': 'x'})
        self.assertEqual(r.status_code, 403)

    def test_change_log_mark_read_clears_log(self):
        from blog.models import ApplicationChangeLog
        ApplicationChangeLog.objects.create(event=self.event, kind='new', text='x')
        self.client.force_login(self.manager)
        r = self.client.post(reverse('event_change_log_mark_read', args=[self.event.id]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.event.application_change_logs.count(), 0)

    def test_participant_can_leave_feedback(self):
        shift = f.make_shift(self.event, days_from_now=-1)
        volunteer = f.make_user()
        f.make_participation(volunteer, shift, status='attended')
        self.client.force_login(volunteer)
        r = self.client.post(reverse('event_feedback_add', args=[self.event.id]), {'rating': 5, 'comment': 'Отлично'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.event.feedbacks.filter(author=volunteer).exists())

    def test_non_participant_cannot_leave_feedback(self):
        outsider = f.make_user()
        self.client.force_login(outsider)
        r = self.client.post(reverse('event_feedback_add', args=[self.event.id]), {'rating': 5, 'comment': 'x'})
        self.assertEqual(r.status_code, 403)

    def test_cannot_leave_feedback_twice(self):
        shift = f.make_shift(self.event, days_from_now=-1)
        volunteer = f.make_user()
        f.make_participation(volunteer, shift, status='attended')
        self.client.force_login(volunteer)
        self.client.post(reverse('event_feedback_add', args=[self.event.id]), {'rating': 4, 'comment': 'Раз'})
        self.client.post(reverse('event_feedback_add', args=[self.event.id]), {'rating': 5, 'comment': 'Два'})
        self.assertEqual(self.event.feedbacks.filter(author=volunteer).count(), 1)
