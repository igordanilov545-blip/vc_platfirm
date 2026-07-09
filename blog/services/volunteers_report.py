"""Отчёт по волонтёрам (reports_template.md «Отчёт по волонтёрам»): сводная
статистика по выборке + карточки (блоки A-D «Отчёта по человеку») подряд по
алфавиту. Охват — «за всё время» либо «за период» (два отдельных прогона).
"""
from django.db.models import Sum

from blog.models import Application, Participation, User
from blog.services.person_report import person_report
from blog.services.stats import is_pgas_star


def volunteers_in_scope(date_from=None, date_to=None):
    """Волонтёры, у которых есть хотя бы одна заявка за охват (даже отклонённая) —
    выборка по умолчанию (reports_template.md)."""
    if date_from and date_to:
        user_ids = Application.objects.filter(
            created_at__date__gte=date_from, created_at__date__lte=date_to, user__isnull=False,
        ).values_list('user_id', flat=True).distinct()
    else:
        user_ids = Application.objects.filter(user__isnull=False).values_list('user_id', flat=True).distinct()
    return User.objects.filter(id__in=user_ids).order_by('last_name', 'first_name')


def volunteers_report(date_from=None, date_to=None, user_ids=None) -> dict:
    scoped = bool(date_from and date_to)

    if user_ids:
        users = User.objects.filter(id__in=user_ids).order_by('last_name', 'first_name')
    else:
        users = volunteers_in_scope(date_from, date_to)

    threshold = None
    from blog.models import Const
    const_row = Const.objects.filter(name='churn_blacklist_threshold').first()
    threshold = const_row.value if const_row else 5

    cards = [person_report(u.id, date_from, date_to) for u in users]

    total_hours = 0
    total_events = 0
    new_count = 0
    star_count = 0
    blacklisted_count = 0
    at_risk_count = 0
    hours_distribution = []

    for card in cards:
        u = card['user']
        hours = card['stats']['scoped_hours'] if scoped else card['stats']['total_hours']
        events = card['stats']['scoped_events'] if scoped else card['stats']['total_events']
        total_hours += hours or 0
        total_events += events or 0
        hours_distribution.append(hours or 0)
        if card['is_star']:
            star_count += 1
        if u.status == 'blacklisted':
            blacklisted_count += 1
        if (u.churn_score or 0) >= threshold * 0.8:
            at_risk_count += 1

    if date_from and date_to:
        new_count = User.objects.filter(
            id__in=[c['user'].id for c in cards],
            created_at__date__gte=date_from, created_at__date__lte=date_to,
        ).count()

    top_volunteers = sorted(
        [{'user': c['user'], 'hours': c['stats']['scoped_hours'] if scoped else c['stats']['total_hours']} for c in cards],
        key=lambda x: x['hours'] or 0, reverse=True,
    )[:10]

    churn_scores = [c['user'].churn_score or 0 for c in cards]
    churn_histogram = _histogram(churn_scores, threshold)

    return {
        'scope': {'scoped': scoped, 'date_from': date_from, 'date_to': date_to},
        'count': len(cards),
        'summary': {
            'total_volunteers': len(cards),
            'total_hours': total_hours,
            'total_events': total_events,
            'avg_hours': round(total_hours / len(cards), 1) if cards else 0,
            'new_count': new_count,
            'star_count': star_count,
            'blacklisted_count': blacklisted_count,
            'at_risk_count': at_risk_count,
        },
        'top_volunteers': top_volunteers,
        'hours_distribution': hours_distribution,
        'churn_histogram': churn_histogram,
        'churn_threshold': threshold,
        'cards': cards,
    }


def _histogram(values, threshold, bucket_size=1.0, max_buckets=8):
    buckets = []
    for i in range(max_buckets):
        low = i * bucket_size
        high = low + bucket_size
        if i == max_buckets - 1:
            count = sum(1 for v in values if v >= low)
            label = f'{low:g}+'
        else:
            count = sum(1 for v in values if low <= v < high)
            label = f'{low:g}–{high:g}'
        buckets.append({'label': label, 'low': low, 'count': count})
    return buckets
