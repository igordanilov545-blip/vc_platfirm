"""Функции мероприятия при ручном создании: мероприятие → функции → позиции.

Решение пользователя 2026-11-11: функция — блок вроде «Организация выдачи пакетов
участников» (названия из ФиП, общий пул EventCategory), позиции создаются внутри
функции. Список функций мероприятия хранится в event_directions (те же записи
создаёт импорт ФиП), функция позиции — её связь с функцией пула.
"""
from collections import OrderedDict

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
        sections.setdefault(key, {'name': direction.name, 'category': pool.get(key), 'positions': []})
    loose = []
    for event in events:
        category = links.get(event.pk)
        event.function = category
        if category is None:
            loose.append(event)
            continue
        key = _key(category.name)
        sections.setdefault(key, {'name': category.name, 'category': category, 'positions': []})['positions'].append(event)
    return {'sections': list(sections.values()), 'without_function': loose}


def remember_position(event, category, operator=None):
    """Название позиции — в пул её функции (подсказка для следующих мероприятий)."""
    if category is not None and event.title:
        dc.ensure_position_template(category, event.title.split(' · ')[0], operator)
