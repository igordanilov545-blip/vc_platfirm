"""Движок системы достижений (achievements.md, этап «Ядро + auto-достижения»).

Идея: у каждого AUTO-достижения есть код (`AchievementDefinition.code`), которому
соответствует функция-эвалуатор в EVALUATORS. Эвалуатор по пользователю возвращает:
  • для series — целочисленный ПРОГРЕСС (сколько накоплено: часов, меро, категорий…);
  • для single — bool (факт есть/нет).

`recalc_user_achievements(user)` гоняет все активные auto-достижения и доначисляет то,
что заслужено, но ещё не выдано:
  • series — по строке на КАЖДУЮ пройденную ступень (решение этапа реализации), с учётом
    идемпотентности (has_user_achievement по (user, achievement, series_value));
  • single — одну строку, если эвалуатор истинен.
После выдачи пересчитываем агрегат-кэш AchievementStat затронутых достижений.

Ручные достижения (курсы, source_type='manual_grant') движок не трогает — их выдаёт
менеджер отдельным потоком (следующий этап).

Пересчёт идемпотентен и дёшев (десятки определений, простые агрегаты), поэтому его
безопасно звать после любой операции, меняющей исходные данные (явка/часы, заявка,
отзыв, верификация, заполнение профиля) — см. вызовы recalc_user_achievements.
"""
from django.db.models import Count, F

from data_base import data_controller as dc
from blog.logging_utils import get_web_logger

logger = get_web_logger(__name__)


# ======================================================================
# Уровни сложности достижений (tier) — ЕДИНАЯ точка правды об оформлении рамок.
# Обычная шкала 1..6 (по возрастанию редкости) + уникальные уровни вне шкалы для
# точечных достижений («был на конкретном меро» — 'event', «прошёл курс» — 'course').
#
# Как задаётся tier:
#   • series — N-я ступень имеет tier = N (1-я = бронза … 6-я = фиолетовый), это НЕ
#     хранится, а выводится по порядку ступени в build_profile_achievements;
#   • single/hidden/manual — tier хранится явно в AchievementDefinition.tier
#     (1 — «заполнить профиль/быть волонтёром», 6 — «откликнуться за минуту»,
#     'event'/'course' — уникальные обводки точечных достижений).
#
# СМЕНА ОФОРМЛЕНИЯ: меняем только `css_class` здесь + соответствующие CSS-классы
# .ach-tier--* в nexus.css. Ни шаблоны, ни движок трогать не нужно — они оперируют
# ключом tier, а не цветами.
# ======================================================================
TIERS = {
    1: {'name': 'Бронза', 'css_class': 'ach-tier--bronze'},
    2: {'name': 'Серебро', 'css_class': 'ach-tier--silver'},
    3: {'name': 'Золото', 'css_class': 'ach-tier--gold'},
    4: {'name': 'Обсидиан', 'css_class': 'ach-tier--obsidian'},
    5: {'name': 'Алый кристалл', 'css_class': 'ach-tier--scarlet'},
    6: {'name': 'Фиолетовый кристалл', 'css_class': 'ach-tier--violet'},
    'event': {'name': 'Мероприятие', 'css_class': 'ach-tier--event'},
    'course': {'name': 'Курс', 'css_class': 'ach-tier--course'},
}
# Максимальный обычный уровень — ступени series выше него всё равно красим топовым
# уровнем (страховка, если у series окажется больше 6 ступеней).
_MAX_NUMERIC_TIER = 6


def tier_meta(tier):
    """Метаданные уровня (name, css_class) по ключу tier. Неизвестный/пустой tier →
    нейтральное оформление (ach-tier--none). Числовой tier > 6 приводим к 6."""
    if isinstance(tier, int) and tier > _MAX_NUMERIC_TIER:
        tier = _MAX_NUMERIC_TIER
    return TIERS.get(tier, {'name': '', 'css_class': 'ach-tier--none'})


# ----------------------------------------------------------------------
# Эвалуаторы прогресса. Каждый принимает User, возвращает int (series) или bool (single).
# Держим их «тонкими» и на ORM напрямую (сервисный слой это допускает): считаем по
# фактическим данным, без кэша — пересчёт редкий и точечный.
# ----------------------------------------------------------------------
def _attended(user):
    return dc.participations_qs().filter(user=user, status='attended')


