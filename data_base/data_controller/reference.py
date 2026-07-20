"""Доступ к данным: справочные и вспомогательные сущности —
фидбек мероприятий, комментарии к пользователям, история/журнал чарна, инциденты,
сезоны, константы.
"""
from typing import Optional, List

from django.utils import timezone

from blog.models import (
    ChurnHistory, ChurnLog, UserComment, EventFeedback, Season, Const, Event, User,
    Incident,
)
from ._base import logger, actor


def create_churn_history(user: User, season: Season, churn_score: float) -> ChurnHistory:
    return ChurnHistory.objects.create(user=user, season=season, churn_score=churn_score)


def create_churn_log(
    user: User, reason: str, delta: float, new_value: float,
    actor_user: Optional[User] = None, event: Optional[Event] = None, note: Optional[str] = None,
) -> ChurnLog:
    """Записывает событие изменения churn в журнал (ChurnLog). Тонкая обёртка — фильтр
    «незначимую delta не логируем» остаётся в сервисе (stats.log_churn_change), т.к. это
    бизнес-правило, а не доступ к данным."""
    entry = ChurnLog.objects.create(
        user=user, reason=reason, delta=delta, new_value=new_value,
        actor=actor_user, event=event, note=note,
    )
    logger.info('INSERT churn_log: user=%s reason=%s delta=%s by=%s', user.id, reason, delta, actor(actor_user))
    return entry


def resolve_incidents(kind: str, related_user: User, resolved_by: Optional[User] = None) -> int:
    """Помечает открытые инциденты данного вида по пользователю решёнными. Возвращает
    число затронутых. Используется, напр., при подтверждении верификации ПГАС."""
    updated = Incident.objects.filter(
        kind=kind, related_user=related_user, resolved_at__isnull=True,
    ).update(resolved_at=timezone.now(), resolved_by=resolved_by)
    if updated:
        logger.info('UPDATE incidents: kind=%s subject=user=%s resolved=%s by=%s',
                    kind, related_user.id, updated, actor(resolved_by))
    return updated


def create_user_comment(target_user: User, author: Optional[User], text: str, event: Optional[Event] = None) -> UserComment:
    return UserComment.objects.create(target_user=target_user, author=author, event=event, text=text)


def create_feedback(author: User, event: Event, rating: int, comment: Optional[str] = None) -> EventFeedback:
    return EventFeedback.objects.create(author=author, event=event, rating=rating, comment=comment)


def create_season(start_date: str, end_date: str) -> Season:
    return Season.objects.create(start_season=start_date, end_season=end_date)


def get_feedbacks(event_id: Optional[int] = None, author_id: Optional[int] = None) -> List[EventFeedback]:
    qs = EventFeedback.objects.all()
    if event_id:
        qs = qs.filter(event_id=event_id)
    if author_id:
        qs = qs.filter(author_id=author_id)
    return list(qs)


def has_feedback(author_id: int, event_id: int) -> bool:
    return EventFeedback.objects.filter(author_id=author_id, event_id=event_id).exists()


def get_seasons() -> List[Season]:
    return list(Season.objects.all().order_by('-start_season'))


def get_churn_history(user_id: Optional[int] = None, season_id: Optional[int] = None) -> List[ChurnHistory]:
    qs = ChurnHistory.objects.select_related('season')
    if user_id:
        qs = qs.filter(user_id=user_id)
    if season_id:
        qs = qs.filter(season_id=season_id)
    return list(qs.order_by('-created_at'))


def get_user_comments(target_user_id: Optional[int] = None) -> List[UserComment]:
    qs = UserComment.objects.select_related('author', 'event')
    if target_user_id:
        qs = qs.filter(target_user_id=target_user_id)
    return list(qs.order_by('-created_at'))


def get_const(name: str, default: Optional[float] = None) -> float:
    try:
        return Const.objects.get(name=name).value
    except Const.DoesNotExist:
        if default is not None:
            return default
        raise


def get_all_consts() -> List[Const]:
    return list(Const.objects.all().order_by('name'))
