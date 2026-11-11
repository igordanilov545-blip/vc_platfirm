"""Функции мероприятия при ручном создании: мероприятие → функции → позиции.

Решение пользователя 2026-11-11: функция — блок вроде «Организация выдачи пакетов
участников» (названия из ФиП, общий пул EventCategory), позиции создаются внутри
функции. Список функций мероприятия хранится в event_directions (те же записи
создаёт импорт ФиП), функция позиции — её связь с функцией пула.
"""
from collections import OrderedDict
from datetime import datetime

from django.utils import timezone

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from data_base import data_controller as dc
from blog.services.position_pool import _key, function_category
from blog.services.roles import has_manager_access


def _manager(operator):
    if not has_manager_access(operator):
        raise PermissionDenied('Функциями мероприятия управляет менеджер.')


@transaction.atomic
def add_function(operator, group, category=None, name=''):
    """Добавить функцию в мероприятие: из пула или новую (она попадает в пул)."""
    _manager(operator)
    if category is None:
        if not (name or '').strip():
            raise ValidationError('Выберите функцию из списка или впишите название новой.')
        category = function_category(name, operator)
    existing = next((d for d in dc.event_directions_qs().filter(event_group=group) if _key(d.name) == _key(category.name)), None)
    return existing or dc.create_event_function(group, category.name, operator)


def functions_overview(group, events=None):
    """Функции мероприятия по порядку и их позиции; позиции без функции — отдельно."""
    events = list(events if events is not None else dc.events_qs().filter(event_group=group))
    links = {}
    for link in dc.event_category_maps_qs().filter(event__event_group=group).select_related('category').order_by('pk'):
        links.setdefault(link.event_id, link.category)
    pool = {_key(c.name): c for c in dc.event_categories_qs()}
    sections = OrderedDict()
    for direction in dc.event_directions_qs().filter(event_group=group).order_by('sort_order', 'pk'):
        key = _key(direction.name)
        sections.setdefault(key, {'name': direction.name, 'category': pool.get(key), 'positions': [], 'direction': direction})
    loose = []
    for event in events:
        category = links.get(event.pk)
        event.function = category
        if category is None:
            loose.append(event)
            continue
        key = _key(category.name)
        sections.setdefault(key, {'name': category.name, 'category': category, 'positions': [], 'direction': None})['positions'].append(event)
    for section in sections.values():
        section['matrix'] = shift_matrix(section['direction'], section['positions']) if section['direction'] else None
    return {'sections': list(sections.values()), 'without_function': loose}


def remember_position(event, category, operator=None):
    """Название позиции — в пул её функции (подсказка для следующих мероприятий)."""
    if category is not None and event.title:
        dc.ensure_position_template(category, event.title.split(' · ')[0], operator)


# --- Смены функции: матрица «смена × роль» (2026-11-11) -----------------------
# Смена — период, когда нужны люди, и сколько всего; позиция — роль человека в
# смене. При создании смены роли «Тим-лидер зоны X» (1) и «Волонтёр зоны X»
# (нужно − 1) берутся из пула функции (или попадают туда один раз).

def role_titles(zone):
    zone = (zone or '').strip()
    return f'Тим-лидер зоны {zone}', f'Волонтёр зоны {zone}'


def _aware(day, moment):
    return timezone.make_aware(datetime.combine(day, moment), timezone.get_current_timezone())


def function_of(direction):
    return function_category(direction.name)


def function_roles(direction):
    """Позиции-роли функции в мероприятии (по связи с функцией пула)."""
    category = function_of(direction)
    links = dc.event_category_maps_qs().filter(event__event_group=direction.event_group, category=category)
    return sorted({link.event for link in links.select_related('event')}, key=lambda e: e.pk)


@transaction.atomic
def ensure_role(operator, direction, title):
    """Роль функции по названию: существующая позиция мероприятия или новая; название — в пул."""
    _manager(operator)
    title = ' '.join((title or '').split())
    if not title:
        raise ValidationError('Впишите название роли.')
    category = function_of(direction)
    found = next((e for e in function_roles(direction) if _key(e.title) == _key(title)), None)
    if found is None:
        found = dc.create_role_position(direction.event_group, title, operator)
        dc.sync_event_categories(found, [category])
        dc.add_event_staff(found, operator, 'manager')
    remember_position(found, category, operator)
    return found


@transaction.atomic
def add_shift(operator, direction, day, start, end, needed, zone=''):
    """Новая смена функции: сразу тим-лидер (1) и волонтёры (нужно − 1)."""
    _manager(operator)
    if end <= start:
        raise ValidationError('Время окончания должно быть позже времени начала.')
    zone = (zone or '').strip() or direction.name
    shift = dc.create_function_shift(direction, day, _aware(day, start), _aware(day, end), needed, zone, operator)
    leader_title, volunteer_title = role_titles(zone)
    dc.save_role_shift(shift, ensure_role(operator, direction, leader_title), 1, operator)
    dc.save_role_shift(shift, ensure_role(operator, direction, volunteer_title), max(needed - 1, 0), operator)
    return shift


@transaction.atomic
def update_shift(operator, shift, day, start, end, needed, counts):
    """Изменить смену функции и клетки ролей: counts = {event_id: сколько нужно}."""
    _manager(operator)
    if end <= start:
        raise ValidationError('Время окончания должно быть позже времени начала.')
    shift.day, shift.start_time, shift.end_time, shift.volunteer_needed = day, _aware(day, start), _aware(day, end), needed
    dc.save_function_shift(shift, operator)
    roles = {event.pk: event for event in function_roles(shift.direction)}
    for event_id, count in counts.items():
        if event_id in roles:
            dc.save_role_shift(shift, roles[event_id], max(int(count or 0), 0), operator)
    return shift


@transaction.atomic
def delete_shift(operator, shift):
    """Удалить смену функции вместе с пустыми клетками (клетки с заявками остаются)."""
    _manager(operator)
    for role_shift in list(shift.role_shifts.all()):
        dc.save_role_shift(shift, role_shift.event, 0, operator)
    dc.delete_function_shift(shift, operator)


def shift_counts(shift):
    return {s.event_id: s.volunteer_needed for s in shift.role_shifts.all()}


def shift_matrix(direction, roles=None):
    """Строки — роли, колонки — смены функции; итог по ролям против заявленного."""
    shifts = list(dc.function_shifts_qs().filter(direction=direction).prefetch_related('role_shifts'))
    roles = list(roles) if roles is not None else function_roles(direction)
    cells = {(s.function_shift_id, s.event_id): s.volunteer_needed for shift in shifts for s in shift.role_shifts.all()}
    columns = []
    for shift in shifts:
        assigned = sum(cells.get((shift.pk, role.pk), 0) for role in roles)
        columns.append({'shift': shift, 'assigned': assigned, 'needed': shift.volunteer_needed,
                        'mismatch': assigned != shift.volunteer_needed})
    rows = [{'role': role, 'cells': [cells.get((shift.pk, role.pk)) for shift in shifts]} for role in roles]
    return {'columns': columns, 'rows': rows, 'warnings': sum(1 for c in columns if c['mismatch'])}


def role_pool(direction):
    """Подсказки названий ролей — только из пула этой функции."""
    category = function_of(direction)
    return [t.name for t in dc.position_templates_qs().filter(category=category).order_by('name')]
