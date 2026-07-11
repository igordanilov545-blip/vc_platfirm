"""Отчёт за период и вспомогательная аналитика (ERP-дашборд «Отчёты»).

Охват отчёта — это ВСЕГДА явный набор мероприятий (`event_ids`): страница строит пул
мероприятий по выбранному диапазону дат и статус-режиму (все/идущие/прошедшие), даёт
пользователю убрать лишние чипами, и передаёт сюда итоговый список id. Диапазон дат
(date_from/date_to) при этом всё равно нужен для графиков с временной осью (динамика).

В отличие от прежней версии отчётов, охват НЕ ограничен `event_status='finished'` —
считаем по фактически выбранным мероприятиям любого статуса (по незавершённым часы/явка
могут быть не проставлены — цифры тогда частичные, это ожидаемо). Сравнение с прошлым
периодом (дельты) убрано из UI — функции `*_basic`/`previous_period_range` больше не
вызываются страницей, оставлены только для обратной совместимости с экспортом.
"""
import math
from datetime import date, timedelta

from django.db.models import Avg, Count, Max, Min, Q, Sum

from blog.models import Application, Event, EventShift, Participation, Season, User

# Режимы статус-фильтра пула мероприятий (под-переключатель над чипами охвата).
EVENT_SCOPE_MODES = ('all', 'ongoing', 'past')


def events_pool(date_from, date_to, status_mode='all', exclude_ids=None):
    """Пул мероприятий для выбора охвата: все меро, у которых есть смена в диапазоне
    [date_from; date_to], отфильтрованные по статус-режиму и без явно убранных.

    status_mode:
      - 'all'     — любые мероприятия периода (по умолчанию);
      - 'ongoing' — идущие (compute_status == 'ongoing') либо предстоящие в периоде;
      - 'past'    — прошедшие/завершённые (compute_status in {'passed','finished'}).

    Возвращает список id (порядок — по первой смене, свежие сверху). Мероприятий в
    системе десятки/сотни, поэтому compute_status в Python здесь допустим (не тысячи)."""
    exclude_ids = set(exclude_ids or [])
    qs = (
        Event.objects.filter(shifts__day__gte=date_from, shifts__day__lte=date_to)
        .distinct()
        .prefetch_related('shifts')
    )
    result = []
    for event in qs:
        if event.id in exclude_ids:
            continue
        if status_mode == 'ongoing' and event.compute_status() not in ('ongoing', 'upcoming'):
            continue
        if status_mode == 'past' and event.compute_status() not in ('passed', 'finished'):
            continue
        result.append(event.id)
    return result


def _events_in_scope(date_from=None, date_to=None, event_ids=None):
    """Мероприятия охвата — по явному списку id (см. events_pool) либо, как запасной
    вариант, все меро со сменами в периоде (без ограничения на статус)."""
    if event_ids is not None:
        return Event.objects.filter(id__in=event_ids).distinct()
    return Event.objects.filter(shifts__day__gte=date_from, shifts__day__lte=date_to).distinct()


def _shifts_in_scope(date_from=None, date_to=None, event_ids=None):
    if event_ids is not None:
        return EventShift.objects.filter(event_id__in=event_ids)
    return EventShift.objects.filter(day__gte=date_from, day__lte=date_to)


