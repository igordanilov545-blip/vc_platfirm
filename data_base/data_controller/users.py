"""Доступ к данным: пользователи и ролевые записи (менеджер / тим-лидер).

Матчинг/дозаполнение профиля из прошлых заявок (`get_or_create_user_by_telegram_id`,
`sync_user_from_applications`) — единая точка, чтобы веб и бот вели себя одинаково.
Бизнес-логику (ACL, пересчёты) сюда НЕ добавляем — она в `blog/services/*`.
"""
from typing import Optional, List

from django.db.models import Q

from blog.models import User, Manager, TeamLeader, Application
from ._base import logger, actor


def create_user(
    telegram_id: str,
    telegram_username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    middle_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    vk_username: Optional[str] = None,
    birthday: Optional[str] = None,
    about: Optional[str] = None,
    status: str = 'active',
    comment: Optional[str] = None,
    login: Optional[str] = None,
) -> User:
    """Создает пользователя через кастомный менеджер."""
    extra = {}
    if middle_name is not None:
        extra['middle_name'] = middle_name
    if login is not None:
        extra['login'] = login
    user = User.objects.create_user(
        telegram_id=telegram_id,
        telegram_username=telegram_username,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        VK_username=vk_username,
        birthday=birthday,
        about=about,
        status=status,
        comment=comment,
        **extra,
    )
    logger.info('INSERT users: user=%s telegram_id=%s', user.id, telegram_id)
    return user


def get_user_by_telegram_id(telegram_id: str) -> Optional[User]:
    return User.objects.filter(telegram_id=str(telegram_id)).first()


def get_user_by_id(user_id: int) -> Optional[User]:
    """Пользователь по первичному ключу или None (мягкий вариант для сервисов бота)."""
    return User.objects.filter(pk=user_id).first()


def is_login_taken(login: str, exclude_user_id: Optional[int] = None) -> bool:
    """Занят ли веб-логин (регистронезависимо) кем-то, кроме указанного пользователя."""
    qs = User.objects.filter(login__iexact=login)
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.exists()


def get_or_create_user_by_telegram_id(
    telegram_id: str,
    telegram_username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
):
    """Первое касание бота (tg-bot.md §3.1): создаёт пользователя-гостя, если его ещё нет.
    Возвращает (user, created).

    При наличии данных из Telegram (username, имя/фамилия) заполняет ими пустые поля
    профиля: telegram_username, first_name, last_name и system_username (из username, иначе
    из имени). Уже заполненные пользователем поля не перетираются. После этого пытается
    подтянуть недостающее (в первую очередь телефон) из ранее поданных заявок (в т.ч.
    Excel-импорта) — см. sync_user_from_applications."""
    user, created = User.objects.get_or_create(
        telegram_id=str(telegram_id),
        defaults={
            'telegram_username': telegram_username,
            'first_name': first_name,
            'last_name': last_name,
            'system_username': telegram_username or first_name,
            'registration_status': 'guest',
        },
    )

    updates = []
    if telegram_username and user.telegram_username != telegram_username:
        user.telegram_username = telegram_username
        updates.append('telegram_username')
    # Заполняем ТОЛЬКО пустые поля — не перетираем то, что пользователь уже указал сам.
    if first_name and not (user.first_name or '').strip():
        user.first_name = first_name
        updates.append('first_name')
    if last_name and not (user.last_name or '').strip():
        user.last_name = last_name
        updates.append('last_name')
    if not (user.system_username or '').strip():
        candidate = telegram_username or first_name or user.first_name
        if candidate:
            user.system_username = candidate
            updates.append('system_username')
    if updates:
        user.save(update_fields=updates)

    # Подтягиваем недостающие данные (телефон, ФИО) из ранее поданных заявок —
    # напр. пользователь раньше был импортирован из Excel и мы знаем его телефон.
    sync_user_from_applications(user)

    return user, created


