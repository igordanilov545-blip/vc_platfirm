"""Отчёт по организации (reports_template.md «Отчёт по организации»): профиль,
контактные лица, статистика, все мероприятия организации подряд, история
взаимодействия. Охват — «за всё время» либо «за период» (по датам смен меро).
"""
from django.db.models import Avg, Count, Sum

from data_base import data_controller as dc


def organization_report(organization_id: int, date_from=None, date_to=None) -> dict:
    org = dc.get_organization_by_id(organization_id)
    scoped = bool(date_from and date_to)

    events_qs = dc.events_qs().filter(organization=org).prefetch_related(
        'shifts', 'category_map__category', 'feedbacks',
    )
    if scoped:
        events_qs = events_qs.filter(
            shifts__day__gte=date_from, shifts__day__lte=date_to,
        ).distinct()

    events_table = []
    categories_seen = {}
    total_volunteers_ids = set()
    total_hours = 0
    total_closed_shifts = 0
    total_people_helped = 0
    ratings = []

    for event in events_qs.order_by('-created_at'):
        shifts = list(event.shifts.all())
        days = [s.day for s in shifts]
        attended = dc.participations_qs().filter(event_day__event=event, status='attended')
        attended_ids = set(attended.values_list('user_id', flat=True))
        hours = attended.aggregate(s=Sum('hours'))['s'] or 0
        rating = event.feedbacks.aggregate(a=Avg('rating'))['a']

        total_volunteers_ids |= attended_ids
        total_hours += hours
        total_closed_shifts += attended.count()
        if event.people_helped:
            total_people_helped += event.people_helped
        if rating is not None:
            ratings.append(rating)

        for m in event.category_map.all():
            if m.category.kind != 'category':
                continue
            categories_seen[m.category.name] = categories_seen.get(m.category.name, 0) + 1

        events_table.append({
            'event': event,
            'date_from': min(days) if days else None,
            'date_to': max(days) if days else None,
            'status': event.get_event_status_display(),
            'volunteers_count': len(attended_ids),
            'rating': round(rating, 1) if rating is not None else None,
        })

    contacts = list(org.organizer_links.select_related('organizer').all())
    interactions = list(
        dc.organizer_interactions_qs().filter(
            organizer__organization_links__organization=org,
        ).select_related('organizer', 'author').order_by('-created_at').distinct()
    )

    return {
        'organization': org,
        'scope': {'scoped': scoped, 'date_from': date_from, 'date_to': date_to},
        'categories': sorted(categories_seen.keys()),
        'categories_breakdown': sorted(categories_seen.items(), key=lambda x: -x[1]),
        'contacts': contacts,
        'stats': {
            'events_count': len(events_table),
            'unique_volunteers': len(total_volunteers_ids),
            'closed_shifts': total_closed_shifts,
            'total_hours': total_hours,
            'people_helped': total_people_helped,
            'avg_rating': round(sum(ratings) / len(ratings), 1) if ratings else None,
        },
        'events': events_table,
        'interactions': interactions,
    }


def organizations_list_brief():
    """Для выпадающего списка выбора организации в карточке отчёта."""
    return dc.organizations_qs().order_by('name').values('id', 'name')
