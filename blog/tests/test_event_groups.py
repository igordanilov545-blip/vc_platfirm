"""Мероприятие объединяет позиции, сохраняя заявки и решения на уровне смен."""
import importlib
import json
from datetime import timedelta
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import Event, EventGroup, EventStaff, ApplicationShiftDecision
from blog.services.event_groups import event_group_rows
from . import factories as f


class EventGroupTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.group = EventGroup.objects.create(title='Большой фестиваль')
        self.group.managers.add(self.manager)
        self.position = f.make_event(title='Регистрация', event_group=self.group)
        self.shift = f.make_shift(self.position, volunteer_needed=3)

    def summary(self):
        return next(row for row in event_group_rows() if row.pk == self.group.pk)

    def test_list_contains_only_parent_columns_and_names(self):
        response = self.client.get(reverse('event_list'))
        self.assertContains(response, 'Большой фестиваль')
        self.assertNotContains(response, '>Регистрация<')
        from html.parser import HTMLParser

        class Headers(HTMLParser):
            def __init__(self):
                super().__init__()
                self.headers = []
                self.in_header = False

            def handle_starttag(self, tag, attrs):
                self.in_header = tag == 'th' if tag in ('th', 'td') else self.in_header

            def handle_endtag(self, tag):
                if tag == 'th':
                    self.in_header = False

            def handle_data(self, data):
                if self.in_header and data.strip():
                    self.headers.append(data.strip())

        parser = Headers()
        parser.feed(response.content.decode())
        self.assertEqual(parser.headers, ['Название', 'Менеджеры', 'Набор', 'Заявки', 'Добро.ру'])
        self.assertContains(response, 'data-href="' + reverse('event_group_detail', args=[self.group.pk]) + '"')

    def test_drilldown_shows_only_positions_of_selected_event(self):
        other = EventGroup.objects.create(title='Другой фестиваль')
        f.make_event(title='Чужая позиция', event_group=other)
        response = self.client.get(reverse('event_group_detail', args=[self.group.pk]))
        self.assertContains(response, 'Регистрация')
        self.assertNotContains(response, 'Чужая позиция')
        self.assertContains(response, reverse('event_detail', args=[self.position.pk]))
        self.assertContains(response, 'Позиции')

    def test_totals_do_not_multiply_applications_by_number_of_shifts(self):
        second_shift = f.make_shift(self.position, volunteer_needed=7)
        app = f.make_application(self.position, shifts=[self.shift, second_shift], status='approved')
        for shift in (self.shift, second_shift):
            ApplicationShiftDecision.objects.update_or_create(application=app, shift=shift, defaults={'status': 'approved'})
        f.make_application(self.position, shifts=[self.shift], status='new')
        cancelled = f.make_application(self.position, shifts=[self.shift], status='cancelled')
        ApplicationShiftDecision.objects.update_or_create(application=cancelled, shift=self.shift, defaults={'status': 'approved'})
        row = self.summary()
        self.assertEqual((row.needed, row.approved), (10, 2))
        self.assertEqual((row.applications_total, row.applications_processed), (2, 1))

    def test_dobro_tracks_both_directions_deletion_and_reassignment(self):
        self.position.dobro_ru_link_kind = 'unique'
        self.position.dobro_ru_hours_logged = True
        self.position.save()
        self.assertEqual(self.summary().dobro_status, 'logged')
        second = f.make_event(event_group=self.group, dobro_ru_link_kind='unique', dobro_ru_hours_logged=False)
        self.assertEqual(self.summary().dobro_status, 'pending')
        second.dobro_ru_hours_logged = True
        second.save()
        self.assertEqual(self.summary().dobro_status, 'logged')
        second.dobro_ru_hours_logged = False
        second.save()
        self.assertEqual(self.summary().dobro_status, 'pending')
        other = EventGroup.objects.create(title='Другой')
        second.event_group = other
        second.save()
        self.assertEqual(self.summary().dobro_status, 'logged')
        self.position.delete()
        self.assertEqual(self.summary().dobro_status, 'not_required')

    def test_positions_without_dobro_tracking_do_not_block_completion(self):
        self.position.dobro_ru_link_kind = 'unique'
        self.position.dobro_ru_hours_logged = True
        self.position.save()
        f.make_event(event_group=self.group, dobro_ru_link_kind='none')
        self.assertEqual(self.summary().dobro_status, 'logged')

    def test_empty_event_has_zero_counters(self):
        self.position.delete()
        row = self.summary()
        self.assertEqual((row.needed, row.approved, row.applications_total), (0, 0, 0))
        self.assertEqual(row.dobro_status, 'not_required')

    def test_manager_creates_and_edits_parent_using_modal(self):
        response = self.client.post(reverse('event_group_create'), {
            'title': 'Новый фестиваль', 'managers': [self.manager.pk],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        group = EventGroup.objects.get(title='Новый фестиваль')
        self.assertEqual(response.json()['redirect'], reverse('event_group_detail', args=[group.pk]))
        self.assertEqual(list(group.managers.all()), [self.manager])
        self.client.post(reverse('event_group_edit', args=[group.pk]), {
            'title': 'Обновлённый фестиваль', 'managers': [],
        })
        group.refresh_from_db()
        self.assertEqual(group.title, 'Обновлённый фестиваль')
        self.assertFalse(group.managers.exists())

    def test_volunteer_cannot_create_or_edit_parent(self):
        self.client.force_login(f.make_user())
        for url in (reverse('event_group_create'), reverse('event_group_edit', args=[self.group.pk])):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse('event_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('event_group_detail', args=[self.group.pk])).status_code, 200)

    def test_position_creation_keeps_parent_and_existing_shift_flow(self):
        day = (timezone.localdate() + timedelta(days=7)).isoformat()
        response = self.client.post(reverse('event_create'), {
            'title': 'Навигация', 'event_group': self.group.pk,
            'shifts_json': json.dumps([{'day': day, 'start_time': '10:00', 'end_time': '12:00', 'volunteer_needed': 4}]),
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertIn('redirect', response.json())
        position = Event.objects.get(title='Навигация')
        self.assertEqual(position.event_group, self.group)
        self.assertEqual(position.shifts.count(), 1)
        self.assertTrue(EventStaff.objects.filter(event=position, staff_role='team_lead').exists())

    def test_existing_dobro_toggle_updates_parent_without_changing_endpoint(self):
        self.position.event_status = 'finished'
        self.position.dobro_ru_link_kind = 'unique'
        self.position.save()
        url = reverse('event_dobro_toggle', args=[self.position.pk])
        self.client.post(url)
        self.assertEqual(self.summary().dobro_status, 'logged')
        self.client.post(url)
        self.assertEqual(self.summary().dobro_status, 'pending')

    def test_migration_preserves_old_position_shift_and_application_ids(self):
        old_position = f.make_event(title='Старое мероприятие')
        shift = f.make_shift(old_position)
        application = f.make_application(old_position, shifts=[shift])
        EventStaff.objects.create(event=old_position, user=self.manager, staff_role='manager')
        migrate = importlib.import_module('blog.migrations.0039_event_groups_and_positions')
        migrate.assign_existing_positions(apps, SimpleNamespace(connection=connection))
        old_position.refresh_from_db()
        shift.refresh_from_db()
        application.refresh_from_db()
        self.assertIsNotNone(old_position.event_group_id)
        self.assertEqual(shift.event_id, old_position.pk)
        self.assertEqual(application.event_id, old_position.pk)
        self.assertEqual(list(old_position.event_group.managers.all()), [self.manager])