def ev_total_hours(user):
    return user.total_hours or 0


# Кэш забегов человека — только на время recalc_user_achievements (там race_<id>
# спрашивают десятки раз); вне пересчёта всегда считаем заново.
_RACE_CACHE = {}


def _race_ids(user):
    if user.pk in _RACE_CACHE:
        if _RACE_CACHE[user.pk] is None:
            _RACE_CACHE[user.pk] = _compute_race_ids(user)
        return _RACE_CACHE[user.pk]
    return _compute_race_ids(user)


def _compute_race_ids(user):
    """Забеги (мероприятия, EventGroup), где человек был: хватает одной смены с явкой,
    роль не важна; тим-лидер засчитывается и по назначению на уже прошедший забег."""
    from django.utils import timezone
    from django.db.models import Max
    # Позиция без мероприятия (старые данные) — сама себе забег: ключ −id позиции.
    ids = {group_id if group_id else -event_id for group_id, event_id in
           _attended(user).values_list('event_day__event__event_group', 'event_day__event')}
    led = (dc.event_staff_qs().filter(user=user, staff_role='team_lead', event__event_group__isnull=False)
           .values('event__event_group').annotate(last=Max('event__event_group__positions__shifts__day')))
    today = timezone.localdate()
    ids |= {row['event__event_group'] for row in led if row['last'] and row['last'] < today}
    return ids


def ev_total_events(user):
    """Копилка забегов: разные мероприятия (забеги), а не позиции и не смены."""
    return len(_race_ids(user))


def ev_shifts_total(user):
    return _attended(user).count()


def _race_order():
    """Прошедшие и идущие забеги по дате первой смены — основа серии «подряд»."""
    from django.utils import timezone
    from django.db.models import Min
    rows = (dc.event_groups_qs().annotate(first=Min('positions__shifts__day'))
            .filter(first__isnull=False, first__lte=timezone.localdate()).order_by('first', 'pk'))
    return [row.pk for row in rows]


def ev_race_streak(user):
    """Самая длинная серия забегов подряд (по календарю забегов) без пропуска."""
    mine = _race_ids(user)
    best = run = 0
    for group_id in _race_order():
        run = run + 1 if group_id in mine else 0
        best = max(best, run)
    return best


def ev_years_active(user):
    return len({day.year for day in _attended(user).values_list('event_day__day', flat=True)})


def ev_season_hours(user):
    return user.season_hours or 0


def ev_season_events(user):
    return user.season_event_count or 0


def ev_categories_diversity(user):
    return (
        _attended(user)
        .filter(event_day__event__category_map__category__kind='category')
        .values('event_day__event__category_map__category')
        .distinct().count()
    )


def ev_organizations_diversity(user):
    return (
        _attended(user)
        .values('event_day__event__organization')
        .exclude(event_day__event__organization__isnull=True)
        .distinct().count()
    )


def ev_locations_diversity(user):
    return (
        _attended(user)
        .values('event_day__location')
        .exclude(event_day__location__isnull=True)
        .distinct().count()
    )


def ev_org_loyalty(user):
    """Максимум мероприятий с ОДНОЙ организацией (обратная разнообразию лояльность)."""
    rows = (
        _attended(user)
        .exclude(event_day__event__organization__isnull=True)
        .values('event_day__event__organization')
        .annotate(n=Count('event_day__event', distinct=True))
        .order_by('-n')
    )
    return rows[0]['n'] if rows else 0


def ev_team_lead_events(user):
    """Сколько забегов человек вёл тим-лидером (назначение на любую позицию забега)."""
    rows = dc.event_staff_qs().filter(user=user, staff_role='team_lead')
    groups = set(rows.exclude(event__event_group__isnull=True).values_list('event__event_group', flat=True))
    return len(groups) + rows.filter(event__event_group__isnull=True).values('event').distinct().count()


def ev_team_lead_shifts(user):
    """Смены с явкой, где человек был тим-лидером (назначение или роль «Тим-лидер»)."""
    from django.db.models import Q
    led_events = dc.event_staff_qs().filter(user=user, staff_role='team_lead').values('event')
    lead_roles = dc.application_shift_decisions_qs().filter(application__user=user, role='Тим-лидер').values('shift')
    return _attended(user).filter(Q(event_day__event__in=led_events) | Q(event_day__in=lead_roles)).count()