def period_report(date_from=None, date_to=None, prev_from=None, prev_to=None, event_ids=None):
    events = _events_in_scope(date_from, date_to, event_ids)
    shifts = _shifts_in_scope(date_from, date_to, event_ids)

    participations = Participation.objects.filter(event_day__in=shifts)
    attended = participations.filter(status='attended')

    total_hours = attended.aggregate(s=Sum('hours'))['s'] or 0
    total_events = events.count()
    unique_volunteers = attended.values('user').distinct().count()
    closed_shifts = attended.count()  # число «человеко-смен» (посещённых слотов)
    new_volunteers = _new_volunteers_count(date_from, date_to, event_ids)
    people_helped = events.aggregate(s=Sum('people_helped'))['s'] or 0

    # --- Дополнительные KPI (плитки дашборда) ---
    total_shifts = shifts.count()  # число СМЕН в охвате (не человеко-смен)
    # Заявки охвата: обработано (assigned) из общего числа поданных.
    apps_all = Application.objects.filter(event__in=events)
    applications_total = apps_all.count()
    applications_processed = apps_all.filter(assigned_at__isnull=False).count()
    # Средние: смен и часов на одного пришедшего волонтёра; людей помогли на меро.
    avg_shifts_per_person = round(closed_shifts / unique_volunteers, 1) if unique_volunteers else 0
    avg_hours_per_person = round(total_hours / unique_volunteers, 1) if unique_volunteers else 0
    # «Людей помогли на меро» считаем только по меро, где people_helped проставлено
    # (иначе нули занизят среднее и оно потеряет смысл).
    helped_events = events.filter(people_helped__isnull=False).exclude(people_helped=0)
    helped_events_count = helped_events.count()
    avg_people_helped = round(people_helped / helped_events_count, 1) if helped_events_count else 0

    top_volunteers = list(
        attended.values('user__id', 'user__telegram_username', 'user__first_name', 'user__last_name')
        .annotate(hours=Sum('hours'))
        .order_by('-hours')[:10]
    )
    # Готовое имя без "None" (у части профилей всё ФИО в first_name, а last_name пуст).
    for v in top_volunteers:
        full = f"{v['user__first_name'] or ''} {v['user__last_name'] or ''}".strip()
        v['name'] = full or v['user__telegram_username'] or '—'

    category_breakdown = list(
        attended.values(
            name=models_f('event_day__event__category_map__category__name'),
        ).annotate(
            volunteers=Count('user', distinct=True),
            hours=Sum('hours'),
            events=Count('event_day__event', distinct=True),
        ).order_by('-volunteers')
    )
    top_categories = [{'event_day__event__category_map__category__name': c['name'], 'count': c['volunteers']} for c in category_breakdown[:10]]

    # Воронка набора (охват — всегда список меро)
    apps_scope = Application.objects.filter(event__in=events)
    submitted = apps_scope.count()
    approved = apps_scope.filter(status='approved').count()
    rejected = apps_scope.filter(status='rejected').count()
    attended_count = attended.count()
    unexcused = participations.filter(status='absent_unexcused').count()
    conversion = (attended_count / submitted * 100) if submitted else 0

    # Явка / дисциплина (график 7): распределение статусов участий в охвате.
    absent_excused = participations.filter(status='absent_excused').count()
    attendance = {
        'attended': attended_count,
        'absent_excused': absent_excused,
        'absent_unexcused': unexcused,
        'total': attended_count + absent_excused + unexcused,
    }

    # Оценки мероприятий (график 11): распределение рейтингов 0–10 и средняя.
    ratings = _ratings_distribution(events)

    # Проблемные зоны — низко-оценённые меро (для блока «требует внимания»).
    low_rated_events = list(
        events.annotate(avg_rating=Avg('feedbacks__rating'), fb_count=Count('feedbacks'))
        .filter(avg_rating__lt=6, fb_count__gt=0)
        .values('id', 'title', 'avg_rating', 'fb_count')
    )

    # --- Ниже: данные, которые НЕ показываются на экранном дашборде (график churn,
    # retention, сравнение убраны из UI), но их читают генераторы DOCX/Excel-отчётов
    # (report_builders/report_exports). Оставлены ради обратной совместимости экспорта —
    # финальный вид скачиваемых документов не меняем. ---
    from blog.models import Const
    threshold = Const.objects.filter(name='churn_blacklist_threshold').first()
    threshold_value = threshold.value if threshold else 5
    active_total = User.objects.filter(status='active').count() or 1
    churned = User.objects.filter(churn_score__gte=threshold_value).count()
    churn_rate = churned / active_total * 100
    if event_ids is not None:
        new_blacklisted = 0
    else:
        new_blacklisted = User.objects.filter(
            status='blacklisted', created_at__date__gte=date_from, created_at__date__lte=date_to,
        ).count()
    at_risk_users = list(
        User.objects.filter(churn_score__gte=threshold_value * 0.8)
        .values('id', 'telegram_username', 'first_name', 'last_name', 'churn_score')
        .order_by('-churn_score')[:20]
    )
    comparison = None
    if prev_from and prev_to and event_ids is None:
        prev = period_report_basic(prev_from, prev_to)
        comparison = {
            'date_from': prev_from, 'date_to': prev_to,
            'hours_delta': total_hours - prev['total_hours'],
            'events_delta': total_events - prev['total_events'],
            'volunteers_delta': unique_volunteers - prev['unique_volunteers'],
            'new_volunteers_delta': new_volunteers - prev['new_volunteers'],
            'hours_delta_pct': _pct_delta(total_hours, prev['total_hours']),
            'events_delta_pct': _pct_delta(total_events, prev['total_events']),
            'volunteers_delta_pct': _pct_delta(unique_volunteers, prev['unique_volunteers']),
            'new_volunteers_delta_pct': _pct_delta(new_volunteers, prev['new_volunteers']),
        }

    return {
        'total_hours': total_hours,
        'total_events': total_events,
        'unique_volunteers': unique_volunteers,
        'closed_shifts': closed_shifts,
        'new_volunteers': new_volunteers,
        'people_helped': people_helped,
        'total_shifts': total_shifts,
        'applications_total': applications_total,
        'applications_processed': applications_processed,
        'avg_shifts_per_person': avg_shifts_per_person,
        'avg_hours_per_person': avg_hours_per_person,
        'avg_people_helped': avg_people_helped,
        'top_volunteers': top_volunteers,
        'top_categories': top_categories,
        'category_breakdown': category_breakdown,
        'funnel': {
            'submitted': submitted,
            'approved': approved,
            'rejected': rejected,
            'attended': attended_count,
            'unexcused': unexcused,
            'conversion_pct': round(conversion, 1),
        },
        'attendance': attendance,
        'ratings': ratings,
        # Ключи ниже — только для генераторов DOCX/Excel (на дашборде не рендерятся).
        'retention': {
            'churn_rate_pct': round(churn_rate, 1),
            'new_blacklisted': new_blacklisted,
        },
        'churn_histogram': _churn_histogram(threshold_value),
        'churn_threshold': threshold_value,
        'problem_zones': {
            'low_rated_events': low_rated_events,
            'at_risk_users': at_risk_users,
        },
        'comparison': comparison,
    }


