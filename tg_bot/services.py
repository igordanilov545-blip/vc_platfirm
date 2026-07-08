"""Сервис-слой бота: синхронные функции над `data_base.data_controller`.

Хендлеры aiogram (async) вызывают их через `asgiref.sync.sync_to_async`.
Вся бизнес-логика — здесь, хендлеры только разговаривают с пользователем.
Работа с БД идёт исключительно через `data_controller` (tg-bot.md §9), не через
прямые ORM-запросы из этого файла.
"""
import re
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.utils import timezone

from data_base import data_controller as dc
from blog.models import BotOutbox
from blog.services import roles as roles_service
from blog.services.applications import process_application
from blog.services.notifications import notify_application_submitted
from blog.services.stats import is_pgas_star


# ---------------------------------------------------------------------------
# Пользователи: первое касание, регистрация, профиль
# ---------------------------------------------------------------------------

def get_or_create_user(telegram_id: int, telegram_username: str = None):
    """Первое касание (tg-bot.md §3.1) — не регистрация. Возвращает (user, created)."""
    close_old_connections()
    return dc.get_or_create_user_by_telegram_id(telegram_id, telegram_username)


def get_user(user_id: int):
    close_old_connections()
    from blog.models import User
    return User.objects.get(pk=user_id)


def is_guest(user) -> bool:
    return user.registration_status != 'registered'


def complete_registration(user_id: int, first_name: str, last_name: str = None, phone: str = None):
    """Завершает регистрацию (tg-bot.md §3.2): имя обязательно, телефон опционален."""
    close_old_connections()
    user = get_user(user_id)
    fields = {
        'first_name': first_name.strip()[:100],
        'registration_status': 'registered',
    }
    if last_name:
        fields['last_name'] = last_name.strip()[:100]
    if phone:
        fields['phone'] = phone.strip()[:20]
    return dc.update_user_fields(user, **fields)


def update_profile(user_id: int, first_name: str = None, last_name: str = None, phone: str = None):
    close_old_connections()
    user = get_user(user_id)
    fields = {}
    if first_name:
        fields['first_name'] = first_name.strip()[:100]
    if last_name:
        fields['last_name'] = last_name.strip()[:100]
    if phone:
        fields['phone'] = phone.strip()[:20]
    return dc.update_user_fields(user, **fields) if fields else user


def toggle_subscription(user_id: int) -> bool:
    """Переключает подписку на уведомления о новых меро. Возвращает новое значение."""
    close_old_connections()
    user = get_user(user_id)
    new_value = not user.notify_new_events
    dc.update_user_fields(user, notify_new_events=new_value)
    return new_value


def toggle_application_notifications(user_id: int) -> bool:
    """Переключает тумблер уведомлений о новых заявках (`notify_applications`,
    db.md правило 7c) для ТЛ/менеджера. Возвращает новое значение. При False карточки
    новых заявок этому пользователю не приходят (см. `notify_event_staff`), но сами
    заявки остаются видны в разделах меро / «Все заявки»."""
    close_old_connections()
    user = get_user(user_id)
    new_value = not user.notify_applications
    dc.update_user_fields(user, notify_applications=new_value)
    return new_value


def issue_web_login_link(user_id: int) -> str:
    """Одноразовая ссылка входа в веб через бота (deep-link `?start=weblogin`).
    Возвращает абсолютный URL `/auth/tg/<token>/`, действующий 5 минут."""
    close_old_connections()
    from django.conf import settings
    from blog.services.web_auth import issue_auth_token

    user = get_user(user_id)
    token = issue_auth_token(user)
    base = (settings.WEBAPP_URL or '').rstrip('/')
    return f'{base}/auth/tg/{token.token}/'


def user_role_label(user) -> str:
    """Роль называем пользователю (не путать с внутренним `status`, см. tg-bot.md §2)."""
    return roles_service.role_label(user)


def user_is_team_leader(user) -> bool:
    return roles_service.is_team_leader(user)


def user_is_manager(user) -> bool:
    return roles_service.is_manager(user)


# ---------------------------------------------------------------------------
# Веб-доступ (architecture.md 2.1–2.2)
# ---------------------------------------------------------------------------

