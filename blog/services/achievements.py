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


# ----------------------------------------------------------------------
# Эвалуаторы прогресса. Каждый принимает User, возвращает int (series) или bool (single).
# Держим их «тонкими» и на ORM напрямую (сервисный слой это допускает): считаем по
# фактическим данным, без кэша — пересчёт редкий и точечный.
# ----------------------------------------------------------------------
def _attended(user):
    return dc.participations_qs().filter(user=user, status='attended')


def ev_total_hours(user):
    return user.total_hours or 0


def ev_total_events(user):
    # Разные мероприятия с явкой (а не смены): total_event_count считает участия-смены,
    # для достижения «N мероприятий» логичнее уникальные меро.
    return _attended(user).values('event_day__event').distinct().count()


def ev_season_hours(user):
    return user.season_hours or 0


def ev_season_events(user):
    return user.season_event_count or 0


def ev_categories_diversity(user):
    return (
        _attended(user)
        .values('event_day__event__category_map__category')
        .exclude(event_day__event__category_map__category__isnull=True)
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
    """Число мероприятий, где пользователь был тим-лидером (по назначениям EventStaff)."""
    return dc.event_staff_qs().filter(user=user, staff_role='team_lead').values('event').distinct().count()


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
}


def progress_for(user, definition):
    """Текущий прогресс пользователя по auto-достижению (int для series, bool для single).
    None — если для кода нет эвалуатора (движок такое достижение не считает)."""
    fn = EVALUATORS.get(definition.code)
    if fn is None:
        return None
    return fn(user)


def recalc_user_achievements(user, *, notify=False):
    """Пересчитать и доначислить auto-достижения пользователя. Возвращает список
    новых UserAchievement (для попапа/уведомления — на этом этапе просто возвращаем).

    Идемпотентно: повторный вызов без изменения данных ничего не выдаёт. Ручные
    (manual_grant) достижения не трогаем. notify — задел на пинг о новом достижении
    (реализуется отдельно), сейчас параметр только прокидывает намерение в лог."""
    newly = []
    touched = set()
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

    if newly:
        logger.info(
            'Достижения доначислены: user=%s count=%s notify=%s codes=%s',
            user.id, len(newly), notify, [ua.achievement.code for ua in newly],
        )
    return newly


def build_profile_achievements(user, *, viewer_is_owner=False):
    """Данные для блока достижений в профиле волонтёра.

    Возвращает список групп: [{'group': str, 'items': [card, …]}, …], где card —
    достижение с прогрессом для рендера карточки (achievements.md §Дополнительно,
    «Видимость»):
      • common (общие) — показываем ВСЕГДА, даже незакрытые (приглушённо);
      • hidden (скрытые) — только полученные;
    поля карточки: title, description, icon, earned(bool), earned_at, current_step,
    next_step, progress, holders_percent/holders_count.

    percent считается от «живых» держателей (dc.count_stats_denominator) — не размываем
    процент выпускниками (см. док). У скрытых показываем абсолютное число держателей."""
    definitions = dc.get_active_definitions()
    grants = dc.get_user_achievements(user)
    stats_map = dc.get_achievement_stats_map()
    denom = dc.count_stats_denominator() or 0

    # Собираем по каждому определению: максимально взятую ступень и дату (для series) или
    # факт (для single). У series берём наибольший series_value как «текущую» ступень.
    by_def = {}
    for g in grants:
        cur = by_def.get(g.achievement_id)
        val = g.series_value if g.series_value is not None else 0
        if cur is None or val > cur['value']:
            by_def[g.achievement_id] = {'value': val, 'granted_at': g.granted_at}
        # earliest granted_at по определению — для single это единственная строка;
        # для series хотим дату ПОСЛЕДНЕЙ взятой ступени (уже покрыто выбором max value).

    groups = {}
    for d in definitions:
        earned_info = by_def.get(d.id)
        earned = earned_info is not None
        if d.visibility == 'hidden' and not earned:
            continue  # скрытые до получения не показываем

        card = {
            'code': d.code,
            'title': d.title,
            'description': d.description,
            'icon': d.icon,
            'kind': d.kind,
            'visibility': d.visibility,
            'earned': earned,
            'earned_at': earned_info['granted_at'] if earned else None,
        }

        if d.kind == 'series':
            steps = d.steps()
            current = earned_info['value'] if earned else 0
            # Следующая невзятая ступень (для подписи «сделай X»).
            next_step = next((s for s in steps if s[0] > current), None)
            card['current_step'] = current
            card['next_step_value'] = next_step[0] if next_step else None
            card['next_step_label'] = next_step[1] if next_step else None
            card['max_step'] = steps[-1][0] if steps else None

        holders = stats_map.get(d.id, 0)
        card['holders_count'] = holders
        if d.visibility == 'common' and denom:
            card['holders_percent'] = round(holders * 100 / denom)
        else:
            card['holders_percent'] = None

        groups.setdefault(d.group or 'Прочее', {'group': d.group or 'Прочее', 'items': []})
        groups[d.group or 'Прочее']['items'].append(card)

    # Порядок групп — как в определениях (по первому появлению), карточки внутри —
    # полученные сверху, затем незакрытые (общие цели), стабильно по названию.
    ordered = list(groups.values())
    for grp in ordered:
        grp['items'].sort(key=lambda c: (not c['earned'], c['title']))
    return ordered
