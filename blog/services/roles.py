"""Резолвинг ролей и контекстных прав тим-лидера (access-control.md)."""
from django.db.models import Q

from blog.models import Application, EventStaff, Participation, User


def is_manager(user: User) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.manager_roles.filter(revoked_at__isnull=True).exists()


def is_team_leader(user: User) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.team_leader_roles.filter(revoked_at__isnull=True).exists()


def is_team_leader_of_event(user: User, event_id: int) -> bool:
    """Является ли user активным тим-лидером конкретного мероприятия."""
    if not user or not user.is_authenticated:
        return False
    return EventStaff.objects.filter(
        event_id=event_id, user=user, staff_role='team_lead'
    ).exists()


def can_process_applications(user: User, event_id: int) -> bool:
    """Менеджер — на всех меро; тим-лидер — только на своих (правило 3 db.md)."""
    return is_manager(user) or is_team_leader_of_event(user, event_id)


def can_manage_event(user: User) -> bool:
    """CRUD мероприятий, назначение персонала — только менеджер."""
    return is_manager(user)


def has_extended_access_to_profile(viewer: User, target: User) -> bool:
    """Расширенный + внутренний профиль чужого волонтёра (access-control.md, правило 5):

    владелец или менеджер — всегда; тим-лидер — только пока одновременно:
    - он team_lead на мероприятии, и
    - мероприятие ещё не завершено (event_status != 'finished'), и
    - целевой волонтёр подал заявку на это меро ИЛИ участвует в нём.
    """
    if not viewer or not viewer.is_authenticated:
        return False
    if viewer.id == target.id or is_manager(viewer):
        return True
    if not is_team_leader(viewer):
        return False

    tl_event_ids = EventStaff.objects.filter(
        user=viewer, staff_role='team_lead'
    ).exclude(event__event_status='finished').values_list('event_id', flat=True)

    if not tl_event_ids:
        return False

    has_application = Application.objects.filter(
        user=target, event_id__in=tl_event_ids
    ).exists()
    has_participation = Participation.objects.filter(
        user=target, event_day__event_id__in=tl_event_ids
    ).exists()

    return has_application or has_participation


def role_label(user: User) -> str:
    if is_manager(user):
        return 'Менеджер'
    if is_team_leader(user):
        return 'Тим-лидер'
    return 'Волонтёр'