def ev_feedbacks(user):
    return dc.feedbacks_qs().filter(author=user).count()


def ev_applications(user):
    return dc.applications_qs().filter(user=user).count()


def ev_people_helped(user):
    """Сумма people_helped мероприятий, где волонтёр был (причастность к помощи)."""
    from django.db.models import Sum
    event_ids = _attended(user).values_list('event_day__event', flat=True).distinct()
    from blog.models import Event
    total = Event.objects.filter(id__in=event_ids).aggregate(s=Sum('people_helped'))['s']
    return total or 0


# --- single-факты ---
def ev_registered(user):
    return user.registration_status == 'registered'


def ev_first_event(user):
    return _attended(user).exists()


def ev_first_application(user):
    return dc.applications_qs().filter(user=user).exists()


def ev_first_feedback(user):
    return dc.feedbacks_qs().filter(author=user).exists()


def ev_first_team_lead(user):
    return user.team_leader_roles.exists()


def ev_profile_complete(user):
    from blog.services.roles import account_is_complete
    return account_is_complete(user)


def ev_verified(user):
    return user.verified_by_manager_at is not None


FULL_COURSE = ('Старт', 'Дистанция', 'Финиш')


def ev_full_course(user):
    """«Вся трасса»: был на старте, на дистанции и на финише (категории забегов)."""
    names = set(_attended(user).filter(event_day__event__category_map__category__kind='category')
                .values_list('event_day__event__category_map__category__name', flat=True))
    return all(name in names for name in FULL_COURSE)


def ev_early_bird(user):
    """Смена, начавшаяся до 7 утра (подготовка старта)."""
    from django.utils import timezone
    return any(timezone.localtime(start).hour < 7
               for start in _attended(user).values_list('event_day__start_time', flat=True))


def ev_double_shift(user):
    """Две смены с явкой в один день одного забега."""
    rows = (_attended(user).values('event_day__day', 'event_day__event__event_group')
            .annotate(n=Count('id')).filter(n__gte=2))
    return rows.exists()


def ev_all_days(user):
    """Многодневный забег (2+ дня) — был на каждом его дне."""
    from collections import defaultdict
    mine = defaultdict(set)
    for group_id, day in _attended(user).exclude(event_day__event__event_group__isnull=True).values_list(
            'event_day__event__event_group', 'event_day__day'):
        mine[group_id].add(day)
    for group_id, days in mine.items():
        all_days = set(dc.event_shifts_qs().filter(event__event_group_id=group_id).values_list('day', flat=True))
        if len(all_days) >= 2 and all_days <= days:
            return True
    return False


def ev_reliable(user):
    """10+ смен с явкой и ни одной неявки без причины."""
    parts = dc.participations_qs().filter(user=user)
    return parts.filter(status='attended').count() >= 10 and not parts.filter(status='absent_unexcused').exists()


def _fastest_response_minutes(user):
    """Наименьшая задержка (в минутах) между публикацией поста меро в канале
    (Event.post_published_at) и подачей заявки (Application.submitted_at). None, если
    нет ни одной заявки с обеими отметками. Основа для «скорости отклика» (три ступени)."""
    apps = (
        dc.applications_qs()
        .filter(user=user, submitted_at__isnull=False, event__post_published_at__isnull=False)
        .annotate(delay=F('submitted_at') - F('event__post_published_at'))
        .values_list('delay', flat=True)
    )
    best = None
    for d in apps:
        if d is None:
            continue
        minutes = d.total_seconds() / 60.0
        if minutes < 0:
            continue  # заявка раньше поста — аномалия данных, игнорируем
        if best is None or minutes < best:
            best = minutes
    return best


def _response_within(user, minutes_limit):
    best = _fastest_response_minutes(user)
    return best is not None and best <= minutes_limit


def ev_response_30min(user):
    return _response_within(user, 30)


def ev_response_5min(user):
    return _response_within(user, 5)


def ev_response_1min(user):
    return _response_within(user, 1)