def _ratings_distribution(events):
    """Распределение оценок мероприятий охвата по значениям 0–10 + средняя и число
    отзывов (график 11). Средняя — по всем отзывам меро охвата."""
    from blog.models import EventFeedback
    feedbacks = EventFeedback.objects.filter(event__in=events)
    total = feedbacks.count()
    avg = feedbacks.aggregate(a=Avg('rating'))['a']
    by_value = {row['rating']: row['n'] for row in feedbacks.values('rating').annotate(n=Count('id'))}
    buckets = [{'rating': r, 'count': by_value.get(r, 0)} for r in range(0, 11)]
    return {
        'buckets': buckets,
        'avg': round(avg, 1) if avg is not None else None,
        'count': total,
    }


def models_f(name):
    """Мелкий хелпер, чтобы values(name=...) читался как алиас, а не голая строка."""
    from django.db.models import F
    return F(name)


def _pct_delta(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _new_volunteers_count(date_from, date_to, event_ids):
    # Страница отчётов теперь всегда передаёт диапазон дат (даже когда охват — явный
    # список меро), поэтому «новых волонтёров» считаем по датам создания аккаунта.
    if not date_from or not date_to:
        return 0
    return User.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to).count()


def _churn_histogram(threshold_value, bucket_size=1.0, max_buckets=8):
    """Гистограмма churn_score волонтёров по бакетам фиксированного шага —
    для графика «Распределение churn» (reports_template.md §1B, блок 5)."""
    buckets = []
    for i in range(max_buckets):
        low = i * bucket_size
        high = low + bucket_size
        if i == max_buckets - 1:
            count = User.objects.filter(churn_score__gte=low).count()
            label = f'{low:g}+'
        else:
            count = User.objects.filter(churn_score__gte=low, churn_score__lt=high).count()
            label = f'{low:g}–{high:g}'
        buckets.append({'label': label, 'low': low, 'high': high, 'count': count})
    return buckets


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


def previous_period_range(date_from, date_to, mode='adjacent'):
    """Диапазон «прошлого периода» для блока сравнения — два режима переключателя
    (reports_template.md): смежный интервал той же длины, либо тот же интервал год назад."""
    if mode == 'year_ago':
        try:
            prev_from = date_from.replace(year=date_from.year - 1)
            prev_to = date_to.replace(year=date_to.year - 1)
        except ValueError:
            # 29 февраля и т.п. — сдвигаем на ближайший валидный день.
            prev_from = date_from - timedelta(days=365)
            prev_to = date_to - timedelta(days=365)
        return prev_from, prev_to

    span = (date_to - date_from).days
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span)
    return prev_from, prev_to


def weekly_dynamics(date_from=None, date_to=None, event_ids=None):
    """Динамика по неделям — оставлена для генераторов DOCX/Excel (финальный вид
    документов не меняем). Экранный дашборд использует адаптивную `dynamics` ниже."""
    if event_ids is not None:
        return []
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
        max_hours = max(max_hours, hours)
        weeks.append({'from': cursor, 'to': week_end, 'hours': hours, 'shifts': attended.count()})
        cursor = week_end + timedelta(days=1)
    for week in weeks:
        week['pct'] = round(week['hours'] / max_hours * 100) if max_hours else 0
    return weeks


def _month_start(d):
    return d.replace(day=1)


