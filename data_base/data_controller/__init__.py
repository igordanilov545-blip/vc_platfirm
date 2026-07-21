"""Единый слой доступа к данным (фасад пакета).

Исторически это был один файл `data_controller.py`; теперь — пакет, разбитый по
доменам, но **публичный контракт сохранён**: весь код продолжает импортировать
`from data_base.data_controller import get_user_by_telegram_id` и т.п. — эти имена
реэкспортируются здесь.

Правила слоя (см. `README.md` рядом, `documentation/agent-workflow.md §5`,
`coding-principles.md §1`):
  - Единая точка доступа к данным для бота и веб-аутентификации.
  - Только тонкий CRUD + простые фильтры; бизнес-логика — в `blog/services/*`.
  - Каждая ИЗМЕНЯЮЩАЯ функция пишет аудит в канал `vc.db` (→ `logs/db.log`).

Карта модулей:
  - `users`        — пользователи, роли (менеджер/тим-лидер), матчинг/дозаполнение
  - `orgs`         — организации, организаторы, связи, локации
  - `events`       — мероприятия, смены, категории, staff, публикация, рассылка
  - `applications` — заявки, привязка смен, участия (явка), запросы фидбека
  - `requirements` — требования меро, привязка, исключения по юзерам
  - `reference`    — фидбек, комментарии, чарн, сезоны, константы
  - `querysets`    — ленивые `*_qs()` для отчётов + скаляры (get_current_season)
  - `_base`        — логгер, generic-функции (get_full_table / create_record_generic)
"""
from ._base import get_full_table, create_record_generic, TABLE_MODEL_MAP  # noqa: F401
from .auth_tokens import (  # noqa: F401
    invalidate_user_auth_tokens, create_auth_token, get_auth_token,
    invalidate_user_verify_tokens, create_verify_token, get_verify_token,
    get_user_by_telegram_id_excluding, logout_user_web_sessions,
)
from .bot_queue import (  # noqa: F401
    create_outbox, fetch_pending_outbox, mark_outbox_sent, get_outbox, save_outbox,
    create_button_removal, fetch_due_button_removals, delete_button_removal,
)
from .analytics import (  # noqa: F401
    touch_web_session, get_web_session, set_page_view_duration, create_button_click,
    create_bot_session_ping, downtimes_since, create_downtime, delete_downtime,
)
from .users import (  # noqa: F401
    create_user, get_users,
    get_user_by_telegram_id, get_user_by_id, is_login_taken,
    get_or_create_user_by_telegram_id, update_user_fields,
    set_user_status, set_user_verification,
    sync_user_from_applications, find_candidate_user_by_telegram,
    create_manager, get_managers,
    create_team_leader, get_team_leaders,
    role_qs, create_role, revoke_roles, has_active_role, reset_all_season_counters,
)
from .orgs import (  # noqa: F401
    create_organization, get_organizations, get_organization_by_id,
    create_organizer, get_organizers,
    link_organizer_to_organization, get_organizer_links,
    create_organizer_interaction, get_organizer_interactions,
    create_location, get_locations,
)
from .events import (  # noqa: F401
    create_event_category, get_event_categories,
    create_event, get_events, get_open_events, get_active_events,
    get_unpublished_events, publish_event, get_broadcastable_events, mark_event_broadcast_sent,
    create_dobro_ru_shared_link,
    add_category_to_event, get_event_categories_map,
    create_event_shift, get_event_shifts,
    assign_staff_to_event, get_event_staff,
    get_event_by_id,
)
from .applications import (  # noqa: F401
    create_application, set_application_shifts, get_applications, get_user_active_applications,
    count_applications, count_events_with_open_recruitment,
    get_user_application_for_event, update_application_status,
    get_application_by_id, get_own_application, get_shift_by_id, get_shifts_by_ids,
    get_participation_by_id, create_application_change_log,
    ensure_shift_decision, set_shift_decision, find_matching_user,
    get_or_create_participation, delete_participations,
    create_participation, get_participations, update_participation_status,
    mark_dobro_ru_logged,
    get_participations_pending_feedback, mark_feedback_requested,
)
from .requirements import (  # noqa: F401
    create_requirement, get_requirements,
    add_requirement_to_event, get_event_requirements_map,
    create_user_exception, get_user_exceptions,
)
from .reference import (  # noqa: F401
    create_churn_history, get_churn_history, create_churn_log, resolve_incidents,
    create_incident, resolve_incident_by_id,
    create_user_comment, get_user_comments,
    create_feedback, get_feedbacks, has_feedback, update_feedback_comment,
    create_season, get_seasons,
    get_const, get_all_consts, get_or_create_pgas_template,
)
from .querysets import (  # noqa: F401
    events_qs, event_shifts_qs, participations_qs, applications_qs, application_shift_decisions_qs,
    event_staff_qs, users_qs, users_ranked_qs, feedbacks_qs, managers_qs, team_leaders_qs,
    dobro_ru_shared_links_qs, get_current_season,
    locations_qs, organizations_qs, organizers_qs, event_categories_qs, requirements_qs,
    seasons_qs, user_requirement_exceptions_qs, incidents_qs, churn_history_qs,
    application_change_logs_qs, user_comments_qs, organizer_interactions_qs,
    web_sessions_qs, web_page_views_qs, button_click_events_qs, bot_session_pings_qs,
)

