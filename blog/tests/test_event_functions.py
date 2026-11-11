"""Ручное создание: мероприятие → функции → позиции (решение пользователя 2026-11-11).

Мероприятие состоит из функций (названия из ФиП, общий пул), позиция создаётся
внутри функции; название позиции подсказывается из позиций этой функции и само
попадает в пул.
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import ApplicationShiftDecision, Event, EventCategory, EventDirection, EventGroup, EventShift, EventStaff, PositionTemplate
from . import factories as f


class EventFunctionsTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.group = EventGroup.objects.create(title='Полумарафон')
        self.function = EventCategory.objects.get(name='Организация выдачи пакетов участников')

    def shift(self):
        day = (timezone.localdate() + timedelta(days=10)).isoformat()
        return json.dumps([{'day': day, 'start_time': '10:00', 'end_time': '14:00', 'volunteer_needed': 5}])

    def create_position(self, **extra):
        data = {'event_group': self.group.pk, 'title': 'Хостес зоны выдачи номеров', 'shifts_json': self.shift(), **extra}
        return self.client.post(reverse('event_create'), data)

    def test_page_offers_function_first_and_lists_functions(self):
        page = self.client.get(reverse('event_group_detail', args=[self.group.pk]))
        self.assertContains(page, reverse('event_function_create', args=[self.group.pk]))
        self.assertContains(page, 'Начните с «+ Функция»')
        self.client.post(reverse('event_function_create', args=[self.group.pk]), {'category': self.function.pk})
        self.client.post(reverse('event_function_create', args=[self.group.pk]), {'name': 'Стартовый городок'})
        names = list(EventDirection.objects.filter(event_group=self.group).values_list('name', flat=True))
        self.assertEqual(names, ['Организация выдачи пакетов участников', 'Стартовый городок'])
        self.assertTrue(EventCategory.objects.filter(name='Стартовый городок').exists())
        page = self.client.get(reverse('event_group_detail', args=[self.group.pk]))
        self.assertContains(page, f'?group={self.group.pk}&function={self.function.pk}')

    def test_position_is_created_inside_chosen_function_and_remembered_in_pool(self):
        self.create_position(function=self.function.pk)
        event = self.group.positions.get()
        self.assertEqual(list(event.category_map.values_list('category__name', flat=True)), [self.function.name])
        self.assertTrue(EventDirection.objects.filter(event_group=self.group, name=self.function.name).exists())
        self.assertTrue(PositionTemplate.objects.filter(category=self.function, name='Хостес зоны выдачи номеров').exists())
        form = self.client.get(reverse('event_create') + f'?group={self.group.pk}&function={self.function.pk}')
        self.assertContains(form, f'id="position-pool-{self.function.pk}"')
        self.assertContains(form, 'Функции мероприятия')

    def test_function_is_required_for_new_position_and_new_function_needs_name(self):
        response = self.create_position(function='')
        self.assertFalse(self.group.positions.exists())
        self.assertContains(response, 'Выберите функцию')
        self.create_position(function='new', function_name='')
        self.assertFalse(self.group.positions.exists())
        self.create_position(function='new', function_name='Волонтёры раздевалок')
        self.assertEqual(list(self.group.positions.get().category_map.values_list('category__name', flat=True)),
                         ['Волонтёры раздевалок'])



class ShiftRolesTests(TestCase):
    """Роль человека — колонка таблицы набора смены (2026-11-11), подсказка без ограничений."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.group = EventGroup.objects.create(title='Полумарафон')
        self.function = EventCategory.objects.get(name='Волонтёры старта и финиша')
        PositionTemplate.objects.get_or_create(category=self.function, name='Хостес старта')
        day = (timezone.localdate() + timedelta(days=10)).isoformat()
        shifts = json.dumps([{'day': day, 'start_time': '08:00', 'end_time': '12:00', 'volunteer_needed': 10},
                             {'day': day, 'start_time': '13:00', 'end_time': '16:00', 'volunteer_needed': 5}])
        form = self.client.get(reverse('event_create') + f'?group={self.group.pk}&function={self.function.pk}')
        self.assertContains(form, f'value="{self.function.name}"')  # название = функция
        self.client.post(reverse('event_create'), {'event_group': self.group.pk, 'title': self.function.name,
                                                   'function': self.function.pk, 'shifts_json': shifts})
        self.event = Event.objects.get(event_group=self.group)

    def test_team_leads_enter_every_shift_with_team_lead_role(self):
        decisions = ApplicationShiftDecision.objects.filter(shift__event=self.event)
        self.assertEqual(sorted((d.status, d.role) for d in decisions), [('approved', 'Тим-лидер')] * 2)
        page = self.client.get(reverse('event_detail', args=[self.event.pk]))
        self.assertContains(page, 'Тим-лидер — 1')
        self.assertContains(page, '<option value="Хостес старта">')
        self.assertEqual(decisions.count(), 2)  # повторный просмотр не дублирует

    def test_role_is_free_hint_and_stats_count_it(self):
        volunteer = f.make_user()
        EventStaff.objects.create(event=self.event, user=volunteer, staff_role='team_lead')
        self.client.get(reverse('event_detail', args=[self.event.pk]))
        decision = ApplicationShiftDecision.objects.filter(application__user=volunteer).order_by('shift__start_time').first()
        response = self.client.post(reverse('shift_decision_role', args=[decision.pk]), {'role': '  Хостес   старта '},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['role'], 'Хостес старта')
        page = self.client.get(reverse('event_detail', args=[self.event.pk]))
        self.assertContains(page, 'Хостес старта — 1')
        decision.refresh_from_db()
        self.assertEqual(decision.role, 'Хостес старта')  # ручная роль не перетирается
