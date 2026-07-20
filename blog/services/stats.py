"""Пересчёт кэш-агрегатов пользователя и churn (db.md, бизнес-правила 1, 9)."""
import math
from datetime import timedelta

from django.db.models import Sum, Count
from django.utils import timezone

from blog.models import Participation, Const, Season, ChurnHistory, ChurnLog
from blog.logging_utils import get_web_logger

logger = get_web_logger(__name__)


def _const(name: str, default: float) -> float:
    try:
        return Const.objects.get(name=name).value
    except Const.DoesNotExist:
        return default


def log_churn_change(user, reason, delta, *, actor=None, event=None, note=None, force=False):
    """Записать изменение churn_score в журнал (ChurnLog). Вызывается ВСЕМИ точками,
    где меняется churn: неявка, списание за активность, сброс по сезону, блокировка/
    разблокировка. new_value берём из user.churn_score (уже пересчитанного). delta≈0
    (незначимое списание за активность) не логируем, чтобы не засорять историю — КРОМЕ
    случая `force=True`: событийные записи (блокировка менеджером) должны попасть в
    журнал даже при delta=0, важен сам факт события, а не изменение числа.

    Запись идёт через data_controller (единый слой доступа + аудит), а не прямым ORM."""
    if abs(delta) < 1e-9 and not force:
        return
    from data_base import data_controller as dc
    dc.create_churn_log(
        user=user, reason=reason, delta=delta, new_value=user.churn_score or 0,
        actor_user=actor, event=event, note=note,
    )


def current_season():
    from django.db.models import Q
    today = timezone.now().date()
    return (
        Season.objects.filter(start_season__lte=today)
        .filter(Q(end_season__isnull=True) | Q(end_season__gte=today))
        .order_by('-start_season')
        .first()
    )


def recalc_user_aggregates(user):
    """Пересчитывает total_hours/season_hours/*_event_count по participations.status='attended'."""
    attended = Participation.objects.filter(user=user, status='attended')

    totals = attended.aggregate(hours=Sum('hours'), count=Count('id'))
    user.total_hours = totals['hours'] or 0
    user.total_event_count = totals['count'] or 0

    season = current_season()
    if season:
        season_qs = attended.filter(
            event_day__day__gte=season.start_season,
        )
        if season.end_season:
            season_qs = season_qs.filter(event_day__day__lte=season.end_season)
        season_totals = season_qs.aggregate(hours=Sum('hours'), count=Count('id'))
        user.season_hours = season_totals['hours'] or 0
        user.season_event_count = season_totals['count'] or 0
    else:
        user.season_hours = 0
        user.season_event_count = 0

    last = attended.order_by('-event_day__day').first()
    user.last_event_at = last.created_at if last else user.last_event_at

    user.save(update_fields=[
        'total_hours', 'total_event_count', 'season_hours', 'season_event_count', 'last_event_at'
    ])


def apply_churn_no_show(user, *, event=None, actor=None):
    """+churn_no_show_penalty за неявку без предупреждения (правило 9)."""
    penalty = _const('churn_no_show_penalty', 1)
    before = user.churn_score or 0
    user.churn_score = before + penalty
    hit_blacklist = _apply_blacklist_if_needed(user)
    user.save(update_fields=['churn_score', 'status'])
    log_churn_change(
        user, 'no_show', (user.churn_score or 0) - before,
        actor=actor, event=event,
        note='Достигнут порог — блокировка' if hit_blacklist else None,
    )


def apply_churn_activity_decay(user, *, event=None):
    """Списание за активность: -churn_activity_base / e^(N меро за последний месяц + 1)."""
    base = _const('churn_activity_base', 3)
    window_days = _const('churn_activity_window_days', 30)
    month_ago = timezone.now() - timedelta(days=window_days)
    n = Participation.objects.filter(
        user=user, status='attended', created_at__gte=month_ago
    ).count()
    decay = base / math.exp(n + 1)
    before = user.churn_score or 0
    user.churn_score = max(0.0, before - decay)
    user.save(update_fields=['churn_score'])
    log_churn_change(user, 'activity_decay', (user.churn_score or 0) - before, event=event)


def _apply_blacklist_if_needed(user):
    """Возвращает True, если пользователь был отправлен в блэклист этим вызовом."""
    threshold = _const('churn_blacklist_threshold', 5)
    if (user.churn_score or 0) >= threshold and user.status != 'blacklisted':
        user.status = 'blacklisted'
        logger.warning(
            'Волонтёр отправлен в блэклист по churn: user=%s churn_score=%.2f threshold=%.2f',
            user.id, user.churn_score or 0, threshold,
        )
        return True
    return False


def is_pgas_star(user) -> bool:
    threshold = _const('pgas_hours_threshold', 100)
    return (user.season_hours or 0) >= threshold


def recruit_status_for_shift(shift):
    """closed, когда approved >= recruit_close_ratio * volunteer_needed смены (правило 10).

    Заявка сейчас подаётся на мероприятие целиком (выбор конкретных смен ещё не
    реализован — см. ApplicationForm), поэтому одобренные заявки считаются общими
    по всему мероприятию и сравниваются с потребностью именно этой смены."""
    from blog.models import Application
    ratio = _const('recruit_close_ratio', 1.2)
    needed = shift.volunteer_needed or 0
    approved = Application.objects.filter(event=shift.event, status='approved').count()
    if needed and approved >= ratio * needed:
        return 'closed'
    return 'open'


def close_season(season):
    """Закрытие сезона (правила 9/11): снимок ненулевого churn в churn_history,
    carryover, обнуление season_*; авто-создание бессрочного сезона, если
    следующий не задан. Возвращает созданный сезон или None."""
    from blog.models import User
    min_seasons = _const('churn_carryover_min_seasons', 2)
    for user in User.objects.filter(churn_score__gt=0):
        ChurnHistory.objects.create(user=user, season=season, churn_score=user.churn_score)
        before = user.churn_score
        past_seasons = ChurnHistory.objects.filter(user=user).count()
        if past_seasons >= min_seasons:
            user.churn_score = user.churn_score / 2
        else:
            user.churn_score = 0
        user.save(update_fields=['churn_score'])
        log_churn_change(
            user, 'season_reset', (user.churn_score or 0) - before,
            note=f'Завершение сезона «{season}»',
        )

    User.objects.update(season_hours=0, season_event_count=0)

    today = timezone.now().date()
    if not season.end_season or season.end_season > today:
        season.end_season = today
        season.save(update_fields=['end_season'])

    next_start = season.end_season + timedelta(days=1)
    has_next = Season.objects.filter(start_season__gte=next_start).exists()
    logger.info('Сезон закрыт: season=%s end=%s создан_следующий=%s', season.id, season.end_season, not has_next)
    if not has_next:
        # Бессрочный сезон: end_season=NULL — плашка «нужно задать дату конца».
        return Season.objects.create(start_season=next_start, end_season=None)
    return None
