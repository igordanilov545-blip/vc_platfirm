"""Отчёт за период и вспомогательная аналитика (reports.md раздел 7)."""
from django.db.models import Avg, Count, Sum

from blog.models import Application, Event, Participation, User


def period_report(date_from, date_to, prev_from=None, prev_to=None):
    # Отчёт по мероприятиям считается только по завершённым (event_status='finished') —
    # ещё идущие/будущие меро не должны попадать в статистику периода задним числом.
    participations = Participation.objects.filter(
        event_day__day__gte=date_from, event_day__day__lte=date_to,
        event_day__event__event_status='finished',
    )
    attended = participations.filter(status='attended')

    total_hours = attended.aggregate(s=Sum('hours'))['s'] or 0
    total_events = Event.objects.filter(
        shifts__day__gte=date_from, shifts__day__lte=date_to, event_status='finished',
    ).distinct().count()
    unique_volunteers = attended.values('user').distinct().count()
    closed_shifts = attended.count()
    new_volunteers = User.objects.filter(
        created_at__date__gte=date_from, created_at__date__lte=date_to
    ).count()
    people_helped = Event.objects.filter(
        shifts__day__gte=date_from, shifts__day__lte=date_to, event_status='finished',
    ).distinct().aggregate(s=Sum('people_helped'))['s'] or 0

    top_volunteers = list(
        attended.values('user__id', 'user__telegram_username', 'user__first_name', 'user__last_name')
        .annotate(hours=Sum('hours'))
        .order_by('-hours')[:10]
    )

    top_categories = list(
        attended.values('event_day__event__category_map__category__name')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    # Воронка набора
    apps_period = Application.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    submitted = apps_period.count()
    approved = apps_period.filter(status='approved').count()
    rejected = apps_period.filter(status='rejected').count()
    attended_count = attended.count()
    unexcused = participations.filter(status='absent_unexcused').count()
    conversion = (attended_count / submitted * 100) if submitted else 0

    # Retention / churn
    from blog.models import Const
    threshold = Const.objects.filter(name='churn_blacklist_threshold').first()
    threshold_value = threshold.value if threshold else 5
    active_total = User.objects.filter(status='active').count() or 1
    churned = User.objects.filter(churn_score__gte=threshold_value).count()
    churn_rate = churned / active_total * 100
    new_blacklisted = User.objects.filter(
        status='blacklisted', created_at__date__gte=date_from, created_at__date__lte=date_to
    ).count()

    # Проблемные зоны
    low_rated_events = list(
        Event.objects.annotate(avg_rating=Avg('feedbacks__rating'), fb_count=Count('feedbacks'))
        .filter(avg_rating__lt=6, fb_count__gt=0)
        .values('id', 'title', 'avg_rating', 'fb_count')
    )

    at_risk_users = list(
        User.objects.filter(churn_score__gte=threshold_value * 0.8)
        .values('id', 'telegram_username', 'first_name', 'last_name', 'churn_score')
        .order_by('-churn_score')[:20]
    )

    comparison = None
    if prev_from and prev_to:
        prev = period_report_basic(prev_from, prev_to)
        comparison = {
            'hours_delta': total_hours - prev['total_hours'],
            'events_delta': total_events - prev['total_events'],
            'volunteers_delta': unique_volunteers - prev['unique_volunteers'],
            'new_volunteers_delta': new_volunteers - prev['new_volunteers'],
        }

    return {
        'total_hours': total_hours,
        'total_events': total_events,
        'unique_volunteers': unique_volunteers,
        'closed_shifts': closed_shifts,
        'new_volunteers': new_volunteers,
        'people_helped': people_helped,
        'top_volunteers': top_volunteers,
        'top_categories': top_categories,
        'funnel': {
            'submitted': submitted,
            'approved': approved,
            'rejected': rejected,
            'attended': attended_count,
            'unexcused': unexcused,
            'conversion_pct': round(conversion, 1),
        },
        'retention': {
            'churn_rate_pct': round(churn_rate, 1),
            'new_blacklisted': new_blacklisted,
        },
        'problem_zones': {
            'low_rated_events': low_rated_events,
            'at_risk_users': at_risk_users,
        },
        'comparison': comparison,
    }


def period_report_basic(date_from, date_to):
    """Облегчённая версия для сравнения с предыдущим периодом (без рекурсии)."""
    attended = Participation.objects.filter(
        event_day__day__gte=date_from, event_day__day__lte=date_to, status='attended',
        event_day__event__event_status='finished',
    )
    return {
        'total_hours': attended.aggregate(s=Sum('hours'))['s'] or 0,
        'total_events': Event.objects.filter(
            shifts__day__gte=date_from, shifts__day__lte=date_to, event_status='finished',
        ).distinct().count(),
        'unique_volunteers': attended.values('user').distinct().count(),
        'new_volunteers': User.objects.filter(
            created_at__date__gte=date_from, created_at__date__lte=date_to
        ).count(),
    }


def weekly_dynamics(date_from, date_to):
    """Динамика по неделям: часы и закрытые смены на каждую неделю периода.
    Используется для графика в отчёте за период."""
    from datetime import timedelta

    weeks = []
    max_hours = 0
    cursor = date_from
    while cursor <= date_to:
        week_end = min(cursor + timedelta(days=6), date_to)
        attended = Participation.objects.filter(
            event_day__day__gte=cursor, event_day__day__lte=week_end, status='attended',
            event_day__event__event_status='finished',
        )
        hours = attended.aggregate(s=Sum('hours'))['s'] or 0
        shifts = attended.count()
        max_hours = max(max_hours, hours)
        weeks.append({
            'from': cursor,
            'to': week_end,
            'hours': hours,
            'shifts': shifts,
        })
        cursor = week_end + timedelta(days=1)

    for week in weeks:
        week['pct'] = round(week['hours'] / max_hours * 100) if max_hours else 0
    return weeks


def recruitment_efficiency(date_from, date_to):
    """% закрытия слотов по каждому меро, недокомплект (reports.md) — только по
    завершённым мероприятиям, у идущих/будущих ещё нет окончательной явки."""
    events = Event.objects.filter(
        shifts__day__gte=date_from, shifts__day__lte=date_to, event_status='finished',
    ).distinct()
    result = []
    for event in events:
        needed = event.shifts.aggregate(s=Sum('volunteer_needed'))['s'] or 0
        attended = Participation.objects.filter(event_day__event=event, status='attended').count()
        pct = (attended / needed * 100) if needed else 0
        result.append({
            'event_id': event.id,
            'title': event.title,
            'needed': needed,
            'attended': attended,
            'pct_closed': round(pct, 1),
            'understaffed': needed > 0 and (attended / needed) < 0.8,
        })
    return result


def staff_load(date_from, date_to):
    """Нагрузка персонала: меро/заявки на менеджера и тим-лидера за период —
    по мероприятиям считаем только завершённые (не будущую/текущую нагрузку)."""
    from blog.models import EventStaff

    managers = list(
        EventStaff.objects.filter(
            staff_role='manager', event__shifts__day__gte=date_from, event__shifts__day__lte=date_to,
            event__event_status='finished',
        ).values('user__id', 'user__first_name', 'user__last_name').annotate(event_count=Count('event', distinct=True))
    )
    team_leads = list(
        EventStaff.objects.filter(
            staff_role='team_lead', event__shifts__day__gte=date_from, event__shifts__day__lte=date_to,
            event__event_status='finished',
        ).values('user__id', 'user__first_name', 'user__last_name').annotate(event_count=Count('event', distinct=True))
    )
    apps_by_manager = list(
        Application.objects.filter(
            created_at__date__gte=date_from, created_at__date__lte=date_to, assigned_by__isnull=False
        ).values('assigned_by__id', 'assigned_by__first_name', 'assigned_by__last_name')
        .annotate(processed=Count('id'))
    )
    return {'managers': managers, 'team_leads': team_leads, 'applications_processed': apps_by_manager}
