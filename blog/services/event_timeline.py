"""Таймлайн «Жизнь мероприятия» (reports_template.md): данные для графика —
засечки ключевых событий меро + подачи заявок точками с кластеризацией.
Используется в отчёте по мероприятию и переиспользуется в комплексном отчёте
(часть 2 — мероприятия периода подряд).
"""
from data_base import data_controller as dc


STATUS_COLOR = {
    'new': '#d4a017',
    'approved': '#2f9e6b',
    'rejected': '#9aa4b2',
    'cancelled': '#c9503f',
}


def event_timeline_data(event) -> dict:
    """Возвращает засечки событий и точки заявок в часах от `events.created_at` —
    формат, который принимает `blog.services.charts.event_timeline_chart`."""
    zero = event.created_at
    milestones = [(_stamp('Создание', zero), 0.0, '#9aa4b2')]

    if event.published_at:
        milestones.append((_stamp('Публикация', event.published_at), _hours_since(zero, event.published_at), '#2f6bff'))
    if event.post_published_at:
        milestones.append((_stamp('Пост в канале', event.post_published_at), _hours_since(zero, event.post_published_at), '#5b8cff'))
    if event.broadcast_sent_at:
        milestones.append((_stamp('Рассылка', event.broadcast_sent_at), _hours_since(zero, event.broadcast_sent_at), '#d4a017'))

    for shift in event.shifts.all().order_by('day'):
        attended_count = dc.participations_qs().filter(event_day=shift, status='attended').count()
        needed = shift.volunteer_needed or 0
        label = f'День {shift.day.strftime("%d.%m.%Y")} {_time_range(shift)} (было {attended_count}/{needed})'
        milestones.append((label, _hours_since(zero, shift.start_time), '#2f9e6b'))

    if event.event_status == 'finished':
        # Момент завершения точно не хранится — используем последнюю смену как приближение.
        last_shift = event.shifts.order_by('-day').first()
        if last_shift:
            milestones.append((_stamp('Закрытие на платформе', last_shift.end_time), _hours_since(zero, last_shift.end_time), '#1d6b47'))

    dobro_logged_at = (
        dc.participations_qs().filter(event_day__event=event, dobro_ru_logged=True, dobro_ru_logged_at__isnull=False)
        .order_by('dobro_ru_logged_at').values_list('dobro_ru_logged_at', flat=True).first()
    )
    if dobro_logged_at:
        milestones.append((_stamp('Часы на Добро.ру', dobro_logged_at), _hours_since(zero, dobro_logged_at), '#8e5bd6'))

    applications_points = []
    for app in dc.applications_qs().filter(event=event):
        moment = app.submitted_at or app.created_at
        if not moment:
            continue
        color = STATUS_COLOR.get(app.status, '#9aa4b2')
        applications_points.append((_hours_since(zero, moment), color))

    return {'milestones': milestones, 'applications': applications_points}


def _hours_since(zero, moment) -> float:
    return max(0.0, (moment - zero).total_seconds() / 3600)


def _stamp(label, moment) -> str:
    """Подпись засечки с датой и временем: «Публикация 12.05.2026 14:30»."""
    if moment is None:
        return label
    try:
        return f'{label} {moment.strftime("%d.%m.%Y %H:%M")}'
    except (AttributeError, ValueError):
        return label


def _time_range(shift) -> str:
    """Интервал смены «14:30–18:00» из start_time/end_time (datetime или time)."""
    def _hm(value):
        try:
            return value.strftime('%H:%M')
        except (AttributeError, ValueError):
            return ''
    start, end = _hm(shift.start_time), _hm(shift.end_time)
    if start and end:
        return f'{start}–{end}'
    return start or end
