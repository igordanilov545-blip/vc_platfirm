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
from blog.logging_utils import get_bot_logger, actor

logger = get_bot_logger(__name__)


# ---------------------------------------------------------------------------
# Пользователи: первое касание, регистрация, профиль
# ---------------------------------------------------------------------------

def get_or_create_user(telegram_id: int, telegram_username: str = None,
                        first_name: str = None, last_name: str = None):
    """Первое касание (tg-bot.md §3.1) — не регистрация. Возвращает (user, created).

    Имя/фамилия из Telegram (если переданы) заполняют пустые поля профиля и участвуют
    в синхронизации с ранее поданными заявками (телефон и т.п.)."""
    close_old_connections()
    user, created = dc.get_or_create_user_by_telegram_id(
        telegram_id, telegram_username, first_name=first_name, last_name=last_name
    )
    if created:
        logger.info('Первое касание бота: создан гость %s telegram_id=%s', actor(user), telegram_id)
    return user, created


def get_user(user_id: int):
    close_old_connections()
    from blog.models import User
    return User.objects.get(pk=user_id)


def is_guest(user) -> bool:
    return user.registration_status != 'registered'


def complete_registration(user_id: int, first_name: str, last_name: str = None,
                          phone: str = None, middle_name: str = None):
    """Завершает регистрацию (tg-bot.md §3.2): имя обязательно, отчество/телефон опциональны."""
    close_old_connections()
    user = get_user(user_id)
    fields = {
        'first_name': first_name.strip()[:100],
        'registration_status': 'registered',
    }
    if last_name:
        fields['last_name'] = last_name.strip()[:100]
    if middle_name:
        fields['middle_name'] = middle_name.strip()[:100]
    if phone:
        fields['phone'] = phone.strip()[:20]
    result = dc.update_user_fields(user, **fields)
    logger.info('Регистрация в боте завершена: %s phone=%s', actor(user), bool(phone))
    return result


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


def verify_token_requester(token: str):
    """ФИО пользователя, инициировавшего подтверждение Telegram по токену (для текста
    «<ФИО> сейчас пытается подтвердить телеграм»). Возвращает (имя|None, ошибка|None)."""
    close_old_connections()
    from blog.services.telegram_verify import get_pending_token
    obj = get_pending_token(token)
    if obj is None:
        return None, 'invalid'
    u = obj.user
    name = (f'{u.last_name or ""} {u.first_name or ""}'.strip()) or u.telegram_username or f'#{u.id}'
    return name, None


def confirm_telegram_verification(token: str, telegram_id, telegram_username: str = None):
    """«Да, это я» из бота: верифицирует и привязывает telegram_id. (user, ошибка|None)."""
    close_old_connections()
    from blog.services.telegram_verify import confirm_verify_token
    return confirm_verify_token(token, telegram_id, telegram_username)


def reject_telegram_verification(token: str):
    """«Нет, это не я» из бота: гасит токен и разлогинивает инициатора. (user, ошибка|None)."""
    close_old_connections()
    from blog.services.telegram_verify import reject_verify_token
    return reject_verify_token(token)


def recognize_by_telegram(user_id: int, telegram_username: str, first_name: str = None, last_name: str = None):
    """«Вход через Telegram» — узнавание гостя по прошлым заявкам (bot-update.md §2.1.B):
    сначала по текущему username, а если он сменился в Telegram — по ФИО, которое
    просим на этом же экране. Возвращает (кандидат: User|None, имя_кандидата: str|None).
    Ничего не привязывает — только просмотр; привязка — в `confirm_recognized_account`."""
    close_old_connections()
    current_user = get_user(user_id)
    candidate = dc.find_candidate_user_by_telegram(
        telegram_username, first_name, last_name, exclude_user_id=current_user.id,
    )
    if not candidate:
        return None, None
    name = (f'{candidate.last_name or ""} {candidate.first_name or ""}'.strip()) or candidate.telegram_username
    return candidate, name