# Реестр: код достижения → эвалуатор. Определения БД с source_type='auto' и кодом НЕ из
# этого реестра движок просто пропускает (например, ручные курсы или ещё не
# реализованные скрытые точечные достижения — они выдаются иначе).
EVALUATORS = {
    # series
    'hours_total': ev_total_hours,
    'events_total': ev_total_events,
    'hours_season': ev_season_hours,
    'events_season': ev_season_events,
    'categories_diversity': ev_categories_diversity,
    'organizations_diversity': ev_organizations_diversity,
    'locations_diversity': ev_locations_diversity,
    'organization_loyalty': ev_org_loyalty,
    'team_lead_events': ev_team_lead_events,
    'feedbacks_total': ev_feedbacks,
    'applications_total': ev_applications,
    'people_helped': ev_people_helped,
    'shifts_total': ev_shifts_total,
    'race_streak': ev_race_streak,
    'years_active': ev_years_active,
    'team_lead_shifts': ev_team_lead_shifts,
    # single
    'registered': ev_registered,
    'first_event': ev_first_event,
    'first_application': ev_first_application,
    'first_feedback': ev_first_feedback,
    'first_team_lead': ev_first_team_lead,
    'profile_complete': ev_profile_complete,
    'verified_account': ev_verified,
    'response_30min': ev_response_30min,
    'response_5min': ev_response_5min,
    'response_1min': ev_response_1min,
    'full_course': ev_full_course,
    'early_bird': ev_early_bird,
    'double_shift': ev_double_shift,
    'all_days': ev_all_days,
    'reliable': ev_reliable,
}


# Префиксы ДИНАМИЧЕСКИХ достижений (по одному на объект справочника). Их код
# параметризован id объекта (category_3, organization_7), а прогресс считается по
# участиям волонтёра в этом конкретном объекте. Сами определения заводятся/удаляются
# сигналами при создании/удалении объекта (см. ensure_*_achievement / signals.py).
def ev_category_count(user, category_id):
    """Сколько РАЗНЫХ меро данной категории посетил волонтёр (series по категории)."""
    return (
        _attended(user)
        .filter(event_day__event__category_map__category_id=category_id)
        .values('event_day__event').distinct().count()
    )


def ev_organization_count(user, organization_id):
    """Сколько РАЗНЫХ меро данной организации посетил волонтёр (series по организации)."""
    return (
        _attended(user)
        .filter(event_day__event__organization_id=organization_id)
        .values('event_day__event').distinct().count()
    )


def ev_race(user, group_id):
    """Точечное «был на этом забеге» (одной смены достаточно, роль не важна)."""
    return group_id in _race_ids(user)


# Префикс → функция (user, obj_id) для параметризованных динамических достижений.
DYNAMIC_EVALUATORS = {
    'category_': ev_category_count,
    'organization_': ev_organization_count,
    'race_': ev_race,
}


def progress_for(user, definition):
    """Текущий прогресс пользователя по auto-достижению (int для series, bool для single).
    None — если для кода нет эвалуатора (движок такое достижение не считает — напр.
    точечные event_<id> выдаются не движком, а хуком завершения меро)."""
    fn = EVALUATORS.get(definition.code)
    if fn is not None:
        return fn(user)
    # Динамические: code = "<prefix><obj_id>" (category_3 / organization_7).
    for prefix, dyn_fn in DYNAMIC_EVALUATORS.items():
        if definition.code.startswith(prefix):
            rest = definition.code[len(prefix):]
            if rest.isdigit():
                return dyn_fn(user, int(rest))
    return None


