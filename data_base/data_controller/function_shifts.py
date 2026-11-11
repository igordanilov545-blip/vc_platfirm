"""CRUD матрицы «смена функции × роль» (ручное создание мероприятия, 2026-11-11).

Смена функции — FunctionShift; клетка матрицы — EventShift позиции-роли с
function_shift. Ссылка Добро.ру мероприятия копируется в его позиции.
"""
from blog.models import Event, EventGroup, EventShift, FunctionShift
from ._base import logger, actor


def function_shifts_qs():
    return FunctionShift.objects.all()


def create_function_shift(direction, day, start_time, end_time, volunteer_needed, zone='', operator=None):
    obj = FunctionShift.objects.create(direction=direction, day=day, start_time=start_time, end_time=end_time,
                                       volunteer_needed=volunteer_needed, zone=zone[:255])
    logger.info('INSERT function_shifts: shift=%s direction=%s by=%s', obj.pk, direction.pk, actor(operator))
    return obj


def save_function_shift(shift, operator=None):
    """Сохранить смену функции и перенести её дату/время во все клетки-роли."""
    shift.save()
    EventShift.objects.filter(function_shift=shift).update(day=shift.day, start_time=shift.start_time, end_time=shift.end_time)
    logger.info('UPDATE function_shifts: shift=%s by=%s', shift.pk, actor(operator))
    return shift


def delete_function_shift(shift, operator=None):
    logger.info('DELETE function_shifts: shift=%s by=%s', shift.pk, actor(operator))
    shift.delete()


def create_role_position(group, title, operator=None):
    """Позиция-роль внутри мероприятия (Добро.ру — ссылка мероприятия)."""
    link = group.dobro_ru_link or None
    obj = Event.objects.create(event_group=group, title=title[:255], dobro_ru_link=link,
                               dobro_ru_link_kind='unique' if link else 'none')
    logger.info('INSERT events role: event=%s group=%s by=%s', obj.pk, group.pk, actor(operator))
    return obj


def role_shift(function_shift, event):
    return EventShift.objects.filter(function_shift=function_shift, event=event).first()


def save_role_shift(function_shift, event, volunteer_needed, operator=None):
    """Клетка матрицы: создать/обновить смену роли; 0 — убрать (если по ней ещё
    никого нет, иначе оставить с нулём, чтобы не потерять заявки и участия)."""
    shift = role_shift(function_shift, event)
    if volunteer_needed <= 0:
        if shift is None:
            return None
        if shift.application_decisions.exists() or shift.participations.exists():
            shift.volunteer_needed = 0
            shift.save(update_fields=['volunteer_needed'])
            return shift
        logger.info('DELETE event_shifts role: shift=%s by=%s', shift.pk, actor(operator))
        shift.delete()
        return None
    if shift is None:
        shift = EventShift.objects.create(event=event, function_shift=function_shift, day=function_shift.day,
                                          start_time=function_shift.start_time, end_time=function_shift.end_time,
                                          volunteer_needed=volunteer_needed)
        logger.info('INSERT event_shifts role: shift=%s event=%s by=%s', shift.pk, event.pk, actor(operator))
    elif shift.volunteer_needed != volunteer_needed:
        shift.volunteer_needed = volunteer_needed
        shift.save(update_fields=['volunteer_needed'])
    return shift


def apply_group_dobro_link(group: EventGroup, operator=None):
    """Ссылка Добро.ру мероприятия — во все его позиции (каждая смена учитывается по ней)."""
    if not group.dobro_ru_link:
        return 0
    count = Event.objects.filter(event_group=group).update(dobro_ru_link=group.dobro_ru_link, dobro_ru_link_kind='unique',
                                                         dobro_ru_shared_link=None)
    logger.info('UPDATE events dobro from group: group=%s events=%s by=%s', group.pk, count, actor(operator))
    return count