def confirm_recognized_account(guest_user_id: int, candidate_user_id: int, telegram_id, telegram_username: str = None):
    """«Да, это я» — переключает текущий Telegram-чат на найденный аккаунт (личность уже
    подтверждена интерактивно). `telegram_id` уникален, поэтому гостевую запись, созданную
    первым касанием в этом же чате (guest_user_id), нужно освободить: если она ещё
    гость без активности (никаких заявок/ролей) — удаляем её и переносим telegram_id на
    кандидата; иначе (уже что-то успел сделать под этим id) — коллизию не разруливаем
    автоматически, только логируем для менеджера (bot-update.md §3 — без миграции)."""
    close_old_connections()
    from blog.models import User

    candidate = User.objects.filter(pk=candidate_user_id).first()
    guest = User.objects.filter(pk=guest_user_id).first()
    if not candidate or not guest:
        return None, 'not_found'
    if candidate.id == guest.id:
        return candidate, None

    guest_has_activity = (
        guest.applications.exists() or guest.manager_roles.exists() or guest.team_leader_roles.exists()
    )
    if guest_has_activity:
        logger.warning(
            'Коллизия Telegram при узнавании: guest=%s (с активностью) пытался войти как candidate=%s '
            'telegram_id=%s username=%s — не перепривязываем.',
            guest.id, candidate.id, telegram_id, telegram_username,
        )
        return None, 'collision'

    guest.delete()
    dc.update_user_fields(candidate, telegram_id=str(telegram_id))
    if telegram_username:
        dc.update_user_fields(candidate, telegram_username=telegram_username)
    if candidate.registration_status != 'registered':
        dc.update_user_fields(candidate, registration_status='registered')
    logger.info('Вход через Telegram (узнавание): candidate=%s telegram_id=%s (гость %s удалён)',
                candidate.id, telegram_id, guest.id)
    return candidate, None


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
    logger.info('Установлены/сброшены веб-креды через бот: %s login=%s', actor(user), user.login)
    return user


# ---------------------------------------------------------------------------
# Статистика и мероприятия (волонтёр)
# ---------------------------------------------------------------------------

def user_stats(user_id: int) -> dict:
    """Статистика волонтёра (tg-bot.md/bot-update.md §2.2.B — порядок вывода: сезон,
    «до Звёздочки ПГАС», потенциал по активным заявкам, итог за всё время внизу)."""
    close_old_connections()
    from data_base.data_controller import get_const

    user = get_user(user_id)
    threshold = get_const('pgas_hours_threshold', default=100)
    hours_to_pgas = max(0, threshold - (user.season_hours or 0))

    potential_hours = 0
    for app in dc.get_user_active_applications(user_id):
        shifts = list(app.selected_shifts.all()) or list(app.event.shifts.all())
        for shift in shifts:
            potential_hours += max(0, round((shift.end_time - shift.start_time).total_seconds() / 3600))

    return {
        'total_hours': user.total_hours,
        'season_hours': user.season_hours,
        'total_events': user.total_event_count,
        'season_events': user.season_event_count,
        'is_star': is_pgas_star(user),
        'blacklisted': user.status == 'blacklisted',
        'hours_to_pgas': hours_to_pgas,
        'potential_hours': potential_hours,
    }


