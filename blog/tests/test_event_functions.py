"""Мероприятие → функции со сменами; в смене — план ролей (решения пользователя 2026-11-11).

«+ Функция» сразу открывает форму со сменами: функция из пула (названия из ФиП)
или новая, название = функция. В каждой смене можно расписать, сколько людей на
какую роль; без этого — 1 тим-лидер и остальные волонтёры. Роль человека —
колонка таблицы набора смены, выбор только из ролей плана; подсказка без ограничений.
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import ApplicationShiftDecision, Event, EventCategory, EventGroup, EventStaff, PositionTemplate
from blog.services.position_pool import function_tone
from blog.services.shift_roles import normalize_role_plan
from . import factories as f


class RolePlanTests(TestCase):
    def test_empty_plan_is_team_lead_and_volunteers(self):
        self.assertEqual(normalize_role_plan([], 10), [['Тим-лидер', 1], ['Волонтёр', 9]])
        self.assertEqual(normalize_role_plan([], 1), [['Тим-лидер', 1]])

    def test_rest_goes_to_volunteers_and_excess_is_kept(self):
        plan = [['Тим-лидер', 1], ['Хостес', 3], ['хостес', 1], ['', 4], ['Пусто', 0]]
        self.assertEqual(normalize_role_plan(plan, 10), [['Тим-лидер', 1], ['Хостес', 4], ['Волонтёр', 5]])
        self.assertEqual(normalize_role_plan([{'role': 'Хостес', 'count': 12}], 10), [['Хостес', 12]])

    def test_related_functions_share_a_tone(self):
        self.assertEqual(function_tone('Волонтёры старта'), function_tone('Волонтёры финиша'))
        self.assertNotEqual(function_tone('Волонтёры старта'), function_tone('Волонтёры-медики'))


class FunctionCreationTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.group = EventGroup.objects.create(title='Полумарафон', dobro_ru_link='https://dobro.ru/event/1')
        self.function = EventCategory.objects.get(name='Волонтёры старта и финиша')
        self.day = (timezone.localdate() + timedelta(days=10)).isoformat()

    def create(self, shifts, **extra):
        data = {'event_group': self.group.pk, 'function': self.function.pk, 'shifts_json': json.dumps(shifts), **extra}
        return self.client.post(reverse('event_create'), data)

    def shift(self, needed, plan=None, start='08:00'):
        end = '12:00' if start < '12:00' else '18:00'
        return {'day': self.day, 'start_time': start, 'end_time': end, 'volunteer_needed': needed, 'role_plan': plan or []}

    def test_page_has_no_functions_card_and_button_opens_form_with_shifts(self):
        page = self.client.get(reverse('event_group_detail', args=[self.group.pk]))
        self.assertNotContains(page, 'Функции мероприятия')
        self.assertContains(page, reverse('event_create') + f'?group={self.group.pk}')
        form = self.client.get(reverse('event_create') + f'?group={self.group.pk}')
        self.assertContains(form, 'data-role-plan')
        self.assertContains(form, 'type="hidden" name="title"')  # название = функция

    def test_function_title_shift_plans_dobro_and_tone(self):
        self.create([self.shift(10), self.shift(6, [['Тим-лидер', 1], ['Хостес старта', 2]], start='13:00')])
        event = Event.objects.get(event_group=self.group)
        self.assertEqual(event.title, self.function.name)
        self.assertEqual(event.dobro_ru_link, 'https://dobro.ru/event/1')
        plans = [s.role_plan for s in event.shifts.order_by('start_time')]
        self.assertEqual(plans, [[['Тим-лидер', 1], ['Волонтёр', 9]], [['Тим-лидер', 1], ['Хостес старта', 2], ['Волонтёр', 3]]])
        page = self.client.get(reverse('event_group_detail', args=[self.group.pk]))
        self.assertContains(page, f'fn-tone-{function_tone(self.function.name)}')

    def test_new_function_needs_name(self):
        self.create([self.shift(3)], function='new', function_name='')
        self.assertFalse(Event.objects.exists())
        self.create([self.shift(3)], function='new', function_name='Волонтёры раздевалок')
        self.assertEqual(Event.objects.get().title, 'Волонтёры раздевалок')

    def test_shift_edit_keeps_plan(self):
        self.create([self.shift(4, [['Хостес старта', 2]])])
        event = Event.objects.get()
        shift = event.shifts.get()
        form = self.client.get(reverse('event_shift_edit', args=[event.pk, shift.pk]))
        self.assertContains(form, 'Хостес старта')
        self.client.post(reverse('event_shift_edit', args=[event.pk, shift.pk]), {
            'day': self.day, 'start_time': '08:00', 'end_time': '12:00', 'volunteer_needed': 5, 'recruit_status': 'open',
            'role_plan': json.dumps([['Хостес старта', 3]])})
        shift.refresh_from_db()
        self.assertEqual(shift.role_plan, [['Хостес старта', 3], ['Волонтёр', 2]])


class ShiftRolesTests(TestCase):
    """Роль человека — колонка таблицы набора смены, только роли из плана смен."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.group = EventGroup.objects.create(title='Полумарафон')
        self.function = EventCategory.objects.get(name='Волонтёры старта и финиша')
        PositionTemplate.objects.get_or_create(category=self.function, name='Ассистент магазина')
        day = (timezone.localdate() + timedelta(days=10)).isoformat()
        shifts = [{'day': day, 'start_time': '08:00', 'end_time': '12:00', 'volunteer_needed': 10,
                   'role_plan': [['Тим-лидер', 1], ['Хостес старта', 2]]},
                  {'day': day, 'start_time': '13:00', 'end_time': '16:00', 'volunteer_needed': 5}]
        self.client.post(reverse('event_create'), {'event_group': self.group.pk, 'function': self.function.pk,
                                                   'shifts_json': json.dumps(shifts)})
        self.event = Event.objects.get(event_group=self.group)

    def test_team_leads_enter_every_shift_with_team_lead_role(self):
        decisions = ApplicationShiftDecision.objects.filter(shift__event=self.event)
        self.assertEqual(sorted((d.status, d.role) for d in decisions), [('approved', 'Тим-лидер')] * 2)
        page = self.client.get(reverse('event_detail', args=[self.event.pk]))
        self.assertContains(page, 'Тим-лидер 1/1')
        self.assertContains(page, 'Хостес старта 0/2')
        self.assertContains(page, '<option value="Хостес старта">')
        self.assertNotContains(page, 'Ассистент магазина')  # только роли плана, не весь пул
        self.assertEqual(decisions.count(), 2)

    def test_role_is_saved_and_counted(self):
        volunteer = f.make_user()
        EventStaff.objects.create(event=self.event, user=volunteer, staff_role='team_lead')
        self.client.get(reverse('event_detail', args=[self.event.pk]))
        decision = ApplicationShiftDecision.objects.filter(application__user=volunteer).order_by('shift__start_time').first()
        response = self.client.post(reverse('shift_decision_role', args=[decision.pk]), {'role': 'Хостес старта'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['role'], 'Хостес старта')
        page = self.client.get(reverse('event_detail', args=[self.event.pk]))
        self.assertContains(page, 'Хостес старта 1/2')
