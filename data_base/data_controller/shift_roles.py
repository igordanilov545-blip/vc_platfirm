"""Роли в сменах и ссылка Добро.ру мероприятия (2026-11-11)."""
from blog.models import Event, EventGroup
from ._base import logger, actor


def set_decision_role(decision, role, operator=None):
    """Роль человека в смене (подсказка планирования, без ограничений)."""
    role = ' '.join((role or '').split())[:255]
    if decision.role != role:
        decision.role = role
        decision.save(update_fields=['role'])
        logger.info('UPDATE application_shift_decisions role: decision=%s role=%r by=%s', decision.pk, role, actor(operator))
    return decision


def apply_group_dobro_link(group: EventGroup, operator=None):
    """Ссылка Добро.ру мероприятия — во все его позиции (каждая смена учитывается по ней)."""
    if not group.dobro_ru_link:
        return 0
    count = Event.objects.filter(event_group=group).update(dobro_ru_link=group.dobro_ru_link, dobro_ru_link_kind='unique',
                                                         dobro_ru_shared_link=None)
    logger.info('UPDATE events dobro from group: group=%s events=%s by=%s', group.pk, count, actor(operator))
    return count