def open_events(limit: int = 7, user_id: int = None) -> list:
    """Ближайшие опубликованные мероприятия с открытым набором (tg-bot.md §4.1).

    Если передан `user_id`, к каждому меро добавляется инфо об АКТИВНОЙ заявке этого
    пользователя (`my_application_id`, `my_application_status`) — чтобы в списке вместо
    кнопки «Подать заявку» показать статус уже поданной заявки (db.md правило 7d)."""
    close_old_connections()
    today = timezone.now().date()
    events = dc.get_open_events()

    my_apps = {}
    if user_id:
        from blog.models import Application
        for app in Application.objects.filter(
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


def apply_to_event(user_id: int, event_id: int, shift_ids: list = None):
    """Подача заявки из бота (tg-bot.md §4.2–4.3, bot-update.md §2.1.E). Каждый вызов —
    независимая заявка на конкретное меро; несколько заявок на разные меро подаются
    отдельными вызовами. `shift_ids` — id выбранных `EventShift` (чипы выбора смен);
    если не переданы/пусты — заявка подаётся на все открытые смены меро (старое
    поведение, совместимость с прямой подачей без выбора).
    Возвращает (application|None, код ошибки|None). При `already_applied` объект
    существующей заявки кладётся в `application`, чтобы хендлер мог сразу предложить
    посмотреть/изменить/отменить её (db.md правило 7d), не делая второй запрос."""
    close_old_connections()
    user = get_user(user_id)
    event = next((e for e in dc.get_events() if e.id == event_id), None)
    if not event:
        return None, 'not_found'
    open_shifts = list(event.shifts.filter(recruit_status='open'))
    if not open_shifts:
        return None, 'closed'
    if user.status == 'blacklisted':
        return None, 'blacklisted'
    if is_guest(user):
        return None, 'need_registration'
    existing = dc.get_user_application_for_event(user_id, event_id)
    if existing:
        return existing, 'already_applied'

    shifts = [s for s in open_shifts if s.id in shift_ids] if shift_ids else open_shifts

    # Требования меро (db.md правило 6) — та же логика, что и на веб-подаче: если
    # волонтёр не соответствует хотя бы одному, заявка сразу уходит в резерв, без
    # особого сообщения пользователю (обычное «заявка отправлена»).
    from blog.services.requirements import check_application_requirements
    req_check = check_application_requirements(event, user)

    application = dc.create_application(
        event=event,
        user=user,
        first_name=user.first_name or '',
        last_name=user.last_name,
        middle_name=user.middle_name,
        telegram_username=user.telegram_username,
        phone=user.phone,
        submitted_at=timezone.now(),
        status='rejected' if req_check['auto_reject'] else 'new',
        auto_reject_reason='; '.join(req_check['reasons']) if req_check['auto_reject'] else None,
    )
    dc.set_application_shifts(application, shifts)
    notify_application_submitted(application, unknown_age=req_check['unknown_age'])
    logger.info(
        'Заявка подана из бота: application=%s event=%s by=%s%s',
        application.id, event_id, actor(user),
        f' auto_reject={application.auto_reject_reason!r}' if application.auto_reject_reason else '',
    )
    return application, None


def my_active_applications(user_id: int) -> list:
    """Только активные заявки волонтёра на ещё актуальные меро (new/approved,
    tg-bot.md §4.4, bot-update.md §2.2.E) — заявки на уже прошедшие мероприятия сюда
    не попадают (фильтр внутри `get_user_active_applications`). `shifts_summary` —
    какие смены заявки уже решены (✅/❌ по каждой), `post_link` — пост меро, если есть."""
    close_old_connections()
    apps = dc.get_user_active_applications(user_id)
    result = []
    for a in apps:
        shifts = list(a.selected_shifts.all())
        shifts_summary = None
        if shifts:
            decisions = {d.shift_id: d.status for d in a.shift_decisions.all()}
            parts = []
            for s in sorted(shifts, key=lambda s: s.day):
                status = decisions.get(s.id, 'new')
                icon = '✅' if status == 'approved' else ('❌' if status == 'rejected' else '⬜')
                parts.append(f'{icon} {s.day.strftime("%d.%m")}')
            shifts_summary = ' · '.join(parts)
        result.append({
            'id': a.id,
            'event_title': a.event.title,
            'status': a.status,
            'status_display': a.get_status_display(),
            'created_at': a.created_at,
            'shifts_summary': shifts_summary,
            'post_link': a.event.post_in_chanel_link or None,
        })
    return result


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


def edit_own_application(user_id: int, application_id: int, shift_ids: list):
    """Изменение смен активной заявки (bot-update.md §2.2.F, db.md правило 7d): создаёт
    НОВУЮ запись `applications` с новыми `selected_shifts` и статусом `new` — старая
    заявка остаётся в истории без изменений (дубли разрешены, см. правило 3). Плюс
    запись в `ApplicationChangeLog` (как при повторном Excel-импорте), чтобы ТЛ увидел
    изменение на странице меро. Возвращает (новая_заявка|None, код_ошибки|None)."""
    close_old_connections()
    from blog.models import EventShift, ApplicationChangeLog

    old = get_own_application(user_id, application_id)
    if not old or old.status not in ('new', 'approved'):
        return None, 'not_found'
    user = get_user(user_id)
    shifts = list(EventShift.objects.filter(pk__in=shift_ids, event=old.event)) if shift_ids else []

    from blog.services.requirements import check_application_requirements
    req_check = check_application_requirements(old.event, user)

    new_application = dc.create_application(
        event=old.event,
        user=user,
        first_name=old.first_name,
        last_name=old.last_name,
        middle_name=old.middle_name,
        telegram_username=old.telegram_username,
        phone=old.phone,
        functions=old.functions,
        role_in_event=old.role_in_event,
        submitted_at=timezone.now(),
        status='rejected' if req_check['auto_reject'] else 'new',
        auto_reject_reason='; '.join(req_check['reasons']) if req_check['auto_reject'] else None,
    )
    dc.set_application_shifts(new_application, shifts)
    notify_application_submitted(new_application, unknown_age=req_check['unknown_age'])

    name = f'{old.first_name} {old.last_name or ""}'.strip()
    ApplicationChangeLog.objects.create(
        event=old.event, application=new_application, kind='changed',
        text=f'{name} изменил(а) смены заявки через бота.',
    )
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


def process_application_shift_decision(user_id: int, application_id: int, shift_id: int, approve: bool):
    """Одобрить/резерв заявки ТОЛЬКО на конкретную смену (bot-update.md §2.3.C) — если
    заявка подана на несколько смен, решение по одной не трогает остальные. Переиспользует
    веб-эталон `blog.services.applications.process_shift_decision` (создание/удаление
    Participation, ApplicationShiftDecision, пересчёт статистики, уведомление волонтёру —
    уже всё реализовано там, здесь только права и вызов)."""
    close_old_connections()
    from blog.models import Application, EventShift
    from blog.services.applications import process_shift_decision

    user = get_user(user_id)
    application = Application.objects.select_related('event').filter(pk=application_id).first()
    if not application:
        return None, 'not_found'
    if not roles_service.can_process_applications(user, application.event_id):
        return None, 'forbidden'
    shift = EventShift.objects.filter(pk=shift_id, event_id=application.event_id).first()
    if not shift:
        return None, 'not_found'

    new_status = 'approved' if approve else 'rejected'
    process_shift_decision(application, shift, new_status, processed_by=user)
    return application, None


def application_shifts_for_decision(application_id: int):
    """Смены конкретной заявки (выбранные чипами, либо все смены меро) — для отрисовки
    кнопок по сменам на карточке заявки у ТЛ (bot-update.md §2.3.C)."""
    close_old_connections()
    from blog.models import Application
    application = Application.objects.select_related('event').prefetch_related(
        'selected_shifts', 'event__shifts'
    ).filter(pk=application_id).first()
    if not application:
        return []
    return list(application.selected_shifts.all()) or list(application.event.shifts.all())


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

    dc.update_participation_status(participation, status, hours=hours, actor_user=user)
    recalc_user_aggregates(participation.user)
    if status == 'absent_unexcused':
        apply_churn_no_show(participation.user)
    elif status == 'attended':
        apply_churn_activity_decay(participation.user)
    logger.info(
        'Явка проставлена из бота: participation=%s status=%s by=%s subject=%s',
        participation_id, status, actor(user), actor(participation.user),
    )
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
