"""Периодическая статистика волонтёра — «карточки за период» (achievements.md,
раздел «Периодическая статистика»). Не геймификация, а готовый «слепок» для шаринга:
месяц / календарный квартал (3 месяца) / сезон ПГАС.

Здесь — только СБОРКА данных (dict на карточку); рендер картинки-шаринга — отдельный
будущий этап (в проекте уже есть PyMuPDF для писем, на него и обопрёмся). Каждая
карточка самодостаточна и берётся «фоточкой» для выкладки в канал.

Состав карточки (из доки): часы, мероприятия, скольким помог (сумма people_helped
посещённых меро периода), уникальные категории, любимая категория (+сколько меро в
ней), скольким организациям помог, самая быстрая заявка периода (submitted_at −
event.post_published_at). Диапазоны месяца/квартала — календарные; сезон ПГАС — из Season.
"""
import calendar
import datetime

from django.db.models import Count, Sum, F
from django.utils import timezone

from data_base import data_controller as dc


_MONTHS_RU = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
              'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
_MONTHS_RU_GEN = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']


def _attended_in(user, start, end):
    """attended-участия пользователя со сменой в [start, end] (даты включительно)."""
    return (
        dc.participations_qs()
        .filter(user=user, status='attended', event_day__day__gte=start, event_day__day__lte=end)
        .select_related('event_day__event', 'event_day__event__organization', 'event_day__location')
    )


def _period_card(user, title, subtitle, start, end):
    """Собрать одну карточку статистики за диапазон дат [start, end]."""
    parts = list(_attended_in(user, start, end))
    event_ids = {p.event_day.event_id for p in parts}
    hours = sum(p.hours for p in parts)

    # Скольким людям помог — сумма people_helped по РАЗНЫМ посещённым меро периода.
    from blog.models import Event
    people = Event.objects.filter(id__in=event_ids).aggregate(s=Sum('people_helped'))['s'] or 0

    # Категории периода + любимая (по числу разных меро в категории).
    cat_counts = {}
    org_ids = set()
    for p in parts:
        ev = p.event_day.event
        if ev.organization_id:
            org_ids.add(ev.organization_id)
    from blog.models import EventCategoryMap
    cat_rows = (
        EventCategoryMap.objects.filter(event_id__in=event_ids)
        .values('category__name').annotate(n=Count('event', distinct=True)).order_by('-n')
    )
    favourite = None
    categories_count = 0
    for row in cat_rows:
        categories_count += 1
        if favourite is None:
            favourite = {'name': row['category__name'], 'events': row['n']}

    # Самая быстрая заявка периода: min(submitted_at − post_published_at) среди заявок на
    # меро периода, у которых заполнены обе отметки. В минутах (может быть None).
    fastest = None
    delays = (
        dc.applications_qs()
        .filter(user=user, event_id__in=event_ids,
                submitted_at__isnull=False, event__post_published_at__isnull=False)
        .annotate(delay=F('submitted_at') - F('event__post_published_at'))
        .values_list('delay', flat=True)
    )
    for d in delays:
        if d is None:
            continue
        minutes = d.total_seconds() / 60.0
        if minutes < 0:
            continue
        fastest = minutes if fastest is None else min(fastest, minutes)

    return {
        'title': title,
        'subtitle': subtitle,
        'hours': hours,
        'events': len(event_ids),
        'people_helped': people,
        'categories': categories_count,
        'favourite_category': favourite,
        'organizations': len(org_ids),
        'fastest_application_minutes': round(fastest) if fastest is not None else None,
        'empty': not event_ids,
    }


def _month_range(year, month):
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last)


def build_period_stats(user, *, months_back=12):
    """Карточки статистики: помесячно за последние months_back месяцев (свежие сверху,
    включая пустые — чтобы был виден и «тихий» месяц) + текущий сезон ПГАС.

    Возвращает {'months': [card,…], 'season': card|None}."""
    today = timezone.localdate()

    months = []
    y, m = today.year, today.month
    for _ in range(months_back):
        start, end = _month_range(y, m)
        title = f'{_MONTHS_RU[m].capitalize()} {y}'
        months.append(_period_card(user, title, 'итоги месяца', start, end))
        m -= 1
        if m == 0:
            m = 12
            y -= 1

    season_card = None
    from blog.services.stats import current_season
    season = current_season()
    if season:
        start = season.start_season
        end = season.end_season or today
        label = (
            f'{_MONTHS_RU_GEN[start.month]} {start.year} — '
            f'{_MONTHS_RU_GEN[end.month]} {end.year}'
        )
        season_card = _period_card(user, 'Сезон ПГАС', label, start, end)

    return {'months': months, 'season': season_card}
