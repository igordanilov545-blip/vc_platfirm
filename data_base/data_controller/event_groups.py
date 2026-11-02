"""Тонкий доступ к мероприятиям верхнего уровня; позиции остаются в events.py."""
from blog.models import EventGroup
from ._base import logger, actor


def event_groups_qs():
    """Ленивый queryset мероприятий для форм, списков и сводок."""
    return EventGroup.objects.all()


def save_event_group(group, managers, assigned_by=None):
    """Сохранить название мероприятия и выбранных менеджеров без изменения их ролей."""
    group.save()
    group.managers.set(managers)
    logger.info('SAVE event_groups: group=%s managers=%s by=%s', group.pk, [user.pk for user in managers], actor(assigned_by))
    return group
