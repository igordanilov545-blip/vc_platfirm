"""Сервисы бота: домен «users». Часть пакета tg_bot.services (см. README.md).

Пользователи: первое касание, регистрация, профиль, подписки, узнавание
аккаунта, роли, веб-креды, статистика.

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403


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
        from blog.services.incidents import create_incident
        create_incident(
            'tg_collision',
            f'Два разных пользователя с одним Telegram: «{guest.full_name}» (id={guest.id}) '
            f'пытался войти как «{candidate.full_name}» (id={candidate.id}) — требуется ручной разбор.',
            related_user=candidate,
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
