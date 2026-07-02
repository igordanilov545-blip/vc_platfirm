"""Сервис-слой бота: синхронные функции над Django ORM.

Хендлеры aiogram (async) вызывают их через `asgiref.sync.sync_to_async`.
Вся бизнес-логика — здесь, хендлеры только разговаривают с пользователем.
"""
import re

from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.utils import timezone

from blog.models import Application, BotOutbox, Event, User
from blog.services.notifications import notify_application_submitted
from blog.services.stats import is_pgas_star


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------

def get_or_create_user(telegram_id: int, telegram_username: str = None):
    """Идентификация по telegram_id (architecture.md 2.1). Возвращает (user, created)."""
    close_old_connections()
    user, created = User.objects.get_or_create(
        telegram_id=str(telegram_id),
        defaults={'telegram_username': telegram_username},
    )
    if not created and telegram_username and user.telegram_username != telegram_username:
        user.telegram_username = telegram_username
        user.save(update_fields=['telegram_username'])
    return user, created


def update_profile(user_id: int, first_name: str = None, last_name: str = None, phone: str = None):
    close_old_connections()
    user = User.objects.get(pk=user_id)
    update_fields = []
    if first_name:
        user.first_name = first_name.strip()[:100]
        update_fields.append('first_name')
    if last_name:
        user.last_name = last_name.strip()[:100]
        update_fields.append('last_name')
    if phone:
        user.phone = phone.strip()[:20]
        update_fields.append('phone')
    if update_fields:
        user.save(update_fields=update_fields)
    return user


def refresh(user_id: int) -> User:
    close_old_connections()
    return User.objects.get(pk=user_id)


def toggle_subscription(user_id: int) -> bool:
    """Переключает подписку на уведомления о новых меро. Возвращает новое значение."""
    close_old_connections()
    user = User.objects.get(pk=user_id)
    user.notify_new_events = not user.notify_new_events
    user.save(update_fields=['notify_new_events'])
    return user.notify_new_events


# ---------------------------------------------------------------------------
# Веб-доступ (architecture.md 2.1–2.2)
# ---------------------------------------------------------------------------

LOGIN_RE = re.compile(r'^[a-zA-Z0-9_.-]{3,50}$')


def validate_login(login: str, user_id: int):
    """None, если логин свободен и валиден; иначе — текст ошибки."""
    close_old_connections()
    login = login.strip()
    if not LOGIN_RE.match(login):
        return 'Логин: 3–50 символов, латиница, цифры, точки, дефисы и подчёркивания.'
    if User.objects.filter(login__iexact=login).exclude(pk=user_id).exists():
        return 'Этот логин уже занят, попробуйте другой.'
    return None


def set_web_credentials(user_id: int, login: str, password: str):
    """Первичная установка или сброс веб-кредов + инвалидация активных веб-сессий."""
    close_old_connections()
    user = User.objects.get(pk=user_id)
    user.login = login.strip()
    user.set_password(password)
    user.web_credentials_set_at = timezone.now()
    user.save(update_fields=['login', 'password', 'web_credentials_set_at'])

    # Инвалидация активных веб-сессий пользователя (architecture.md 2.2).
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.get_decoded().get('_auth_user_id') == str(user.id):
            session.delete()
    return user


# ---------------------------------------------------------------------------
# Статистика и мероприятия
# ---------------------------------------------------------------------------

def user_stats(user_id: int) -> dict:
    close_old_connections()
    user = User.objects.get(pk=user_id)
    return {
        'total_hours': user.total_hours,
        'season_hours': user.season_hours,
        'total_events': user.total_event_count,
        'season_events': user.season_event_count,
        'is_star': is_pgas_star(user),
        'status': user.get_status_display(),
        'blacklisted': user.status == 'blacklisted',
    }


def open_events(limit: int = 7) -> list:
    """Ближайшие опубликованные мероприятия с открытым набором."""
    close_old_connections()
    today = timezone.now().date()
    events = (
        Event.objects.filter(
            recruit_status='open',
            event_status__in=['upcoming', 'ongoing'],
            published_at__isnull=False,
        )
        .select_related('location')
        .prefetch_related('days')
        .order_by('created_at')
    )
    result = []
    for event in events:
        days = sorted(d.day for d in event.days.all())
        first_day = next((d for d in days if d >= today), days[0] if days else None)
        result.append({
            'id': event.id,
            'title': event.title,
            'description': (event.description or '')[:200],
            'location': event.location.name if event.location else None,
            'first_day': first_day,
        })
    result.sort(key=lambda e: (e['first_day'] is None, e['first_day']))
    return result[:limit]


def apply_to_event(user_id: int, event_id: int):
    """Подача заявки из бота. Возвращает (application|None, текст ошибки|None)."""
    close_old_connections()
    user = User.objects.get(pk=user_id)
    event = Event.objects.filter(pk=event_id).first()
    if not event:
        return None, 'Мероприятие не найдено.'
    if event.recruit_status != 'open':
        return None, 'Набор на это мероприятие уже закрыт.'
    if user.status == 'blacklisted':
        return None, 'Ваш аккаунт заблокирован — обратитесь к менеджеру центра.'
    existing = Application.objects.filter(
        user=user, event=event, status__in=['new', 'approved']
    ).first()
    if existing:
        return None, 'У вас уже есть активная заявка на это мероприятие.'
    if not user.first_name:
        return None, 'need_profile'

    # Заявка через бота: submitted_at = created_at (implementation-plan Этап 4.2).
    application = Application.objects.create(
        event=event,
        user=user,
        first_name=user.first_name or '',
        last_name=user.last_name,
        telegram_username=user.telegram_username,
        phone=user.phone,
        submitted_at=timezone.now(),
        status='new',
    )
    notify_application_submitted(application)
    return application, None


def my_applications(user_id: int, limit: int = 10) -> list:
    close_old_connections()
    apps = (
        Application.objects.filter(user_id=user_id)
        .select_related('event')
        .order_by('-created_at')[:limit]
    )
    return [
        {
            'event_title': a.event.title,
            'status': a.status,
            'status_display': a.get_status_display(),
            'created_at': a.created_at,
        }
        for a in apps
    ]


def my_letters(user_id: int) -> list:
    """Мероприятия, за которые волонтёру доступно благодарственное письмо."""
    close_old_connections()
    events = (
        Event.objects.filter(
            days__participations__user_id=user_id,
            days__participations__status='attended',
            letter__isnull=False,
        )
        .distinct()
        .order_by('-created_at')
    )
    return [{'id': e.id, 'title': e.title} for e in events]


# ---------------------------------------------------------------------------
# Очередь исходящих (диспетчер уведомлений)
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 5


def fetch_pending_outbox(batch: int = 20) -> list:
    close_old_connections()
    return list(
        BotOutbox.objects.filter(status='pending', attempts__lt=MAX_ATTEMPTS)
        .order_by('created_at')[:batch]
    )


def mark_outbox_sent(outbox_id: int):
    close_old_connections()
    BotOutbox.objects.filter(pk=outbox_id).update(
        status='sent', sent_at=timezone.now()
    )


def mark_outbox_failed(outbox_id: int, error: str):
    close_old_connections()
    item = BotOutbox.objects.filter(pk=outbox_id).first()
    if not item:
        return
    item.attempts += 1
    item.last_error = str(error)[:1000]
    if item.attempts >= MAX_ATTEMPTS:
        item.status = 'failed'
    item.save(update_fields=['attempts', 'last_error', 'status'])
