"""Сервисы бота: домен «events». Часть пакета tg_bot.services (см. README.md).

Мероприятия для бота: список открытых, смены, меро тим-лидера, публикация
и рассылка из бота.

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403
from .users import get_user


def open_events(limit: int = 7, user_id: int = None) -> list:
    """Ближайшие опубликованные мероприятия с открытым набором (tg-bot.md §4.1).

    Если передан `user_id`, к каждому меро добавляется инфо об АКТИВНОЙ заявке этого
    пользователя (`my_application_id`, `my_application_status`) — чтобы в списке вместо
    кнопки «Подать заявку» показать статус уже поданной заявки (db.md правило 7d)."""
    close_old_connections()
    today = timezone.localdate()
    events = dc.get_open_events()

    my_apps = {}
    if user_id:
        for app in dc.applications_qs().filter(
            user_id=user_id, status__in=['new', 'approved'],
            event__in=[e.id for e in events],
        ):
            # На одно меро может быть несколько активных заявок — берём последнюю.
            my_apps[app.event_id] = app

    result = []
    for event in events:
        days = sorted(s.day for s in event.shifts.all())
        first_day = next((d for d in days if d >= today), days[0] if days else None)
        my_app = my_apps.get(event.id)
        result.append({
            'id': event.id,
            'title': event.title,
            'description': (event.description or '')[:200],
            'location': event.location.name if event.location else None,
            'first_day': first_day,
            'my_application_id': my_app.id if my_app else None,
            'my_application_status': my_app.get_status_display() if my_app else None,
        })
    result.sort(key=lambda e: (e['first_day'] is None, e['first_day']))
    return result[:limit]

def event_open_shifts(event_id: int) -> list:
    """Смены меро с открытым набором (для экрана выбора смен, tg-bot.md §4.2)."""
    close_old_connections()
    event = dc.get_event_by_id(event_id)
    if not event:
        return []
    return list(event.shifts.filter(recruit_status='open').order_by('day', 'start_time'))

def team_leader_events(user_id: int) -> list:
    """Мероприятия, где пользователь назначен тим-лидером, с числом новых заявок."""
    close_old_connections()
    assignments = dc.get_event_staff(user_id=user_id)
    result = []
    for a in assignments:
        if a.staff_role != 'team_lead':
            continue
        new_count = len(dc.get_applications(status_filter='new', event_id=a.event_id))
        result.append({'id': a.event.id, 'title': a.event.title, 'new_applications': new_count})
    return result

def active_events_with_organizers(user_id: int):
    """Активные мероприятия с контактами организатора (tg-bot.md §6.2) — только менеджер."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.has_manager_access(user):
        return None, 'forbidden'
    return dc.get_active_events(), None

def unpublished_events(user_id: int):
    """Меро, сформированные на сайте, но не опубликованные (bot-update.md §2.4.C) —
    только менеджер."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.has_manager_access(user):
        return None, 'forbidden'
    return dc.get_unpublished_events(), None

def publish_event_from_bot(user_id: int, event_id: int):
    """Публикация меро из бота (bot-update.md §2.4.C) — зеркалит `blog.views.event_publish`:
    открывает подачу заявок, рассылку НЕ делает (отдельная кнопка). Возвращает
    (event|None, код_ошибки|None)."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.has_manager_access(user):
        return None, 'forbidden'
    event = dc.get_event_by_id(event_id)
    if not event:
        return None, 'not_found'
    if event.published_at:
        return None, 'already_published'
    if event.event_status == 'finished':
        return None, 'finished'
    dc.publish_event(event)
    logger.info('Мероприятие опубликовано из бота: event=%s by=%s', event.id, actor(user))
    return event, None

def broadcastable_events(user_id: int):
    """Активные (опубликованные, не завершённые) меро — кандидаты для рассылки
    (bot-update.md §2.4.D), с датой последней рассылки — только менеджер."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.has_manager_access(user):
        return None, 'forbidden'
    return dc.get_broadcastable_events(), None

def broadcast_event_from_bot(user_id: int, event_id: int):
    """Рассылка по меро из бота (bot-update.md §2.4.D) — зеркалит `blog.views.event_broadcast`:
    рассылка всем подписанным волонтёрам, `broadcast_sent_at` проставляется только при
    первой рассылке. Возвращает (число адресатов|None, была_ли_рассылка_раньше, код_ошибки|None)."""
    close_old_connections()
    from blog.services.notifications import broadcast_new_event

    user = get_user(user_id)
    if not roles_service.has_manager_access(user):
        return None, None, 'forbidden'
    event = dc.get_event_by_id(event_id)
    if not event:
        return None, None, 'not_found'
    if not event.published_at:
        return None, None, 'not_published'
    if event.event_status == 'finished':
        return None, None, 'finished'

    was_sent_before = event.broadcast_sent_at is not None
    sent = broadcast_new_event(event)
    if not was_sent_before:
        dc.mark_event_broadcast_sent(event)
    logger.info(
        'Рассылка по меро из бота: event=%s адресатов=%s повторная=%s by=%s',
        event.id, sent, was_sent_before, actor(user),
    )
    return sent, was_sent_before, None
