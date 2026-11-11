"""Доступ к данным: мероприятия, смены, категории, staff, публикация и рассылка.

Доменный инвариант (coding-principles §6): набор (`recruit_status`, `volunteer_needed`)
живёт на СМЕНЕ (`EventShift`), а не на мероприятии. Здесь только тонкий CRUD —
вычисление статусов/наборов делают модели (`Event.compute_status`) и сервисы.
"""
from typing import Optional, List

from django.utils import timezone

from blog.models import (
    Location, Organization, Organizer, OrganizerOrganizationLink,
    EventCategory, EventRequirement, EventRequirementMap, Event,
    EventCategoryMap, EventPerk, EventPerkMap, EventShift, EventStaff,
    TeamLeader, Manager, User, DobroRuSharedLink,
)
from ._base import logger


def create_event_category(name: str, kind: str = 'category') -> EventCategory:
    obj = EventCategory.objects.create(name=name, kind=kind)
    logger.info('INSERT event_categories: id=%s kind=%s name=%r', obj.pk, kind, name)
    return obj


def set_function_default_categories(function: EventCategory, categories) -> None:
    """Категории, которые функция проставляет позиции при выборе (настройки пула)."""
    function.default_categories.set([c for c in categories if c is not None])
    logger.info('UPDATE event_categories defaults: function=%s categories=%s', function.pk, [c.pk for c in categories if c])


def create_event_perk(name: str) -> EventPerk:
    return EventPerk.objects.create(name=name)


def create_event(
    title: str,
    location: Optional[Location] = None,
    organization: Optional[Organization] = None,
    organizer: Optional[Organizer] = None,
    description: Optional[str] = None,
    chat_link: Optional[str] = None,
    post_in_chanel_link: Optional[str] = None,
    event_status: str = 'upcoming',
    people_helped: int = 0,
    dobro_ru_link_kind: str = 'none',
    dobro_ru_link: Optional[str] = None,
    dobro_ru_shared_link: Optional[DobroRuSharedLink] = None,
) -> Event:
    return Event.objects.create(
        title=title,
        location=location,
        organization=organization,
        organizer=organizer,
        description=description,
        chat_link=chat_link,
        post_in_chanel_link=post_in_chanel_link,
        event_status=event_status,
        people_helped=people_helped,
        dobro_ru_link_kind=dobro_ru_link_kind,
        dobro_ru_link=dobro_ru_link,
        dobro_ru_shared_link=dobro_ru_shared_link,
    )


def create_dobro_ru_shared_link(
    title: str,
    url: str,
    link_type: str,
    period_hint: Optional[str] = None,
    is_active: bool = True,
) -> DobroRuSharedLink:
    return DobroRuSharedLink.objects.create(
        title=title, url=url, link_type=link_type, period_hint=period_hint, is_active=is_active,
    )


def add_category_to_event(event: Event, category: EventCategory) -> EventCategoryMap:
    return EventCategoryMap.objects.create(event=event, category=category)


def add_perk_to_event(event: Event, perk: EventPerk) -> EventPerkMap:
    return EventPerkMap.objects.create(event=event, perk=perk)


def create_event_shift(
    event: Event,
    day: str,
    start_time: str,
    end_time: str,
    volunteer_needed: int = 0,
    location: Optional[Location] = None
) -> EventShift:
    return EventShift.objects.create(
        event=event,
        day=day,
        start_time=start_time,
        end_time=end_time,
        volunteer_needed=volunteer_needed,
        location=location
    )


def assign_staff_to_event(event: Event, user: User, role: str) -> EventStaff:
    return EventStaff.objects.create(event=event, user=user, staff_role=role)


def get_event_categories(name_filter: Optional[str] = None) -> List[EventCategory]:
    qs = EventCategory.objects.all()
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    return list(qs)


def get_event_perks(name_filter: Optional[str] = None) -> List[EventPerk]:
    qs = EventPerk.objects.all()
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    return list(qs)


def get_events(title_filter: Optional[str] = None) -> List[Event]:
    qs = Event.objects.all()
    if title_filter:
        qs = qs.filter(title__icontains=title_filter)
    return list(qs)


