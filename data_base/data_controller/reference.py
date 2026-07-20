"""Доступ к данным: справочные и вспомогательные сущности —
фидбек мероприятий, комментарии к пользователям, история чарна, сезоны, константы.
"""
from typing import Optional, List

from blog.models import (
    ChurnHistory, UserComment, EventFeedback, Season, Const, Event, User,
)


def create_churn_history(user: User, season: Season, churn_score: float) -> ChurnHistory:
    return ChurnHistory.objects.create(user=user, season=season, churn_score=churn_score)


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