def recalc_user_achievements(user, *, notify=False):
    """Пересчитать и доначислить auto-достижения пользователя. Возвращает список
    новых UserAchievement (для попапа/уведомления — на этом этапе просто возвращаем).

    Идемпотентно: повторный вызов без изменения данных ничего не выдаёт. Ручные
    (manual_grant) достижения не трогаем. notify — задел на пинг о новом достижении
    (реализуется отдельно), сейчас параметр только прокидывает намерение в лог."""
    newly = []
    touched = set()
    _RACE_CACHE[user.pk] = None  # кэш забегов живёт один пересчёт
    try:
        for definition in dc.get_active_definitions():
            if definition.source_type != 'auto':
                continue
            value = progress_for(user, definition)
            if value is None:
                continue

            if definition.kind == 'series':
                progress = int(value or 0)
                for step_value, _label in definition.steps():
                    if progress >= step_value and not dc.has_user_achievement(user, definition, step_value):
                        newly.append(dc.grant_achievement(user, definition, series_value=step_value))
                        touched.add(definition)
            else:  # single
                if value and not dc.has_user_achievement(user, definition, None):
                    newly.append(dc.grant_achievement(user, definition, series_value=None))
                    touched.add(definition)

        for definition in touched:
            dc.recompute_achievement_stat(definition)
    finally:
        _RACE_CACHE.pop(user.pk, None)

    if newly:
        logger.info(
            'Достижения доначислены: user=%s count=%s notify=%s codes=%s',
            user.id, len(newly), notify, [ua.achievement.code for ua in newly],
        )
    return newly


# ======================================================================
# Динамические достижения: по одному на каждый объект справочника (категория,
# организация — series-ряд; мероприятие — точечный single). Заводятся/удаляются
# сигналами при создании/удалении объекта (blog/signals.py), чтобы «в таблице есть
# объект → есть и достижение» держалось само собой.
# ======================================================================
# Разумные дефолтные ступени для «N раз в категории/с организацией».
_CATEGORY_STEPS = [1, 3, 5, 10, 25]
_ORGANIZATION_STEPS = [1, 3, 5, 10]


def _steps_json(values):
    labels = {1: '1 мероприятие'}
    return [{'value': v, 'label': labels.get(v, f'{v} мероприятий')} for v in values]


def category_achievement_defaults(name):
    return dict(
        kind='series', visibility='common', group='Категории',
        title=f'Категория «{name}»',
        description=f'Помогай на забегах в категории «{name}».',
        icon='🎯', series_steps=_steps_json(_CATEGORY_STEPS),
        source_type='auto', is_active=True,
    )


def ensure_category_achievement(category):
    """Series-достижение под категорию забегов (идемпотентно). Функциям ФиП
    (kind=function) достижение не положено — их ряд удаляется."""
    if getattr(category, 'kind', 'category') != 'category':
        remove_dynamic_achievement(f'category_{category.id}')
        return None
    d, _ = dc.upsert_definition(code=f'category_{category.id}', defaults=category_achievement_defaults(category.name))
    return d


def race_achievement_defaults(title):
    return dict(
        kind='single', visibility='hidden', group='Забеги',
        title=f'Забег: {title}',
        description=f'Ты помогал на забеге «{title}».',
        icon='🏅', series_steps=None,
        source_type='auto', is_active=True, tier='event',
    )


def ensure_race_achievement(group):
    """Точечное достижение «был на этом забеге» — по одному на мероприятие (EventGroup).
    Выдаёт движок (ev_race): хватает одной смены с явкой, роль не важна."""
    d, _ = dc.upsert_definition(code=f'race_{group.id}', defaults=race_achievement_defaults(group.title))
    return d


def ensure_organization_achievement(organization):
    d, _ = dc.upsert_definition(
        code=f'organization_{organization.id}',
        defaults=dict(
            kind='series', visibility='common', group='Организации',
            title=f'Партнёр «{organization.name}»',
            description=f'Участвуй в мероприятиях организации «{organization.name}».',
            icon='🤝', series_steps=_steps_json(_ORGANIZATION_STEPS),
            # Организация убрана из формы позиции (2026-11-11) — ряд не показываем.
            source_type='auto', is_active=False,
        ),
    )
    return d


def remove_dynamic_achievement(code):
    """Удалить динамическое достижение по коду (при удалении объекта). Каскадом уйдут
    выданные user_achievements и agregate-строка (FK on_delete=CASCADE)."""
    dc.delete_definition_by_code(code)


def grant_event_participants(event, *, granted_by=None):
    """Завершение позиции: участникам и тим-лидерам — пересчёт достижений (в т.ч.
    «был на забеге» race_<id> по мероприятию позиции). Возвращает число новых."""
    if event.event_group_id:
        ensure_race_achievement(event.event_group)
    user_ids = set(dc.participations_qs().filter(event_day__event=event, status='attended')
                   .values_list('user_id', flat=True))
    user_ids |= set(dc.event_staff_qs().filter(event=event, staff_role='team_lead').values_list('user_id', flat=True))
    granted = 0
    for user_id in user_ids:
        user = dc.get_user_by_id(user_id)
        if user:
            granted += len(recalc_user_achievements(user))
    return granted


