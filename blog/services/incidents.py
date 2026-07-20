"""Инциденты для раздела «Главное» менеджера — чек-лист того, что требует внимания
(коллизии Telegram-аккаунтов, идущие/скоро начинающиеся мероприятия, запросы
верификации для справки ПГАС). См. Incident в blog/models.py."""
from datetime import timedelta

from django.utils import timezone

from blog.models import Incident, User
from blog.logging_utils import get_web_logger

logger = get_web_logger(__name__)


def create_incident(kind: str, text: str, related_user: User = None, related_event=None) -> Incident:
    return Incident.objects.create(
        kind=kind, text=text, related_user=related_user, related_event=related_event,
    )


def get_or_create_event_ongoing_incident(event) -> Incident:
    """Идемпотентно: одно мероприятие — один открытый инцидент типа `event_ongoing`
    (не плодим дубли при каждом заходе на дашборд, пока меро идёт/скоро начнётся)."""
    existing = Incident.objects.filter(
        kind='event_ongoing', related_event=event, resolved_at__isnull=True,
    ).first()
    if existing:
        return existing
    return create_incident(
        'event_ongoing', f'Мероприятие «{event.title}» идёт или начинается в ближайшие сутки.',
        related_event=event,
    )


def sync_ongoing_event_incidents():
    """Пересчитывает инциденты `event_ongoing`: создаёт для мероприятий, у которых
    сегодня или в ближайшие 24ч есть смена, и автоматически резолвит те, что были
    актуальны раньше, но уже не подходят под условие (смена прошла)."""
    from blog.models import Event

    from data_base import data_controller as dc
    now = timezone.now()
    horizon = now + timedelta(hours=dc.get_const('event_ongoing_horizon_hours', default=24))
    today = now.date()
    horizon_date = horizon.date()

    qs = Event.objects.filter(
        shifts__day__gte=today, shifts__day__lte=horizon_date,
    ).exclude(event_status='finished').distinct()
    for event in qs:
        get_or_create_event_ongoing_incident(event)

    # Резолвим устаревшие: инцидент есть, но событие больше не попадает в горизонт.
    still_relevant_ids = set(qs.values_list('id', flat=True))
    stale = Incident.objects.filter(kind='event_ongoing', resolved_at__isnull=True).exclude(
        related_event_id__in=still_relevant_ids
    )
    stale.update(resolved_at=timezone.now())


def get_open_incidents():
    sync_ongoing_event_incidents()
    return list(
        Incident.objects.filter(resolved_at__isnull=True)
        .select_related('related_user', 'related_event')
        .order_by('-created_at')
    )


def resolve_incident(incident_id: int, by: User) -> bool:
    updated = Incident.objects.filter(pk=incident_id, resolved_at__isnull=True).update(
        resolved_at=timezone.now(), resolved_by=by,
    )
    if updated:
        logger.info('Инцидент отмечен решённым: incident=%s by=%s', incident_id, by.id if by else None)
    return bool(updated)