def get_open_events(limit: Optional[int] = None) -> List[Event]:
    """Опубликованные меро хотя бы с одной сменой с открытым набором (tg-bot.md §4.1)."""
    qs = (
        Event.objects.filter(
            shifts__recruit_status='open',
            event_status__in=['upcoming', 'ongoing'],
            published_at__isnull=False,
        )
        .select_related('location')
        .prefetch_related('shifts')
        .distinct()
        .order_by('created_at')
    )
    return list(qs[:limit]) if limit else list(qs)


def get_unpublished_events() -> List[Event]:
    """Мероприятия, сформированные на сайте, но ещё не опубликованные (bot-update.md
    §2.4.C) — `published_at IS NULL`, не завершённые."""
    return list(
        Event.objects.filter(published_at__isnull=True)
        .exclude(event_status='finished')
        .order_by('created_at')
    )


def publish_event(event: Event) -> Event:
    """Публикует мероприятие: проставляет `published_at` (тонкая обёртка, зеркалит
    `blog.views.event_publish` — бизнес-проверки делает вызывающий сервис)."""
    event.published_at = timezone.now()
    event.save(update_fields=['published_at'])
    logger.info('UPDATE events: event=%s published_at=%s', event.id, event.published_at)
    return event


def get_broadcastable_events() -> List[Event]:
    """Опубликованные, ещё не завершённые мероприятия — кандидаты для рассылки
    (bot-update.md §2.4.D)."""
    return list(
        Event.objects.filter(published_at__isnull=False)
        .exclude(event_status='finished')
        .order_by('created_at')
    )


def mark_event_broadcast_sent(event: Event) -> Event:
    """Проставляет `broadcast_sent_at` при ПЕРВОЙ рассылке по мероприятию (повторные
    рассылки это поле не трогают — вызывающий сервис проверяет `was_sent_before`)."""
    event.broadcast_sent_at = timezone.now()
    event.save(update_fields=['broadcast_sent_at'])
    return event


def get_active_events() -> List[Event]:
    """Не завершённые меро (для карточек с контактами организатора у менеджера)."""
    return list(
        Event.objects.filter(event_status__in=['upcoming', 'ongoing'])
        .select_related('location', 'organization', 'organizer')
    )


def get_event_categories_map(event_id: Optional[int] = None) -> List[EventCategoryMap]:
    qs = EventCategoryMap.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)


def get_event_perks_map(event_id: Optional[int] = None) -> List[EventPerkMap]:
    qs = EventPerkMap.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)


def get_event_shifts(event_id: Optional[int] = None) -> List[EventShift]:
    qs = EventShift.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)


def get_event_staff(event_id: Optional[int] = None, user_id: Optional[int] = None) -> List[EventStaff]:
    qs = EventStaff.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    if user_id:
        qs = qs.filter(user_id=user_id)
    return list(qs)


def get_event_by_id(event_id: int) -> Optional[Event]:
    return Event.objects.filter(pk=event_id).first()


# --- Ленивые queryset'ы для полей форм мероприятия (см. blog/forms/events.py) ---
def active_team_leader_users_qs():
    """Пользователи с активной ролью тим-лидера (team_leaders, revoked_at IS NULL),
    по id из TeamLeader напрямую (LEFT JOIN дал бы ложные NULL-совпадения)."""
    return User.objects.filter(
        id__in=TeamLeader.objects.filter(revoked_at__isnull=True).values('user_id')
    ).order_by('last_name', 'first_name')


def active_manager_users_qs():
    """Пользователи с активной ролью менеджера (managers, revoked_at IS NULL)."""
    return User.objects.filter(
        id__in=Manager.objects.filter(revoked_at__isnull=True).values('user_id')
    ).order_by('last_name', 'first_name')