def find_candidate_user_by_telegram(
    username: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None,
    exclude_user_id: Optional[int] = None,
) -> Optional[User]:
    """Кандидат «мы тебя знаем» для узнавания гостя по Telegram (bot-update.md §2.1.B):
    сопоставление по текущему `telegram_username` — а если он сменился (пользователь
    переименовался в Telegram) или совпадение — это сам текущий гость (`exclude_user_id`)
    — по ФИО, как и матчинг заявок (username → ФИО). Ничего не создаёт и не привязывает."""
    uname = (username or '').lstrip('@')
    if uname:
        qs = User.objects.filter(telegram_username__iexact=uname)
        if exclude_user_id:
            qs = qs.exclude(pk=exclude_user_id)
        found = qs.order_by('-id').first()
        if found:
            return found
    if (first_name or '').strip() and (last_name or '').strip():
        qs = User.objects.filter(first_name__iexact=first_name.strip(), last_name__iexact=last_name.strip())
        if exclude_user_id:
            qs = qs.exclude(pk=exclude_user_id)
        return qs.order_by('-id').first()
    return None


def sync_user_from_applications(user: User) -> User:
    """Синхронизирует профиль с ранее поданными заявками того же человека: заполняет
    пустые поля (телефон, ФИО, telegram_username) данными из наиболее свежей заявки,
    сопоставленной по telegram_username → телефону → ФИО. Также привязывает найденные
    «ничьи» заявки (user IS NULL) к этому пользователю.

    Ничего не перетирает, если поле уже заполнено. Работает и для веб-, и для бот-входа.
    """
    uname = (user.telegram_username or '').lstrip('@') if user.telegram_username else None
    conditions = Q()
    if uname:
        conditions |= Q(telegram_username__iexact=uname)
    if (user.phone or '').strip():
        conditions |= Q(phone=user.phone)
    if (user.first_name or '').strip() and (user.last_name or '').strip():
        conditions |= Q(first_name__iexact=user.first_name, last_name__iexact=user.last_name)
    if not conditions:
        return user

    apps = Application.objects.filter(conditions).order_by('-submitted_at', '-created_at')

    # Привязка ничьих заявок к пользователю (сопоставление по данным).
    apps.filter(user__isnull=True).update(user=user)

    source = apps.first()
    if not source:
        return user

    updates = []
    if not (user.phone or '').strip() and (source.phone or '').strip():
        user.phone = source.phone
        updates.append('phone')
    if not (user.first_name or '').strip() and (source.first_name or '').strip():
        user.first_name = source.first_name
        updates.append('first_name')
    if not (user.last_name or '').strip() and (source.last_name or '').strip():
        user.last_name = source.last_name
        updates.append('last_name')
    if not (user.telegram_username or '').strip() and (source.telegram_username or '').strip():
        user.telegram_username = source.telegram_username.lstrip('@')
        updates.append('telegram_username')
    if updates:
        user.save(update_fields=updates)
    return user


def update_user_fields(user: User, **fields) -> User:
    """Точечное обновление полей пользователя (например, при регистрации в боте)."""
    allowed = set(fields) & {f.name for f in User._meta.get_fields()}
    for name in allowed:
        setattr(user, name, fields[name])
    if allowed:
        user.save(update_fields=list(allowed))
    return user


def set_user_status(user: User, status: str, *, comment: Optional[str] = None,
                    churn_score: Optional[float] = None, actor_user: Optional[User] = None) -> User:
    """Меняет статус допуска пользователя (active/inactive/blacklisted) и, опционально,
    комментарий/churn_score в одной записи. Бизнес-правила (когда блокировать, что
    обнулять) — в сервисе, здесь только запись + аудит."""
    fields = ['status']
    user.status = status
    if comment is not None:
        user.comment = comment
        fields.append('comment')
    if churn_score is not None:
        user.churn_score = churn_score
        fields.append('churn_score')
    user.save(update_fields=fields)
    logger.info('UPDATE users: user=%s status=%s by=%s', user.id, status, actor(actor_user))
    return user


def set_user_verification(user: User, *, verified_at, verified_by: Optional[User],
                          snapshot=None) -> User:
    """Проставляет/снимает менеджерскую верификацию для справки ПГАС. `verified_at=None`
    снимает верификацию. Снимок верифицированных полей (`snapshot`) хранится, чтобы
    отследить их последующее изменение."""
    user.verified_by_manager_at = verified_at
    user.verified_by_manager_by = verified_by
    user.verified_snapshot = snapshot
    user.save(update_fields=['verified_by_manager_at', 'verified_by_manager_by', 'verified_snapshot'])
    logger.info('UPDATE users: user=%s pgas_verified=%s by=%s',
                user.id, bool(verified_at), actor(verified_by))
    return user