def _add_month(d):
    return date(d.year + (d.month // 12), (d.month % 12) + 1, 1)


def dynamics(date_from, date_to, event_ids=None):
    """Адаптивная динамика активности для экранного дашборда (график 3).

    Шаг корзины подбирается под длину охвата, чтобы график не был ни пустым (1 день),
    ни частоколом (год по дням):
      - ≤ 14 дней  → по ДНЯМ;
      - ≤ 92 дня   → по НЕДЕЛЯМ;
      - иначе      → по МЕСЯЦАМ.
    Каждая корзина: сумма часов attended и число человеко-смен. Ограничен охватом меро
    (event_ids), если он задан. Возвращает {granularity, buckets:[{label, hours, shifts, pct}]}.
    """
    base = Participation.objects.filter(status='attended')
    if event_ids is not None:
        base = base.filter(event_day__event_id__in=event_ids)

    span_days = (date_to - date_from).days
    buckets = []

    def _bucket(lo, hi, label):
        qs = base.filter(event_day__day__gte=lo, event_day__day__lte=hi)
        hours = qs.aggregate(s=Sum('hours'))['s'] or 0
        buckets.append({'label': label, 'hours': hours, 'shifts': qs.count()})

    if span_days <= 14:
        granularity = 'day'
        cursor = date_from
        while cursor <= date_to:
            _bucket(cursor, cursor, cursor.strftime('%d.%m'))
            cursor += timedelta(days=1)
    elif span_days <= 92:
        granularity = 'week'
        cursor = date_from
        while cursor <= date_to:
            week_end = min(cursor + timedelta(days=6), date_to)
            _bucket(cursor, week_end, cursor.strftime('%d.%m'))
            cursor = week_end + timedelta(days=1)
    else:
        granularity = 'month'
        MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
        cursor = _month_start(date_from)
        while cursor <= date_to:
            nxt = _add_month(cursor)
            _bucket(cursor, min(nxt - timedelta(days=1), date_to), f'{MONTHS[cursor.month - 1]} {cursor.year % 100:02d}')
            cursor = nxt

    max_hours = max((b['hours'] for b in buckets), default=0)
    for b in buckets:
        b['pct'] = round(b['hours'] / max_hours * 100) if max_hours else 0
    return {'granularity': granularity, 'buckets': buckets}


def recruitment_efficiency(date_from=None, date_to=None, event_ids=None):
    """% закрытия слотов по каждой СМЕНЕ (не только по меро в целом) — reports_template.md
    §1 блок 3. Считается только по завершённым мероприятиям."""
    shifts = _shifts_in_scope(date_from, date_to, event_ids).select_related('event').order_by('event__title', 'day')
    result = []
    avg_recruit_days = []
    for shift in shifts:
        needed = shift.volunteer_needed or 0
        attended = Participation.objects.filter(event_day=shift, status='attended').count()
        pct = (attended / needed * 100) if needed else 0
        result.append({
            'event_id': shift.event_id,
            'shift_id': shift.id,
            'title': shift.event.title,
            'day': shift.day,
            'needed': needed,
            'attended': attended,
            'pct_closed': round(pct, 1),
            'understaffed': needed > 0 and (attended / needed) < 0.8,
        })

        last_approved = Application.objects.filter(
            event=shift.event, status='approved', assigned_at__isnull=False,
        ).order_by('-assigned_at').first()
        if last_approved and last_approved.assigned_at:
            days = (shift.day - last_approved.assigned_at.date()).days
            if days >= 0:
                avg_recruit_days.append(days)

    avg_recruit_time = round(sum(avg_recruit_days) / len(avg_recruit_days), 1) if avg_recruit_days else None

    # Свёртка по МЕРОПРИЯТИЯМ (график 4 дашборда): при 1–2 меро в неделю частокол
    # столбиков по сменам нечитаем — агрегируем needed/attended до уровня меро, каждое
    # меро = одна прогресс-строка с названием и % закрытия. Меро без плановой потребности
    # (needed=0) не показываем (нечего «закрывать»).
    by_event = {}
    for row in result:
        e = by_event.setdefault(row['event_id'], {'event_id': row['event_id'], 'title': row['title'], 'needed': 0, 'attended': 0})
        e['needed'] += row['needed']
        e['attended'] += row['attended']
    events_rollup = []
    for e in by_event.values():
        if e['needed'] <= 0:
            continue
        pct = e['attended'] / e['needed'] * 100
        e['pct_closed'] = round(pct, 1)
        e['understaffed'] = pct < 80
        events_rollup.append(e)
    events_rollup.sort(key=lambda x: x['pct_closed'])  # худшие сверху — на них смотрят первыми

    return {'shifts': result, 'events': events_rollup, 'avg_recruit_days': avg_recruit_time}


def _fmt_date(d):
    return d.strftime('%d.%m.%Y') if d else '—'


def _days_ago(d):
    """Сколько дней назад была дата d (по дате смены/заявки). None → '—'."""
    if not d:
        return None
    from django.utils import timezone
    today = timezone.now().date()
    if hasattr(d, 'date'):
        d = d.date()
    return (today - d).days


def _volunteer_activity_metrics(user_ids):
    """Общие «волонтёрские» метрики по каждому пользователю (используются в таблицах
    волонтёров, тим-лидеров и менеджеров — чтобы не дублировать расчёт). Возвращает
    dict user_id -> {...} со сводкой по ВСЕМ участиям пользователя (не только в охвате):
    часы всего/за сезон, меро всего/за сезон, смены всего/за сезон, средняя длительность
    смены, средняя явка на меро, даты первого/последнего меро и последней заявки.

    Сезонные метрики берутся из кэш-полей User (season_hours/season_event_count) — они
    поддерживаются пересчётом; «за всё время» считаем по participations напрямую."""
    from django.utils import timezone
    from django.db.models import Min, Max, DurationField, ExpressionWrapper, F

    if not user_ids:
        return {}
    users = User.objects.filter(id__in=user_ids).values(
        'id', 'first_name', 'last_name', 'middle_name', 'telegram_username', 'phone',
        'total_hours', 'season_hours', 'total_event_count', 'season_event_count',
        'churn_score', 'created_at',
    )
    metrics = {}
    for u in users:
        full = f"{u['last_name'] or ''} {u['first_name'] or ''} {u['middle_name'] or ''}".strip()
        metrics[u['id']] = {
            'user_id': u['id'],
            'name': full or u['telegram_username'] or f"#{u['id']}",
            'telegram': u['telegram_username'] or '—',
            'phone': u['phone'] or '—',
            'hours_total': u['total_hours'] or 0,
            'hours_season': u['season_hours'] or 0,
            'events_total': u['total_event_count'] or 0,
            'events_season': u['season_event_count'] or 0,
            'churn': round(u['churn_score'] or 0, 1),
        }

    # Все участия этих пользователей (attended) — для смен, длительностей, дат.
    parts = (
        Participation.objects.filter(user_id__in=user_ids, status='attended')
        .select_related('event_day')
        .values('user_id', 'hours', 'event_day__day', 'event_day__start_time', 'event_day__end_time')
    )
    agg = {uid: {'shifts': 0, 'dur_sum': 0.0, 'dur_n': 0, 'days': [], 'events': set()} for uid in metrics}
    part_events = {uid: set() for uid in metrics}
    for p in parts:
        uid = p['user_id']
        a = agg[uid]
        a['shifts'] += 1
        st, en = p['event_day__start_time'], p['event_day__end_time']
        if st and en:
            a['dur_sum'] += (en - st).total_seconds() / 3600
            a['dur_n'] += 1
        if p['event_day__day']:
            a['days'].append(p['event_day__day'])

    # Число меро (distinct) по каждому пользователю.
    ev_counts = (
        Participation.objects.filter(user_id__in=user_ids, status='attended')
        .values('user_id').annotate(n=Count('event_day__event', distinct=True))
    )
    ev_by_user = {r['user_id']: r['n'] for r in ev_counts}
    # Смены за сезон — по кэш-полю нет, считаем participations в текущем сезоне.
    current_season = Season.objects.filter(start_season__lte=timezone.now().date()).order_by('-start_season').first()
    season_shift_counts = {}
    if current_season:
        sq = Participation.objects.filter(
            user_id__in=user_ids, status='attended',
            event_day__day__gte=current_season.start_season,
        )
        if current_season.end_season:
            sq = sq.filter(event_day__day__lte=current_season.end_season)
        for r in sq.values('user_id').annotate(n=Count('id')):
            season_shift_counts[r['user_id']] = r['n']

    # Дата последней заявки по каждому пользователю.
    last_apps = (
        Application.objects.filter(user_id__in=user_ids)
        .values('user_id').annotate(last=Max('created_at'))
    )
    last_app_by_user = {r['user_id']: r['last'] for r in last_apps}

    for uid, m in metrics.items():
        a = agg[uid]
        days = sorted(a['days'])
        first_day = days[0] if days else None
        last_day = days[-1] if days else None
        m['shifts_total'] = a['shifts']
        m['shifts_season'] = season_shift_counts.get(uid, 0)
        m['events_attended'] = ev_by_user.get(uid, 0)
        m['avg_shift_hours'] = round(a['dur_sum'] / a['dur_n'], 1) if a['dur_n'] else 0
        # Среднее время на мероприятии (часы / число меро).
        m['avg_hours_per_event'] = round(m['hours_total'] / m['events_attended'], 1) if m['events_attended'] else 0
        m['first_event'] = _fmt_date(first_day)
        m['last_event'] = _fmt_date(last_day)
        m['days_with_us'] = _days_ago(first_day)  # с первого меро
        m['days_since_last_event'] = _days_ago(last_day)
        last_app = last_app_by_user.get(uid)
        m['last_application'] = _fmt_date(last_app.date() if last_app else None)
        m['days_since_last_app'] = _days_ago(last_app)
    return metrics


def volunteers_table(date_from=None, date_to=None, event_ids=None):
    """Таблица «Волонтёры» ERP-раздела: по каждому пришедшему в охват волонтёру —
    полная сводка (часы/сезон/всё время, меро, смены, средние, даты первого/последнего
    касания, churn). Метрики «за всё время» и по сезону — не ограничены охватом (это
    характеристика человека), а список волонтёров — те, кто пришёл в охват."""
    shifts = _shifts_in_scope(date_from, date_to, event_ids)
    scope_user_ids = list(
        Participation.objects.filter(event_day__in=shifts, status='attended')
        .values_list('user_id', flat=True).distinct()
    )
    metrics = _volunteer_activity_metrics(scope_user_ids)
    rows = list(metrics.values())
    rows.sort(key=lambda r: r['hours_total'], reverse=True)
    return rows


def events_table(date_from=None, date_to=None, event_ids=None):
    """Таблица «Мероприятия» ERP-раздела: по каждому меро охвата — название, статус,
    число смен, ПЕРЕЧИСЛЕНИЕ смен (каждая смена — отдельная колонка, чтобы таблица не
    ломалась под работу в Excel), плановая потребность, воронка заявок
    (подано/принято/отклонено/осталось), организация и организатор с контактами.

    Возвращает (rows, max_shifts) — max_shifts задаёт число динамических колонок смен
    (шаблон рисует «Смена 1..N»; у меро с меньшим числом смен лишние колонки пустые)."""
    events = (
        _events_in_scope(date_from, date_to, event_ids)
        .select_related('organization', 'organizer')
        .prefetch_related('shifts')
    )
    rows = []
    max_shifts = 0
    for event in events:
        shifts = sorted(event.shifts.all(), key=lambda s: (s.day, s.start_time))
        max_shifts = max(max_shifts, len(shifts))
        needed = sum(s.volunteer_needed or 0 for s in shifts)
        apps = Application.objects.filter(event=event)
        submitted = apps.count()
        approved = apps.filter(status='approved').count()
        rejected = apps.filter(status='rejected').count()
        remaining = apps.filter(status='new').count()  # ещё не обработанные
        org = event.organization
        organizer = event.organizer
        shift_cells = [
            f"{s.day.strftime('%d.%m.%Y')} {s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')}"
            + (f" ({s.volunteer_needed} чел.)" if s.volunteer_needed else '')
            for s in shifts
        ]
        rows.append({
            'id': event.id,
            'title': event.title,
            'status': event.compute_status(),
            'status_display': event.compute_status_display(),
            'shifts_count': len(shifts),
            'shift_cells': shift_cells,
            'needed': needed,
            'submitted': submitted,
            'approved': approved,
            'rejected': rejected,
            'remaining': remaining,
            'organization': org.name if org else '—',
            'organizer': f"{organizer.first_name} {organizer.last_name}" if organizer else '—',
            'organizer_tg': (organizer.telegram_username if organizer and organizer.telegram_username else '—'),
            'organizer_phone': (organizer.phone if organizer and organizer.phone else '—'),
        })
    rows.sort(key=lambda r: r['title'].lower())
    return rows, max_shifts


def _role_table(role, date_from, date_to, event_ids):
    """Общий построитель таблиц «Тим-лидеры» / «Менеджеры» (role = 'team_lead'|'manager').

    Список — те, кто в охвате был назначен на меро в этой роли (EventStaff). По каждому:
    ролевые метрики (меро в роли за сезон/всё время, дата назначения и «сколько с нами
    в роли», первое/последнее меро в роли и «сколько дней назад», сумма и среднее людей
    на его меро, обработано/принято/отклонено заявок на его меро) + волонтёрские метрики
    (те же, что в таблице волонтёров) — через _volunteer_activity_metrics."""
    from blog.models import EventStaff, Manager, TeamLeader
    from django.utils import timezone

    events = _events_in_scope(date_from, date_to, event_ids)
    # Пользователи, которые в охвате были в этой роли.
    staff_qs = EventStaff.objects.filter(staff_role=role, event__in=events).values_list('user_id', flat=True)
    user_ids = list(dict.fromkeys(staff_qs))  # уникальные, стабильный порядок
    if not user_ids:
        return []

    vol_metrics = _volunteer_activity_metrics(user_ids)
    role_model = TeamLeader if role == 'team_lead' else Manager

    # Дата назначения ролью (самая ранняя активная запись роли).
    assign_dates = {}
    for r in role_model.objects.filter(user_id__in=user_ids).values('user_id').annotate(first=Min('assigned_at')):
        assign_dates[r['user_id']] = r['first']

    # Все меро пользователя в этой роли (за всё время) — для первого/последнего меро в роли,
    # суммы/среднего людей на меро, дат.
    all_staff = (
        EventStaff.objects.filter(staff_role=role, user_id__in=user_ids)
        .select_related('event')
        .prefetch_related('event__shifts')
    )
    role_events = {uid: [] for uid in user_ids}
    for st in all_staff:
        role_events[st.user_id].append(st.event)

    # Заявки на меро пользователя-в-роли: обработано/принято/отклонено (по его меро в охвате).
    rows = []
    current_season = Season.objects.filter(start_season__lte=timezone.now().date()).order_by('-start_season').first()
    for uid in user_ids:
        m = dict(vol_metrics.get(uid, {'user_id': uid, 'name': f'#{uid}'}))
        revents = role_events[uid]
        # Даты меро в роли — по первой смене каждого меро.
        ev_days = []
        people_sum = 0
        for ev in revents:
            first_day = min((s.day for s in ev.shifts.all()), default=None)
            if first_day:
                ev_days.append(first_day)
            people_sum += Participation.objects.filter(event_day__event=ev, status='attended').count()
        ev_days.sort()
        m['role_events_total'] = len(revents)
        # Меро в роли за сезон.
        season_n = 0
        if current_season and ev_days:
            for d in ev_days:
                if d >= current_season.start_season and (not current_season.end_season or d <= current_season.end_season):
                    season_n += 1
        m['role_events_season'] = season_n
        assigned = assign_dates.get(uid)
        m['role_assigned_at'] = _fmt_date(assigned.date() if assigned else None)
        m['role_days_since_assigned'] = _days_ago(assigned)
        m['role_first_event'] = _fmt_date(ev_days[0] if ev_days else None)
        m['role_last_event'] = _fmt_date(ev_days[-1] if ev_days else None)
        m['role_days_since_first'] = _days_ago(ev_days[0]) if ev_days else None
        m['role_days_since_last'] = _days_ago(ev_days[-1]) if ev_days else None
        m['role_people_total'] = people_sum
        m['role_people_avg'] = round(people_sum / len(revents), 1) if revents else 0
        # Заявки на его меро (в роли, за всё время его меро).
        his_events = [ev.id for ev in revents]
        his_apps = Application.objects.filter(event_id__in=his_events)
        m['role_apps_processed'] = his_apps.filter(assigned_at__isnull=False).count()
        m['role_apps_approved'] = his_apps.filter(status='approved').count()
        m['role_apps_rejected'] = his_apps.filter(status='rejected').count()
        rows.append(m)
    rows.sort(key=lambda r: r.get('role_events_total', 0), reverse=True)
    return rows


def team_leaders_table(date_from=None, date_to=None, event_ids=None):
    return _role_table('team_lead', date_from, date_to, event_ids)


def managers_table(date_from=None, date_to=None, event_ids=None):
    return _role_table('manager', date_from, date_to, event_ids)


# Место появления заявки в системе — по служебному telegram_id (веб/бот) или import:* id.
def _application_source(app):
    """Откуда заявка: 'Бот' / 'Веб' / 'Excel-выгрузка'. Excel-импорт создаёт заявки с
    привязкой к пользователю со служебным telegram_id вида 'import:*'; заявки без user
    или с submitted_at, но без telegram — веб/бот различаем по наличию telegram_username."""
    user = app.user
    if user and (user.telegram_id or '').startswith('import:'):
        return 'Excel-выгрузка'
    # Заявка, поданная через бот, имеет telegram_username и реальный telegram_id.
    if user and (user.telegram_id or '').isdigit():
        return 'Бот' if app.telegram_username else 'Веб'
    # Резерв: по наличию telegram_username в самой заявке.
    return 'Бот' if app.telegram_username else 'Веб'


def applications_table(date_from=None, date_to=None, event_ids=None):
    """Таблица «Заявки» ERP-раздела: все заявки мероприятий охвата (перенос из БД) +
    производные поля: кто обработал, когда, сколько прошло между подачей и обработкой,
    место появления в системе (бот/веб/Excel-выгрузка)."""
    events = _events_in_scope(date_from, date_to, event_ids)
    apps = (
        Application.objects.filter(event__in=events)
        .select_related('event', 'user', 'assigned_by')
        .order_by('-created_at')
    )
    rows = []
    for app in apps:
        name = f"{app.last_name or ''} {app.first_name or ''} {app.middle_name or ''}".strip() or '—'
        wait_hours = None
        if app.assigned_at and app.created_at:
            wait_hours = round((app.assigned_at - app.created_at).total_seconds() / 3600, 1)
        rows.append({
            'id': app.id,
            'name': name,
            'telegram': app.telegram_username or '—',
            'phone': app.phone or '—',
            'event': app.event.title,
            'event_id': app.event_id,
            'functions': app.functions or '—',
            'role': app.role_in_event or '—',
            'status': app.get_status_display(),
            'status_key': app.status,
            'source': _application_source(app),
            'submitted_at': _fmt_dt_local(app.submitted_at or app.created_at),
            'assigned_by': app.assigned_by.full_name if app.assigned_by else '—',
            'assigned_at': _fmt_dt_local(app.assigned_at),
            'wait_hours': wait_hours if wait_hours is not None else '—',
        })
    return rows


def _fmt_dt_local(value):
    if not value:
        return '—'
    return value.strftime('%d.%m.%Y %H:%M')


def staff_load(date_from=None, date_to=None, event_ids=None):
    """Нагрузка персонала: меро/заявки на менеджера и тим-лидера за охват —
    обработка заявок считается и для менеджеров, и для тим-лидеров (reports.md).
    Используется генератором Excel-экспорта (лист «Персонал» не показывается на экране)."""
    from blog.models import EventStaff

    events = _events_in_scope(date_from, date_to, event_ids)
    apps_scope = Application.objects.filter(event__in=events)

    processed_apps = list(
        apps_scope.filter(assigned_by__isnull=False, assigned_at__isnull=False)
        .values('assigned_by__id', 'created_at', 'assigned_at')
    )
    processing_by_user = {}
    for app in processed_apps:
        uid = app['assigned_by__id']
        seconds = (app['assigned_at'] - app['created_at']).total_seconds()
        processing_by_user.setdefault(uid, []).append(seconds)

    counts_by_user = {}
    for app in apps_scope.filter(assigned_by__isnull=False).values('assigned_by__id'):
        counts_by_user[app['assigned_by__id']] = counts_by_user.get(app['assigned_by__id'], 0) + 1

    def _staff_with_apps(role):
        staff = list(
            EventStaff.objects.filter(staff_role=role, event__in=events)
            .values('user__id', 'user__first_name', 'user__last_name')
            .annotate(event_count=Count('event', distinct=True))
        )
        for row in staff:
            uid = row['user__id']
            row['applications_processed'] = counts_by_user.get(uid, 0)
            durations = processing_by_user.get(uid)
            row['avg_processing_hours'] = round(sum(durations) / len(durations) / 3600, 1) if durations else None
            row['name'] = f"{row['user__first_name'] or ''} {row['user__last_name'] or ''}".strip() or '—'
        return staff

    managers = _staff_with_apps('manager')
    team_leads = _staff_with_apps('team_lead')

    apps_by_manager = list(
        apps_scope.filter(assigned_by__isnull=False)
        .values('assigned_by__id', 'assigned_by__first_name', 'assigned_by__last_name')
        .annotate(processed=Count('id'))
    )
    return {'managers': managers, 'team_leads': team_leads, 'applications_processed': apps_by_manager}


def application_timing(date_from=None, date_to=None, event_ids=None, bucket_hours=(1, 6, 24, 72)):
    """Тайминг заявок относительно публикации меро — reports_template.md §1B блок 8.

    Для каждого мероприятия «ноль» — самое раннее из post_published_at / published_at.
    Возвращает кумулятивную кривую заявок по времени от нуля и гистограмму плотности
    по бакетам фиксированного шага."""
    events = _events_in_scope(date_from, date_to, event_ids).filter(
        Q(published_at__isnull=False) | Q(post_published_at__isnull=False)
    )

    points = []  # (event_id, hours_since_zero)
    per_event_zero = {}
    for event in events:
        candidates = [t for t in (event.published_at, event.post_published_at) if t]
        if not candidates:
            continue
        zero = min(candidates)
        per_event_zero[event.id] = {
            'zero': zero,
            'post_offset_h': (event.post_published_at - zero).total_seconds() / 3600 if event.post_published_at else None,
            'announce_offset_h': (event.published_at - zero).total_seconds() / 3600 if event.published_at else None,
            'zero_is': 'post' if event.post_published_at == zero else 'announce',
        }

    apps = Application.objects.filter(event_id__in=per_event_zero.keys(), submitted_at__isnull=False)
    for app in apps:
        zero = per_event_zero[app.event_id]['zero']
        delta_h = (app.submitted_at - zero).total_seconds() / 3600
        if delta_h >= 0:
            points.append(delta_h)

    points.sort()
    cumulative = []
    for i, h in enumerate(points, start=1):
        cumulative.append({'hours': round(h, 1), 'count': i})

    bucket_edges = [0, *bucket_hours, math.inf]
    density = []
    for i in range(len(bucket_edges) - 1):
        low, high = bucket_edges[i], bucket_edges[i + 1]
        count = sum(1 for h in points if low <= h < high)
        label = f'{low:g}–{high:g}ч' if high != math.inf else f'>{low:g}ч'
        density.append({'label': label, 'count': count})

    return {
        'events': per_event_zero,
        'cumulative': cumulative,
        'density': density,
        'total_applications': len(points),
    }


def post_publication_timing(date_from=None, date_to=None, event_ids=None):
    """Время публикации постов по часам суток / дням недели (reports.md, график)."""
    events = _events_in_scope(date_from, date_to, event_ids).filter(post_published_at__isnull=False)
    by_hour = [0] * 24
    by_weekday = [0] * 7  # 0 = понедельник
    for event in events.values_list('post_published_at', flat=True):
        by_hour[event.hour] += 1
        by_weekday[event.weekday()] += 1
    return {'by_hour': by_hour, 'by_weekday': by_weekday}
