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

from blog.models import Event, EventCategory, EventDirection, EventGroup, EventShift, FunctionShift, PositionTemplate
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
        direction = EventDirection.objects.get(event_group=self.group, name=self.function.name)
        self.assertContains(page, reverse('function_shift_create', args=[direction.pk]))

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


class FunctionShiftMatrixTests(TestCase):
    """Смена функции = период + сколько нужно; роли смены — позиции функции (2026-11-11)."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.group = EventGroup.objects.create(title='Полумарафон', dobro_ru_link='https://dobro.ru/event/1')
        self.function = EventCategory.objects.get(name='Волонтёры старта и финиша')
        self.client.post(reverse('event_function_create', args=[self.group.pk]), {'category': self.function.pk})
        self.direction = EventDirection.objects.get(event_group=self.group)
        self.day = (timezone.localdate() + timedelta(days=10)).isoformat()

    def add_shift(self, needed=10, zone='Старт', start='08:00'):
        return self.client.post(reverse('function_shift_create', args=[self.direction.pk]),
                                {'day': self.day, 'start_time': start, 'end_time': '12:00', 'volunteer_needed': needed, 'zone': zone})

    def cells(self, shift):
        return {s.event.title: s.volunteer_needed for s in EventShift.objects.filter(function_shift=shift).select_related('event')}

    def test_new_shift_gets_team_lead_and_volunteers_from_pool_once(self):
        self.add_shift(10)
        shift = FunctionShift.objects.get()
        self.assertEqual(self.cells(shift), {'Тим-лидер зоны Старт': 1, 'Волонтёр зоны Старт': 9})
        self.add_shift(4, start='13:00')
        self.assertEqual(Event.objects.filter(event_group=self.group).count(), 2)  # роли не дублируются
        self.assertEqual(PositionTemplate.objects.filter(category=self.function, name__endswith='зоны Старт').count(), 2)
        role = Event.objects.get(title='Волонтёр зоны Старт')
        self.assertEqual(list(role.category_map.values_list('category__name', flat=True)), [self.function.name])
        self.assertEqual(role.dobro_ru_link, 'https://dobro.ru/event/1')

    def test_edit_shift_counts_and_mismatch_warning(self):
        self.add_shift(10)
        shift = FunctionShift.objects.get()
        self.client.post(reverse('function_role_create', args=[self.direction.pk]), {'title': 'Хостес старта'})
        roles = {e.title: e.pk for e in Event.objects.filter(event_group=self.group)}
        form = self.client.get(reverse('function_shift_edit', args=[shift.pk]))
        self.assertContains(form, 'data-role-count')
        self.client.post(reverse('function_shift_edit', args=[shift.pk]), {
            'day': self.day, 'start_time': '09:00', 'end_time': '12:00', 'volunteer_needed': 10,
            f'role_{roles["Тим-лидер зоны Старт"]}': 1, f'role_{roles["Волонтёр зоны Старт"]}': 6, f'role_{roles["Хостес старта"]}': 2})
        self.assertEqual(self.cells(shift), {'Тим-лидер зоны Старт': 1, 'Волонтёр зоны Старт': 6, 'Хостес старта': 2})
        self.assertEqual(EventShift.objects.filter(function_shift=shift).values_list('start_time__hour', flat=True).distinct().count(), 1)
        page = self.client.get(reverse('event_group_detail', args=[self.group.pk]))
        self.assertContains(page, 'Сумма по ролям (9) не равна заявленному на смену (10)')

    def test_role_suggestions_only_from_this_function(self):
        other = EventCategory.objects.get(name='Волонтёры дистанции')
        PositionTemplate.objects.get_or_create(category=other, name='Волонтёр пункта питания')
        PositionTemplate.objects.get_or_create(category=self.function, name='Хостес старта')
        form = self.client.get(reverse('function_role_create', args=[self.direction.pk]))
        self.assertContains(form, 'Хостес старта')
        self.assertNotContains(form, 'Волонтёр пункта питания')

    def test_group_dobro_link_goes_to_positions_and_position_form_drops_fields(self):
        event = Event.objects.create(title='Старая', event_group=self.group)
        self.client.post(reverse('event_group_edit', args=[self.group.pk]),
                         {'title': self.group.title, 'dobro_ru_link': 'https://dobro.ru/event/2', 'managers': [self.manager.pk]})
        event.refresh_from_db()
        self.assertEqual((event.dobro_ru_link, event.dobro_ru_link_kind), ('https://dobro.ru/event/2', 'unique'))
        form = self.client.get(reverse('event_create') + f'?group={self.group.pk}')
        for label in ('Масштаб позиции', 'Организация:<', 'Контактное лицо', 'Ссылка на пост в канале', 'Ссылка на Добро.ру'):
            self.assertNotContains(form, label)