def events_open_for_application_qs():
    """Опубликованные меро с хотя бы одной будущей сменой, не завершённые вручную —
    пул для поля выбора меро в форме подачи заявки (см. ApplicationForm)."""
    now = timezone.now()
    return (
        Event.objects.filter(published_at__isnull=False, shifts__start_time__gt=now)
        .exclude(event_status='finished')
        .distinct().order_by('-created_at')
    )


def events_with_open_shifts():
    """Меро, у которых есть хотя бы одна смена с открытым набором — для ленивого
    закрытия набора по прошедшим меро в форме подачи заявки."""
    return list(Event.objects.filter(shifts__recruit_status='open').distinct())


def event_categories_for_event(event) -> List[EventCategory]:
    """Категории (kind=category), привязанные к меро — initial чипов формы."""
    return list(EventCategory.objects.filter(event_map__event=event, kind='category'))


def event_perks_for_event(event) -> List[EventPerk]:
    """Плюшки, привязанные к меро (для initial чипов формы редактирования)."""
    return list(EventPerk.objects.filter(event_map__event=event))


def event_requirements_for_event(event) -> List[EventRequirement]:
    return list(EventRequirement.objects.filter(event_map__event=event))


def event_staff_users(event, staff_role: str) -> List[User]:
    """Пользователи, назначенные на меро в данной роли staff (team_lead/manager)."""
    return list(User.objects.filter(
        staff_assignments__event=event, staff_assignments__staff_role=staff_role,
    ))


def organizer_organization_link_pairs() -> List[tuple]:
    """Пары (organization_id, organizer_id) всех связей — для зависимой фильтрации
    выбора организации/организатора на клиенте (форма меро)."""
    return list(OrganizerOrganizationLink.objects.values_list('organization_id', 'organizer_id'))


# --- Запись M2M-связей мероприятия из формы (event save) ---
def sync_event_categories(event, selected) -> None:
    """Приводит категории (kind=category) меро к выбранному набору; функцию не трогает."""
    EventCategoryMap.objects.filter(event=event, category__kind='category').exclude(category__in=selected).delete()
    for category in selected:
        EventCategoryMap.objects.get_or_create(event=event, category=category)


def set_event_function(event, function) -> None:
    """Функция позиции — ровно одна связь вида function."""
    EventCategoryMap.objects.filter(event=event, category__kind='function').exclude(category=function).delete()
    if function is not None:
        EventCategoryMap.objects.get_or_create(event=event, category=function)


def sync_event_perks(event, selected) -> None:
    """Приводит плюшки меро к выбранному набору (снять лишние, добавить новые)."""
    EventPerkMap.objects.filter(event=event).exclude(perk__in=selected).delete()
    for perk in selected:
        EventPerkMap.objects.get_or_create(event=event, perk=perk)


def sync_event_requirements(event, selected) -> None:
    EventRequirementMap.objects.filter(event=event).exclude(requirement__in=selected).delete()
    for requirement in selected:
        EventRequirementMap.objects.get_or_create(event=event, requirement=requirement)


def prune_event_staff(event, staff_role: str, keep_user_ids) -> None:
    """Снимает назначения staff данной роли, кроме пользователей из keep_user_ids."""
    event.staff.filter(staff_role=staff_role).exclude(user_id__in=keep_user_ids).delete()


def add_event_staff(event, user, staff_role: str) -> bool:
    """Назначает пользователя на меро в роли staff (идемпотентно). True, если создано."""
    _, created = EventStaff.objects.get_or_create(event=event, user=user, staff_role=staff_role)
    return created


def prune_event_manager(event, selected_user) -> None:
    """Снимает всех менеджеров меро, кроме выбранного (None → снять всех)."""
    event.staff.filter(staff_role='manager').exclude(user=selected_user).delete()


def has_active_team_leader_role(user) -> bool:
    return TeamLeader.objects.filter(user=user, revoked_at__isnull=True).exists()


def create_team_leader_role(user, assigned_by=None) -> TeamLeader:
    return TeamLeader.objects.create(user=user, assigned_by=assigned_by)


def get_or_create_organizer_organization_link(organizer, organization) -> None:
    OrganizerOrganizationLink.objects.get_or_create(organizer=organizer, organization=organization)
