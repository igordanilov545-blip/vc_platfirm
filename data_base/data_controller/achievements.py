"""Доступ к данным: система достижений (achievements.md).

Тонкий CRUD над AchievementDefinition / UserAchievement / AchievementStat. Вся логика
«какое достижение выдать и на какой ступени» — в blog/services/achievements.py, не тут.
Изменяющие функции логируются в канал vc.db.
"""
from typing import Optional

from django.db.models import Count, Min, Max
from django.utils import timezone

from blog.models import AchievementDefinition, UserAchievement, AchievementStat, User
from ._base import logger, actor


def achievement_definitions_qs():
    """Ленивый queryset шаблонов достижений (для отчётов/UI-раскладки)."""
    return AchievementDefinition.objects.all()


def get_active_definitions():
    """Активные шаблоны достижений (список), отсортированные по группе/порядку."""
    return list(AchievementDefinition.objects.filter(is_active=True))


def get_definition_by_code(code: str) -> Optional[AchievementDefinition]:
    return AchievementDefinition.objects.filter(code=code).first()


def create_definition(**fields) -> AchievementDefinition:
    """Завести шаблон достижения (в т.ч. курс, заводимый менеджером с платформы)."""
    obj = AchievementDefinition.objects.create(**fields)
    logger.info('INSERT achievement_definitions: code=%s by=%s', obj.code, actor(fields.get('created_by')))
    return obj


def user_achievements_qs():
    return UserAchievement.objects.all()


def get_user_achievements(user: User):
    """Все выданные достижения пользователя (со ссылкой на шаблон), свежие сверху."""
    return list(
        UserAchievement.objects.filter(user=user)
        .select_related('achievement')
        .order_by('-granted_at')
    )


def has_user_achievement(user: User, achievement: AchievementDefinition, series_value=None) -> bool:
    """Есть ли у пользователя уже эта строка достижения (для идемпотентной выдачи).
    Для single series_value=None; для series — конкретная ступень."""
    return UserAchievement.objects.filter(
        user=user, achievement=achievement, series_value=series_value
    ).exists()


def grant_achievement(user: User, achievement: AchievementDefinition, *,
                      series_value=None, context=None, granted_by=None) -> UserAchievement:
    """Выдать достижение (одна строка). Уникальность (user, achievement, series_value)
    гарантируется на уровне БД — вызов защищайте has_user_achievement в сервисе."""
    obj = UserAchievement.objects.create(
        user=user, achievement=achievement, series_value=series_value,
        context=context, granted_by=granted_by,
    )
    logger.info(
        'INSERT user_achievements: user=%s code=%s step=%s by=%s',
        user.id, achievement.code, series_value, actor(granted_by),
    )
    return obj


def recompute_achievement_stat(achievement: AchievementDefinition) -> AchievementStat:
    """Пересчитать агрегат holders_count/first/last по user_achievements (источник истины).

    holders_count — число РАЗНЫХ пользователей, у кого есть это достижение (series с
    несколькими ступенями у одного человека считается как один держатель)."""
    grants = UserAchievement.objects.filter(achievement=achievement)
    agg = grants.aggregate(
        holders=Count('user', distinct=True),
        first=Min('granted_at'),
        last=Max('granted_at'),
    )
    stat, _ = AchievementStat.objects.update_or_create(
        achievement=achievement,
        defaults={
            'holders_count': agg['holders'] or 0,
            'first_granted_at': agg['first'],
            'last_granted_at': agg['last'],
        },
    )
    return stat


def get_achievement_stats_map():
    """{achievement_id: holders_count} — для показа «сколько людей имеют» в UI."""
    return {s.achievement_id: s.holders_count for s in AchievementStat.objects.all()}


def count_stats_denominator() -> int:
    """Знаменатель для процента «у скольких людей есть» у ОБЩИХ достижений: число живых
    волонтёров-держателей (не «мёртвые души»). Берём пользователей со статусом active и
    хотя бы одним посещённым мероприятием — так процент не размывается выпускниками
    двухлетней давности (achievements.md §Дополнительно)."""
    return (
        User.objects.filter(status='active', participations__status='attended')
        .distinct().count()
    )