LOGIN_RE = re.compile(r'^[a-zA-Z0-9_.-]{3,50}$')


def validate_login(login: str, user_id: int):
    """None, если логин свободен и валиден; иначе — текст ошибки."""
    close_old_connections()
    from blog.models import User
    login = login.strip()
    if not LOGIN_RE.match(login):
        return 'Логин: 3–50 символов, латиница, цифры, точки, дефисы и подчёркивания.'
    if User.objects.filter(login__iexact=login).exclude(pk=user_id).exists():
        return 'Этот логин уже занят, попробуйте другой.'
    return None


def set_web_credentials(user_id: int, login: str, password: str):
    """Первичная установка или сброс веб-кредов + инвалидация активных веб-сессий."""
    close_old_connections()
    user = get_user(user_id)
    user.login = login.strip()
    user.set_password(password)
    user.web_credentials_set_at = timezone.now()
    user.save(update_fields=['login', 'password', 'web_credentials_set_at'])

    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.get_decoded().get('_auth_user_id') == str(user.id):
            session.delete()
    return user


# ---------------------------------------------------------------------------
# Статистика и мероприятия (волонтёр)
# ---------------------------------------------------------------------------

def user_stats(user_id: int) -> dict:
    close_old_connections()
    user = get_user(user_id)
    return {
        'total_hours': user.total_hours,
        'season_hours': user.season_hours,
        'total_events': user.total_event_count,
        'season_events': user.season_event_count,
        'is_star': is_pgas_star(user),
        'blacklisted': user.status == 'blacklisted',
    }


