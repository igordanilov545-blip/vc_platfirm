"""Доступ к данным: мероприятия, смены, категории, staff, публикация и рассылка.

Доменный инвариант (coding-principles §6): набор (`recruit_status`, `volunteer_needed`)
живёт на СМЕНЕ (`EventShift`), а не на мероприятии. Здесь только тонкий CRUD —
вычисление статусов/наборов делают модели (`Event.compute_status`) и сервисы.
"""
from typing import Optional, List

from django.utils import timezone

from blog.models import (
    Location, Organization, Organizer, EventCategory, Event,
    EventCategoryMap, EventShift, EventStaff, User, DobroRuSharedLink,
)
from ._base import logger


def create_event_category(name: str) -> EventCategory:
    return EventCategory.objects.create(name=name)


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
