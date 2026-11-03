"""Выдача в позиции: обед на смену, один жетон на все смены мероприятия."""
import json
from django.test import TestCase
from django.urls import reverse
from blog.models import EventGroup, ShiftMeal, EventBadge
from . import factories as f


class PositionHandoutTests(TestCase):
    def setUp(self):
        self.manager, self.user = f.make_manager(), f.make_user()
        self.group = EventGroup.objects.create(title='Выдача')
        self.event = f.make_event(event_group=self.group)
        self.shifts = [f.make_shift(self.event, days_from_now=i + 2) for i in range(2)]
        f.make_application(self.event, self.user, status='approved', shifts=self.shifts)
        self.parts = [f.make_participation(self.user, shift, status='pending', hours=0) for shift in self.shifts]
        self.client.force_login(self.manager)

    def mark(self, kind, checked=True, part=0):
        return self.client.post(reverse('participation_handout', args=[self.parts[part].pk]),
                                {'kind': kind, 'checked': json.dumps(checked)})

    def test_lunch_is_per_shift_badge_shared_across_positions(self):
        self.assertEqual(self.mark('lunch').status_code, 200)
        self.assertEqual(self.mark('badge').status_code, 200)
        self.assertEqual(self.mark('badge', part=1).status_code, 200)
        self.assertEqual(ShiftMeal.objects.count(), 1)
        self.assertEqual(EventBadge.objects.count(), 1)
        response = self.client.get(reverse('event_detail', args=[self.event.pk]))
        self.assertContains(response, 'data-handout-kind="lunch"', count=2)
        self.assertContains(response, 'data-handout-kind="badge"', count=2)
        rows = [row for entry in response.context['shifts_with_recruitment'] for row in entry['rows']]
        self.assertEqual(sum(row['meal'] for row in rows), 1)
        self.assertTrue(all(row['badge'] for row in rows))
        self.assertEqual(self.mark('badge', False, part=1).status_code, 200)
        self.assertFalse(EventBadge.objects.exists())
        self.assertEqual(self.mark('lunch', False).status_code, 200)
        self.assertFalse(ShiftMeal.objects.exists())

    def test_team_leader_can_change_own_position_only(self):
        leader = f.make_team_leader()
        self.client.force_login(leader)
        self.assertEqual(self.mark('lunch').status_code, 403)
        f.assign_team_leader(self.event, leader)
        self.assertEqual(self.mark('lunch').status_code, 200)
        self.client.force_login(self.user)
        self.assertEqual(self.mark('badge').status_code, 403)
        self.client.logout()
        self.assertEqual(self.mark('badge').status_code, 302)

    def test_finished_invalid_input_and_get_do_not_issue(self):
        for kind, checked in [('wrong', True), ('lunch', 'false')]:
            self.assertEqual(self.mark(kind, checked).status_code, 400)
        url = reverse('participation_handout', args=[self.parts[0].pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.event.event_status = 'finished'
        self.event.save(update_fields=['event_status'])
        self.assertEqual(self.mark('lunch').status_code, 403)
        self.assertFalse(ShiftMeal.objects.exists())
        self.assertFalse(EventBadge.objects.exists())
