"""Доступ к данным: требования мероприятий, их привязка к меро и исключения по юзерам.

Инвариант (ToDo/db.md): изначально все пользователи соответствуют всем требованиям;
несоответствие — это явная запись `UserRequirementException`.
"""
from typing import Optional, List

from blog.models import (
    EventRequirement, EventRequirementMap, UserRequirementException, Event, User,
)


def create_requirement(title: str, description: Optional[str] = None) -> EventRequirement:
    return EventRequirement.objects.create(title=title, description=description)


def add_requirement_to_event(event: Event, requirement: EventRequirement) -> EventRequirementMap:
    return EventRequirementMap.objects.create(event=event, requirement=requirement)


def create_user_exception(user: User, requirement: EventRequirement, reason: Optional[str] = None) -> UserRequirementException:
    return UserRequirementException.objects.create(user=user, requirement=requirement, reason=reason)


def get_requirements(title_filter: Optional[str] = None) -> List[EventRequirement]:
    qs = EventRequirement.objects.all()
    if title_filter:
        qs = qs.filter(title__icontains=title_filter)
    return list(qs)


def get_event_requirements_map(event_id: Optional[int] = None) -> List[EventRequirementMap]:
    qs = EventRequirementMap.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)


def user_has_requirement_exception(user: User, requirement: EventRequirement) -> bool:
    """Отмечен ли пользователь как несоответствующий требованию (валидация формы)."""
    return UserRequirementException.objects.filter(user=user, requirement=requirement).exists()


def get_user_exceptions(user_id: Optional[int] = None) -> List[UserRequirementException]:
    qs = UserRequirementException.objects.all()
    if user_id:
        qs = qs.filter(user_id=user_id)
    return list(qs)