def open_events(limit: int = 7) -> list:
    """Ближайшие опубликованные мероприятия с открытым набором (tg-bot.md §4.1)."""
    close_old_connections()
    today = timezone.now().date()
    events = dc.get_open_events()
    result = []
    for event in events:
        days = sorted(s.day for s in event.shifts.all())
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
    """Подача заявки из бота (tg-bot.md §4.2–4.3). Каждый вызов — независимая заявка
    на конкретное меро; несколько заявок на разные меро подаются отдельными вызовами.
    Возвращает (application|None, код ошибки|None). При `already_applied` объект
    существующей заявки кладётся в `application`, чтобы хендлер мог сразу предложить
    посмотреть/изменить/отменить её (db.md правило 7d), не делая второй запрос."""
    close_old_connections()
    user = get_user(user_id)
    event = next((e for e in dc.get_events() if e.id == event_id), None)
    if not event:
        return None, 'not_found'
    if not event.shifts.filter(recruit_status='open').exists():
        return None, 'closed'
    if user.status == 'blacklisted':
        return None, 'blacklisted'
    if is_guest(user):
        return None, 'need_registration'
    existing = dc.get_user_application_for_event(user_id, event_id)
    if existing:
        return existing, 'already_applied'

    application = dc.create_application(
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


def my_active_applications(user_id: int) -> list:
    """Только активные заявки волонтёра на ещё актуальные меро (new/approved,
    tg-bot.md §4.4) — заявки на уже прошедшие мероприятия сюда не попадают
    (фильтр внутри `get_user_active_applications`)."""
    close_old_connections()
    apps = dc.get_user_active_applications(user_id)
    return [
        {
            'id': a.id,
            'event_title': a.event.title,
            'status': a.status,
            'status_display': a.get_status_display(),
            'created_at': a.created_at,
        }
        for a in apps
    ]


def get_own_application(user_id: int, application_id: int):
    """Заявка пользователя по id, только если она принадлежит ему — используется в
    хендлерах редактирования/отмены (tg-bot.md §4.3.2–4.3.3), чтобы не дать подделать
    callback_data и подействовать на чужую заявку."""
    close_old_connections()
    from blog.models import Application
    return Application.objects.select_related('event').filter(
        pk=application_id, user_id=user_id
    ).first()


def application_cancel_eligibility(user_id: int, application_id: int):
    """(можно_отменить, причина_отказа|None, late_cancel_hours) — обёртка над общим
    правилом `blog.services.applications.can_cancel_application` с проверкой владения."""
    from blog.services.applications import can_cancel_application
    close_old_connections()
    application = get_own_application(user_id, application_id)
    if not application:
        return False, 'not_found', None
    return can_cancel_application(application)


def cancel_own_application(user_id: int, application_id: int, reason: str):
    """Отмена своей заявки с обязательной причиной (tg-bot.md §4.3.3). Возвращает
    (application|None, код_ошибки|None). Права/срок повторно проверяются здесь —
    хендлер не должен полагаться только на состояние экрана, вызванное раньше."""
    from blog.services.applications import can_cancel_application, cancel_application
    close_old_connections()
    application = get_own_application(user_id, application_id)
    if not application:
        return None, 'not_found'
    can_cancel, reason_code, _ = can_cancel_application(application)
    if not can_cancel:
        return None, reason_code
    cancel_application(application, reason)
    return application, None


def edit_own_application(user_id: int, application_id: int, functions: str = None, role_in_event: str = None):
    """Изменение данных активной заявки (tg-bot.md §4.3.2, db.md правило 7d): создаёт
    НОВУЮ запись `applications` с обновлёнными функцией/ролью и статусом `new` — старая
    заявка остаётся в истории без изменений (дубли разрешены, см. правило 3). Возвращает
    (новая_заявка|None, код_ошибки|None)."""
    close_old_connections()
    old = get_own_application(user_id, application_id)
    if not old or old.status not in ('new', 'approved'):
        return None, 'not_found'
    user = get_user(user_id)

    new_application = dc.create_application(
        event=old.event,
        user=user,
        first_name=old.first_name,
        last_name=old.last_name,
        telegram_username=old.telegram_username,
        phone=old.phone,
        functions=functions if functions is not None else old.functions,
        role_in_event=role_in_event if role_in_event is not None else old.role_in_event,
        submitted_at=timezone.now(),
        status='new',
    )
    notify_application_submitted(new_application)
    return new_application, None


def submit_feedback(user_id: int, event_id: int, rating: int, comment: str = None):
    """Оценка мероприятия после участия (tg-bot.md §4.6)."""
    close_old_connections()
    user = get_user(user_id)
    event = next((e for e in dc.get_events() if e.id == event_id), None)
    if not event:
        return None, 'not_found'
    if dc.has_feedback(user_id, event_id):
        return None, 'already_rated'
    feedback = dc.create_feedback(author=user, event=event, rating=rating, comment=comment)
    return feedback, None


# ---------------------------------------------------------------------------
# Функции тим-лидера (контекстные — только свои мероприятия)
# ---------------------------------------------------------------------------

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


def event_pending_applications(user_id: int, event_id: int):
    """Заявки на рассмотрении по конкретному меро — с проверкой контекстных прав."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.can_process_applications(user, event_id):
        return None, 'forbidden'
    apps = dc.get_applications(status_filter='new', event_id=event_id)
    return apps, None


def process_application_decision(user_id: int, application_id: int, approve: bool):
    """Одобрить/резерв заявки (tg-bot.md §5.2). Права: ТЛ — свои меро, менеджер — все."""
    close_old_connections()
    from blog.models import Application
    user = get_user(user_id)
    application = Application.objects.select_related('event').filter(pk=application_id).first()
    if not application:
        return None, 'not_found'
    if not roles_service.can_process_applications(user, application.event_id):
        return None, 'forbidden'

    new_status = 'approved' if approve else 'rejected'
    process_application(application, new_status, processed_by=user)
    return application, None


def process_all_applications(user_id: int, event_id: int):
    """Одобрить все заявки на рассмотрении по меро одним действием (tg-bot.md §5.2, TL4).
    Права те же, что и для одиночного решения. Возвращает (список одобренных заявок, ошибка)."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.can_process_applications(user, event_id):
        return None, 'forbidden'
    apps = dc.get_applications(status_filter='new', event_id=event_id)
    approved = []
    for application in apps:
        process_application(application, 'approved', processed_by=user)
        approved.append(application)
    return approved, None


def event_participants_for_attendance(user_id: int, event_id: int):
    """Список участников меро для простановки явки (tg-bot.md §5.3)."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.can_process_applications(user, event_id):
        return None, 'forbidden'
    participations = dc.get_participations(event_id=event_id)
    return participations, None


def set_attendance(user_id: int, participation_id: int, status: str, hours: int = None):
    """Проставляет явку и пересчитывает агрегаты/churn волонтёра (tg-bot.md §5.3)."""
    close_old_connections()
    from blog.models import Participation
    from blog.services.stats import recalc_user_aggregates, apply_churn_no_show, apply_churn_activity_decay

    user = get_user(user_id)
    participation = Participation.objects.select_related('event_day__event', 'user').filter(pk=participation_id).first()
    if not participation:
        return None, 'not_found'
    event_id = participation.event_day.event_id
    if not roles_service.can_process_applications(user, event_id):
        return None, 'forbidden'

    dc.update_participation_status(participation, status, hours=hours)
    recalc_user_aggregates(participation.user)
    if status == 'absent_unexcused':
        apply_churn_no_show(participation.user)
    elif status == 'attended':
        apply_churn_activity_decay(participation.user)
    return participation, None


def add_user_comment(user_id: int, target_user_id: int, text: str, event_id: int = None):
    """Внутренний комментарий волонтёру (tg-bot.md §5.4) — только по контексту правила 5."""
    close_old_connections()
    from blog.models import User, Event
    author = get_user(user_id)
    target = User.objects.filter(pk=target_user_id).first()
    if not target:
        return None, 'not_found'
    if not roles_service.has_extended_access_to_profile(author, target):
        return None, 'forbidden'
    event = Event.objects.filter(pk=event_id).first() if event_id else None
    comment = dc.create_user_comment(target_user=target, author=author, text=text, event=event)
    return comment, None


# ---------------------------------------------------------------------------
# Функции менеджера
# ---------------------------------------------------------------------------

def all_applications(user_id: int, limit: int = 20):
    """Все заявки по всем мероприятиям (tg-bot.md §6.1) — только для менеджера."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.is_manager(user):
        return None, 'forbidden'
    apps = dc.get_applications()[:limit]
    return apps, None


def active_events_with_organizers(user_id: int):
    """Активные мероприятия с контактами организатора (tg-bot.md §6.2) — только менеджер."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.is_manager(user):
        return None, 'forbidden'
    return dc.get_active_events(), None


def pending_feedback_requests(delay_hours: float = 3.0) -> list:
    """Участники, кому пора отправить запрос на оценку мероприятия (tg-bot.md §4.6)."""
    close_old_connections()
    cutoff = timezone.now() - timedelta(hours=delay_hours)
    return dc.get_participations_pending_feedback(cutoff)


def mark_feedback_requested(participation_id: int):
    close_old_connections()
    from blog.models import Participation
    participation = Participation.objects.filter(pk=participation_id).first()
    if participation:
        dc.mark_feedback_requested(participation)


# ---------------------------------------------------------------------------
# Очередь исходящих (диспетчер уведомлений)
# ---------------------------------------------------------------------------

BUTTON_TTL_SECONDS = 300  # 5 минут — inline-кнопки "остывают" (tg-bot.md §0.2)


def schedule_button_removal(chat_id, message_id: int):
    """Ставит в очередь снятие inline-клавиатуры сообщения через `BUTTON_TTL_SECONDS`.
    Вызывается сразу после отправки любого сообщения с inline-кнопками, срок жизни
    которых ограничен (подать заявку, одобрить/резерв, оценка меро и т.п.) — чтобы
    пользователь не мог нажать на кнопку многомесячной давности с уже неактуальным
    состоянием. Обходчик — `tg_bot/notifier.py::_process_button_removals`."""
    close_old_connections()
    from blog.models import PendingButtonRemoval
    PendingButtonRemoval.objects.create(
        chat_id=str(chat_id),
        message_id=message_id,
        remove_at=timezone.now() + timedelta(seconds=BUTTON_TTL_SECONDS),
    )


def fetch_due_button_removals(batch: int = 50) -> list:
    close_old_connections()
    from blog.models import PendingButtonRemoval
    return list(
        PendingButtonRemoval.objects.filter(remove_at__lte=timezone.now())
        .order_by('remove_at')[:batch]
    )


def delete_button_removal(removal_id: int):
    close_old_connections()
    from blog.models import PendingButtonRemoval
    PendingButtonRemoval.objects.filter(pk=removal_id).delete()


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