# Технический демо-аккаунт: волонтёр, у которого есть ВСЕ существующие достижения (все
# ступени series, все single/hidden/manual) — витрина оформления. Новые достижения
# появляются у него автоматически (grant_all_achievements зовётся при создании
# определения через dc.create_definition и командой sync_all_achievements_account).
ALL_ACHIEVEMENTS_LOGIN = 'all_achivments'


def grant_all_achievements(user, *, granted_by=None):
    """Выдать пользователю ВСЕ достижения из справочника (для техаккаунта-витрины):
    каждую ступень каждого series + каждое single/hidden/manual. Идемпотентно —
    уже выданное пропускается. Пересчитывает агрегаты затронутых достижений.
    Возвращает число новых строк."""
    granted = 0
    touched = set()
    for d in dc.get_active_definitions():
        if d.kind == 'series':
            targets = [step_value for step_value, _ in d.steps()]
        else:
            targets = [None]
        for sv in targets:
            if not dc.has_user_achievement(user, d, sv):
                dc.grant_achievement(user, d, series_value=sv, granted_by=granted_by)
                granted += 1
                touched.add(d)
    for d in touched:
        dc.recompute_achievement_stat(d)
    if granted:
        logger.info('Техаккаунт-витрина: выдано достижений user=%s count=%s', user.id, granted)
    return granted


def sync_all_achievements_account():
    """Синхронизировать техаккаунт-витрину `all_achivments`: если он существует —
    доначислить ему все недостающие достижения. Возвращает число новых строк (0, если
    аккаунта нет). Аккаунт создаётся отдельно (миграция/команда create_all_achievements)."""
    user = dc.get_user_by_login(ALL_ACHIEVEMENTS_LOGIN)
    if not user:
        return 0
    return grant_all_achievements(user)


def _card_tier(tier):
    """Дополняет карточку метаданными уровня (tier_name/tier_class) по ключу tier."""
    meta = tier_meta(tier)
    return {'tier': tier, 'tier_name': meta['name'], 'tier_class': meta['css_class']}


_MONTHS_RU = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
              'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']


def current_season_label():
    """Человекочитаемый период текущего сезона ПГАС: «сен 2025 — фев 2026» (месяц
    старта — месяц конца, годы). None, если активного сезона нет. Используется, чтобы
    у сезонных достижений в явном виде было написано, за КАКОЙ это сезон."""
    from blog.services.stats import current_season
    season = current_season()
    if not season:
        return None
    s = season.start_season
    start = f'{_MONTHS_RU[s.month][:3]} {s.year}'
    if season.end_season:
        e = season.end_season
        return f'{start} — {_MONTHS_RU[e.month][:3]} {e.year}'
    return f'{start} — …'


