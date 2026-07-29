"""Резолвинг ролей и контекстных прав тим-лидера (access-control.md)."""
from django.conf import settings
from django.db import transaction

from data_base import data_controller as dc
from blog.models import User  # только для аннотаций типов (не доступ к БД)
from blog.logging_utils import get_web_logger, actor

logger = get_web_logger(__name__)


def is_manager(user: User) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.manager_roles.filter(revoked_at__isnull=True).exists()


def is_tech_admin(user: User) -> bool:
    """Технический администратор — не бизнес-роль, а закрытый список telegram_id
    в .env (ANALYTICS_ADMIN_TG_IDS). Даёт доступ к техническому дашборду аналитики
    и к административному редактированию/удалению чужих профилей (единственный,
    кто может удалить чужой профиль целиком — не путать с блокировкой менеджером)."""
    if not user or not user.is_authenticated:
        return False
    return str(getattr(user, 'telegram_id', '')) in settings.ANALYTICS_ADMIN_TG_IDS


def is_team_leader(user: User) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.team_leader_roles.filter(revoked_at__isnull=True).exists()


def is_team_leader_of_event(user: User, event_id: int) -> bool:
    """Является ли user активным тим-лидером конкретного мероприятия."""
    if not user or not user.is_authenticated:
        return False
    return dc.event_staff_qs().filter(
        event_id=event_id, user=user, staff_role='team_lead'
    ).exists()


def can_process_applications(user: User, event_id: int) -> bool:
    """Менеджер — на всех меро; тим-лидер — только на своих (правило 3 db.md)."""
    return is_manager(user) or is_team_leader_of_event(user, event_id)


def can_manage_event(user: User) -> bool:
    """CRUD мероприятий, назначение персонала — только менеджер."""
    return is_manager(user)


def has_extended_access_to_profile(viewer: User, target: User) -> bool:
    """Расширенный + внутренний профиль чужого волонтёра (access-control.md, правило 5):

    владелец или менеджер — всегда; тим-лидер — только пока одновременно:
    - он team_lead на мероприятии, и
    - мероприятие ещё не завершено (event_status != 'finished'), и
    - целевой волонтёр подал заявку на это меро ИЛИ участвует в нём.
    """
    if not viewer or not viewer.is_authenticated:
        return False
    if viewer.id == target.id or is_manager(viewer):
        return True
    if not is_team_leader(viewer):
        return False

    tl_event_ids = dc.event_staff_qs().filter(
        user=viewer, staff_role='team_lead'
    ).exclude(event__event_status='finished').values_list('event_id', flat=True)

    if not tl_event_ids:
        return False

    has_application = dc.applications_qs().filter(
        user=target, event_id__in=tl_event_ids
    ).exists()
    has_participation = dc.participations_qs().filter(
        user=target, event_day__event_id__in=tl_event_ids
    ).exists()

    return has_application or has_participation


def account_is_complete(user: User) -> bool:
    """«Заполненный аккаунт» — минимум, при котором пользователь может подать заявку:
    известно ФИО (хотя бы имя), есть ссылка на Telegram (username или реальный
    telegram_id из бота) И указан номер телефона. Эти три поля (ФИО, ТГ, телефон) —
    обязательны для подачи заявки; остальные поля профиля опциональны.

    Авторизация в боте не обязательна — заявка может прийти из Excel-выгрузки, там
    достаточно ФИО + Telegram + телефон. Пользователи с веб-входом (login/пароль,
    служебный telegram_id `web:*`) без TG-username сюда не попадают."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    has_name = bool((user.first_name or '').strip())
    # Реальный telegram_id пользователя — положительное целое (служебные web:*-id и
    # отрицательные id каналов/групп не считаем «привязкой к Telegram»).
    real_tg_id = bool(user.telegram_id) and user.telegram_id.isdigit()
    has_tg = bool((user.telegram_username or '').strip()) or real_tg_id
    has_phone = bool((user.phone or '').strip())
    return has_name and has_tg and has_phone


def account_missing_fields(user: User) -> list:
    """Список человекочитаемых названий обязательных для заявки полей, которых не
    хватает в профиле (для плашки «заполните …, чтобы подать заявку»)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return ['ФИО', 'Telegram', 'номер телефона']
    missing = []
    if not (user.first_name or '').strip():
        missing.append('ФИО')
    real_tg_id = bool(user.telegram_id) and user.telegram_id.isdigit()
    if not ((user.telegram_username or '').strip() or real_tg_id):
        missing.append('Telegram')
    if not (user.phone or '').strip():
        missing.append('номер телефона')
    return missing