# Публичный контракт слоя — тот же, что был у монолитного data_controller.py.
__all__ = [
    'create_user', 'get_users',
    'get_user_by_telegram_id', 'get_user_by_id', 'is_login_taken',
    'get_or_create_user_by_telegram_id', 'update_user_fields',
    'set_user_status', 'set_user_verification',
    'sync_user_from_applications', 'find_candidate_user_by_telegram',
    'create_manager', 'get_managers',
    'create_team_leader', 'get_team_leaders',
    'role_qs', 'create_role', 'revoke_roles', 'has_active_role', 'reset_all_season_counters',
    'create_organization', 'get_organizations', 'get_organization_by_id',
    'create_organizer', 'get_organizers',
    'link_organizer_to_organization', 'get_organizer_links',
    'create_organizer_interaction', 'get_organizer_interactions',
    'create_location', 'get_locations',
    'create_event_category', 'get_event_categories',
    'create_event', 'get_events', 'get_open_events', 'get_active_events',
    'get_unpublished_events', 'publish_event', 'get_broadcastable_events', 'mark_event_broadcast_sent',
    'create_dobro_ru_shared_link',
    'add_category_to_event', 'get_event_categories_map',
    'create_event_shift', 'get_event_shifts',
    'assign_staff_to_event', 'get_event_staff',
    'create_application', 'set_application_shifts', 'get_applications', 'get_user_active_applications',
    'count_applications', 'count_events_with_open_recruitment',
    'get_user_application_for_event', 'update_application_status',
    'get_application_by_id', 'get_own_application', 'get_shift_by_id', 'get_shifts_by_ids',
    'get_participation_by_id', 'create_application_change_log',
    'ensure_shift_decision', 'set_shift_decision', 'find_matching_user',
    'get_or_create_participation', 'delete_participations',
    'create_participation', 'get_participations', 'update_participation_status',
    'mark_dobro_ru_logged',
    'get_participations_pending_feedback', 'mark_feedback_requested',
    'create_churn_history', 'get_churn_history', 'create_churn_log', 'resolve_incidents',
    'create_incident', 'resolve_incident_by_id',
    'create_user_comment', 'get_user_comments',
    'create_feedback', 'get_feedbacks', 'has_feedback', 'update_feedback_comment',
    'create_requirement', 'get_requirements',
    'add_requirement_to_event', 'get_event_requirements_map',
    'create_user_exception', 'get_user_exceptions',
    'create_season', 'get_seasons',
    'get_const', 'get_all_consts', 'get_or_create_pgas_template',
    # Базовые queryset'ы для аналитики (отчёты) + скалярные срезы.
    'events_qs', 'event_shifts_qs', 'participations_qs', 'applications_qs', 'application_shift_decisions_qs',
    'event_staff_qs', 'users_qs', 'users_ranked_qs', 'feedbacks_qs', 'managers_qs', 'team_leaders_qs',
    'dobro_ru_shared_links_qs', 'get_current_season', 'get_event_by_id',
    'locations_qs', 'organizations_qs', 'organizers_qs', 'event_categories_qs', 'requirements_qs',
    'seasons_qs', 'user_requirement_exceptions_qs', 'incidents_qs', 'churn_history_qs',
    'application_change_logs_qs', 'user_comments_qs', 'organizer_interactions_qs',
    'web_sessions_qs', 'web_page_views_qs', 'button_click_events_qs', 'bot_session_pings_qs',
    'get_full_table', 'create_record_generic',
    'invalidate_user_auth_tokens', 'create_auth_token', 'get_auth_token',
    'invalidate_user_verify_tokens', 'create_verify_token', 'get_verify_token',
    'get_user_by_telegram_id_excluding', 'logout_user_web_sessions',
    'create_outbox', 'fetch_pending_outbox', 'mark_outbox_sent', 'get_outbox', 'save_outbox',
    'create_button_removal', 'fetch_due_button_removals', 'delete_button_removal',
    'touch_web_session', 'get_web_session', 'set_page_view_duration', 'create_button_click',
    'create_bot_session_ping', 'downtimes_since', 'create_downtime', 'delete_downtime',
]