def build_profile_achievements(user, *, viewer_is_owner=False):
    """Данные для страницы «Мои достижения».

    Возвращает список групп: [{'group': str, 'items': [card, …]}, …].

    КАЖДАЯ КАРТОЧКА — это отдельный «значок»:
      • single/hidden/manual — одна карточка на достижение, tier берётся из
        AchievementDefinition.tier (см. TIERS);
      • series — по карточке НА КАЖДУЮ СТУПЕНЬ (10ч/50ч/…); tier ступени = её порядковый
        номер (1-я=бронза … 6-я=фиолетовый). Незакрытые ступени показываем приглушённо
        как цель (common), у скрытых — только полученные ступени.

    Видимость (achievements.md): common — показываем всегда (в т.ч. незакрытые как цель),
    hidden — только полученное. percent держателей — от «живых» (count_stats_denominator),
    у скрытых показываем абсолютное число.

    Поля карточки: code, title, description, icon, kind, visibility, earned(bool),
    earned_at, tier/tier_name/tier_class, holders_count, holders_percent; для ступеней
    series дополнительно step_value/step_label."""
    definitions = dc.get_active_definitions()
    grants = dc.get_user_achievements(user)
    # Достижения тим-лидеров (visibility=team_lead) как цели видны только тим-лидерам.
    is_lead = user.team_leader_roles.exists() or dc.event_staff_qs().filter(user=user, staff_role='team_lead').exists()
    stats_map = dc.get_achievement_stats_map()
    denom = dc.count_stats_denominator() or 0

    # Индексы выданного: для single — дата по achievement_id; для series — дата по паре
    # (achievement_id, series_value), т.к. у каждой ступени своя строка/дата.
    single_at = {}
    step_at = {}
    for g in grants:
        if g.series_value is None:
            single_at.setdefault(g.achievement_id, g.granted_at)
        else:
            step_at[(g.achievement_id, g.series_value)] = g.granted_at

    def _holders(d):
        holders = stats_map.get(d.id, 0)
        # holders учитывает всех держателей (в т.ч. служебный техаккаунт-витрину, который
        # не входит в denominator живых волонтёров), поэтому процент клампим сверху 100 —
        # «у 100% волонтёров» вместо возможных 100+% на малых числах.
        percent = min(100, round(holders * 100 / denom)) if (d.visibility in ('common', 'team_lead') and denom) else None
        return holders, percent

    groups = {}

    def _add(d, card):
        grp = d.group or 'Прочее'
        groups.setdefault(grp, {'group': grp, 'items': []})
        groups[grp]['items'].append(card)

    # Сезонные достижения — в явном виде дописываем период текущего сезона в название/
    # описание («за сезон сен 2025 — фев 2026»), чтобы было понятно, за какой это сезон.
    season_label = current_season_label()
    season_codes = {'hours_season', 'events_season'}

    def _titled(d):
        if season_label and d.code in season_codes:
            return f'{d.title} ({season_label})', f'{d.description} Текущий сезон: {season_label}.'
        return d.title, d.description

    for d in definitions:
        holders, percent = _holders(d)
        title, description = _titled(d)

        if d.kind == 'series':
            # Одна карточка на ступень. Ступень взята, если по паре (d, step) есть строка.
            for idx, (step_value, step_label) in enumerate(d.steps(), start=1):
                granted_at = step_at.get((d.id, step_value))
                earned = granted_at is not None
                if not earned and (d.visibility == 'hidden' or (d.visibility == 'team_lead' and not is_lead)):
                    continue
                card = {
                    'code': f'{d.code}:{step_value}',
                    'title': title,
                    'step_value': step_value,
                    'step_label': step_label,
                    'description': description,
                    'icon': d.icon,
                    'kind': 'series',
                    'visibility': d.visibility,
                    'earned': earned,
                    'earned_at': granted_at,
                    'holders_count': holders,
                    'holders_percent': percent,
                }
                card.update(_card_tier(idx))  # tier ступени = её порядковый номер
                _add(d, card)
        else:  # single / hidden-факт / manual
            granted_at = single_at.get(d.id)
            earned = granted_at is not None
            if not earned and (d.visibility == 'hidden' or (d.visibility == 'team_lead' and not is_lead)):
                continue
            # tier у single хранится строкой ('1'..'6'/'event'/'course'); числа приводим к int.
            raw = (d.tier or '').strip()
            tier_key = int(raw) if raw.isdigit() else (raw or None)
            card = {
                'code': d.code,
                'title': title,
                'step_value': None,
                'step_label': None,
                'description': description,
                'icon': d.icon,
                'kind': 'single',
                'visibility': d.visibility,
                'earned': earned,
                'earned_at': granted_at,
                'holders_count': holders,
                'holders_percent': percent,
            }
            card.update(_card_tier(tier_key))
            _add(d, card)

    # Порядок карточек внутри группы: полученные сверху, затем незакрытые; внутри —
    # по возрастанию уровня (ступени series идут 1→6), стабильно по названию.
    ordered = list(groups.values())

    def _sort_key(c):
        t = c['tier'] if isinstance(c['tier'], int) else 99  # уникальные (event/course) — в конец
        return (not c['earned'], t, c['title'], c['step_value'] or 0)

    for grp in ordered:
        grp['items'].sort(key=_sort_key)
    return ordered