def role_label(user: User) -> str:
    if is_manager(user):
        return 'Менеджер'
    if is_team_leader(user):
        return 'Тим-лидер'
    return 'Волонтёр'


def role_slug(user: User) -> str:
    """Машиночитаемый слаг роли (аналитика/фильтры) — 'manager'/'team_leader'/'volunteer'."""
    if is_manager(user):
        return 'manager'
    if is_team_leader(user):
        return 'team_leader'
    return 'volunteer'


# ---------------------------------------------------------------------------
# Назначение/снятие ролей (настройки, только менеджер — см. settings_view)
# ---------------------------------------------------------------------------

def users_without_role(kind: str):
    """Волонтёры, у которых сейчас НЕТ активной роли `kind` ('team_lead'/'manager') —
    кандидаты для назначения, отсортированы по алфавиту (фамилия, имя)."""
    active_user_ids = dc.role_qs(kind).filter(revoked_at__isnull=True).values('user_id')
    return dc.users_qs().exclude(id__in=active_user_ids).order_by('last_name', 'first_name')


def users_with_role(kind: str):
    """Пользователи с активной ролью `kind` — кандидаты для снятия роли."""
    active_user_ids = dc.role_qs(kind).filter(revoked_at__isnull=True).values('user_id')
    return dc.users_qs().filter(id__in=active_user_ids).order_by('last_name', 'first_name')


@transaction.atomic
def assign_role(kind: str, users, assigned_by: User):
    """Выдаёт роль `kind` каждому из `users`, у кого её ещё нет. Возвращает список
    реально затронутых пользователей (уже имевших роль — пропускаются молча).

    Менеджеру автоматически выдаётся и роль тим-лидера (если её ещё нет) — чтобы
    менеджера можно было назначать тим-лидером на мероприятия наравне с обычными
    тим-лидерами (правило: у менеджера всегда есть профиль ТЛ)."""
    already_active = set(
        dc.role_qs(kind).filter(revoked_at__isnull=True, user__in=users).values_list('user_id', flat=True)
    )
    affected = []
    for user in users:
        if user.id in already_active:
            continue
        dc.create_role(kind, user, assigned_by=assigned_by)
        affected.append(user)
        if kind == 'manager' and not dc.has_active_role('team_lead', user):
            dc.create_role('team_lead', user, assigned_by=assigned_by)
        if kind == 'team_lead':
            from blog.services.notifications import notify_became_team_leader
            notify_became_team_leader(user)
        # Роль — источник достижений «Первый шаг в тим-лидеры» и т.п.; доначисляем сразу.
        from blog.services.achievements import recalc_user_achievements
        recalc_user_achievements(user)
    if affected:
        logger.info(
            'Выдана роль %s: subjects=%s by=%s',
            kind, [actor(u) for u in affected], actor(assigned_by),
        )
    return affected


@transaction.atomic
def revoke_role(kind: str, users, revoked_by: User = None):
    """Снимает активную роль `kind` у каждого из `users`. Возвращает список
    реально затронутых пользователей. `revoked_by` — кто снял (для аудита в логе)."""
    updated_ids = dc.revoke_roles(kind, users)
    affected = [u for u in users if u.id in updated_ids]
    if affected:
        logger.info(
            'Снята роль %s: subjects=%s by=%s',
            kind, [actor(u) for u in affected], actor(revoked_by),
        )
    return affected
