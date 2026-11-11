"""Отчёт по человеку (reports_template.md «Отчёт по человеку»): блоки A-F.

Охват — два режима: «за всё время» (period=None) либо «за период»
(date_from/date_to заданы). Блоки E/F (тим-лидер/менеджер) добавляются только
если у пользователя есть соответствующая активная роль.
"""
from django.db.models import Avg, Count, Sum

from data_base import data_controller as dc
from blog.services.stats import is_pgas_star


def _participations_qs(user, date_from=None, date_to=None):
    qs = dc.participations_qs().filter(user=user).select_related('event_day', 'event_day__event')
    if date_from and date_to:
        qs = qs.filter(event_day__day__gte=date_from, event_day__day__lte=date_to)
    return qs


def _applications_qs(user, date_from=None, date_to=None):
    qs = dc.applications_qs().filter(user=user).select_related('event', 'assigned_by')
    if date_from and date_to:
        qs = qs.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    return qs


def person_report(user_id: int, date_from=None, date_to=None) -> dict:
    user = dc.get_user_by_id(user_id)
    scoped = bool(date_from and date_to)

    participations = _participations_qs(user, date_from, date_to)
    attended = participations.filter(status='attended')
    applications = _applications_qs(user, date_from, date_to)

    hours_scoped = attended.aggregate(s=Sum('hours'))['s'] or 0
    events_scoped = attended.values('event_day__event').distinct().count()

    participations_table = [
        {
            'event': p.event_day.event.title,
            'event_id': p.event_day.event_id,
            'day': p.event_day.day,
            'shift': p.event_day,
            'status': p.get_status_display(),
            'status_code': p.status,
            'hours': p.hours,
        }
        for p in participations.order_by('-event_day__day')
    ]

    applications_table = [
        {
            'event': a.event.title,
            'event_id': a.event_id,
            'submitted_at': a.submitted_at or a.created_at,
            'status': a.get_status_display(),
            'status_code': a.status,
            'assigned_at': a.assigned_at,
        }
        for a in applications.order_by('-created_at')
    ]

    total_apps = applications.count()
    approved_apps = applications.filter(status='approved').count()
    conversion = round(approved_apps / total_apps * 100, 1) if total_apps else 0

    active_applications = dc.applications_qs().filter(
        user=user, status__in=['new', 'approved'],
    ).select_related('event')

    # Любимые категории (топ-3) по частоте участия.
    category_counts = (
        attended.filter(event_day__event__category_map__category__kind='category')
        .values('event_day__event__category_map__category__name')
        .annotate(count=Count('id'))
        .order_by('-count')[:3]
    )
    top_categories = [
        {'name': c['event_day__event__category_map__category__name'] or 'Без категории', 'count': c['count']}
        for c in category_counts if c['event_day__event__category_map__category__name']
    ]

    report = {
        'user': user,
        'scope': {'scoped': scoped, 'date_from': date_from, 'date_to': date_to},
        'is_star': is_pgas_star(user),
        'stats': {
            'total_hours': user.total_hours,
            'season_hours': user.season_hours,
            'total_events': user.total_event_count,
            'season_events': user.season_event_count,
            'scoped_hours': hours_scoped if scoped else None,
            'scoped_events': events_scoped if scoped else None,
            'avg_hours_per_event': round(hours_scoped / events_scoped, 1) if scoped and events_scoped else (
                round(user.total_hours / user.total_event_count, 1) if user.total_event_count else 0
            ),
        },
        'top_categories': top_categories,
        'participations': participations_table,
        'applications': applications_table,
        'applications_summary': {
            'total': total_apps,
            'approved': approved_apps,
            'conversion_pct': conversion,
        },
        'active_applications': list(active_applications),
        'internal': {
            'churn_score': user.churn_score,
            'churn_history': list(
                dc.churn_history_qs().filter(user=user).select_related('season').order_by('season__start_season')
            ),
            'comments': list(
                dc.user_comments_qs().filter(target_user=user).select_related('author', 'event').order_by('-created_at')
            ),
            'exceptions': list(
                dc.user_requirement_exceptions_qs().filter(user=user).select_related('requirement')
            ),
            'unexcused_count': participations.filter(status='absent_unexcused').count(),
        },
    }

    team_leader_role = dc.team_leaders_qs().filter(user=user, revoked_at__isnull=True).first()
    if team_leader_role:
        report['team_leader'] = _staff_role_block(user, team_leader_role, 'team_lead', date_from, date_to)

    manager_role = dc.managers_qs().filter(user=user, revoked_at__isnull=True).first()
    if manager_role:
        report['manager'] = _staff_role_block(user, manager_role, 'manager', date_from, date_to)

    return report


def _staff_role_block(user, role_record, staff_role: str, date_from=None, date_to=None) -> dict:
    events_qs = dc.event_staff_qs().filter(user=user, staff_role=staff_role).select_related('event')
    if date_from and date_to:
        events_qs = events_qs.filter(event__shifts__day__gte=date_from, event__shifts__day__lte=date_to).distinct()

    apps_scope = dc.applications_qs().filter(assigned_by=user)
    if date_from and date_to:
        apps_scope = apps_scope.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)

    processed = apps_scope.filter(assigned_at__isnull=False)
    durations = [
        (a.assigned_at - a.created_at).total_seconds()
        for a in processed if a.assigned_at
    ]
    avg_hours = round(sum(durations) / len(durations) / 3600, 1) if durations else None

    return {
        'total_events': role_record.total_events,
        'season_events': role_record.season_events,
        'scoped_events': events_qs.count() if (date_from and date_to) else None,
        'assigned_at': role_record.assigned_at,
        'revoked_at': role_record.revoked_at,
        'assigned_by': role_record.assigned_by,
        'applications_processed': apps_scope.filter(assigned_by__isnull=False).count(),
        'avg_processing_hours': avg_hours,
        'events': [es.event for es in events_qs],
    }