def get_users(
    name: Optional[str] = None,
    telegram_username: Optional[str] = None,
    telegram_id: Optional[str] = None,
    phone: Optional[str] = None
) -> List[User]:
    filters = Q()
    if name:
        filters &= Q(first_name__icontains=name) | Q(last_name__icontains=name)
    if telegram_username:
        filters &= Q(telegram_username__iexact=telegram_username)
    if telegram_id:
        filters &= Q(telegram_id=telegram_id)
    if phone:
        filters &= Q(phone__icontains=phone)
    return list(User.objects.filter(filters))


# --- ROLES: MANAGER / TEAM LEADER ---
def create_manager(
    user: User,
    assigned_by: Optional[User] = None,
    total_events: int = 0,
    season_events: int = 0
) -> Manager:
    """Выдает роль менеджера. У менеджера всегда есть и профиль тим-лидера
    (если ещё нет) — чтобы его можно было назначать ТЛ на мероприятия."""
    manager = Manager.objects.create(
        user=user,
        assigned_by=assigned_by,
        total_events=total_events,
        season_events=season_events
    )
    if not TeamLeader.objects.filter(user=user, revoked_at__isnull=True).exists():
        TeamLeader.objects.create(user=user, assigned_by=assigned_by)
    return manager


def create_team_leader(
    user: User,
    assigned_by: Optional[User] = None,
    total_events: int = 0,
    season_events: int = 0
) -> TeamLeader:
    """Выдает роль тим-лидера."""
    return TeamLeader.objects.create(
        user=user,
        assigned_by=assigned_by,
        total_events=total_events,
        season_events=season_events
    )


def get_managers(user_id: Optional[int] = None, is_active_only: bool = True) -> List[Manager]:
    qs = Manager.objects.select_related('user')
    if user_id:
        qs = qs.filter(user_id=user_id)
    if is_active_only:
        qs = qs.filter(revoked_at__isnull=True)
    return list(qs)


_ROLE_MODELS = {'team_lead': TeamLeader, 'manager': Manager}


def reset_all_season_counters() -> int:
    """Обнуляет сезонные счётчики (season_hours/season_event_count) у ВСЕХ пользователей
    при закрытии сезона (bulk). Возвращает число затронутых строк."""
    n = User.objects.update(season_hours=0, season_event_count=0)
    logger.info('UPDATE users: season counters reset for all (%s rows)', n)
    return n


def role_qs(kind: str):
    """Ленивый queryset ролевой записи по виду ('team_lead'/'manager') — для сервиса
    roles (кто без роли / с ролью, назначение/снятие). Единая точка вместо
    Manager.objects/TeamLeader.objects в сервисе."""
    return _ROLE_MODELS[kind].objects.all()


def create_role(kind: str, user: User, assigned_by: Optional[User] = None):
    """Создаёт ролевую запись нужного вида. Бизнес-правило «менеджер ⇒ и тим-лидер»
    остаётся в сервисе roles (assign_role), здесь — только запись + аудит."""
    obj = _ROLE_MODELS[kind].objects.create(user=user, assigned_by=assigned_by)
    logger.info('INSERT %s_role: user=%s by=%s', kind, user.id, actor(assigned_by))
    return obj


def revoke_roles(kind: str, users) -> list:
    """Снимает активные роли `kind` у переданных пользователей (bulk). Возвращает список
    user_id, у кого роль реально была активна (и снята)."""
    from django.utils import timezone
    qs = _ROLE_MODELS[kind].objects.filter(revoked_at__isnull=True, user__in=users)
    updated_ids = list(qs.values_list('user_id', flat=True))
    if updated_ids:
        qs.update(revoked_at=timezone.now())
        logger.info('UPDATE %s_role: revoked subjects=%s', kind, updated_ids)
    return updated_ids


def has_active_role(kind: str, user: User) -> bool:
    return _ROLE_MODELS[kind].objects.filter(user=user, revoked_at__isnull=True).exists()


def get_team_leaders(user_id: Optional[int] = None, is_active_only: bool = True) -> List[TeamLeader]:
    qs = TeamLeader.objects.select_related('user')
    if user_id:
        qs = qs.filter(user_id=user_id)
    if is_active_only:
        qs = qs.filter(revoked_at__isnull=True)
    return list(qs)
