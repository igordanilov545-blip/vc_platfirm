"""Пакет сервис-слоя бота (распил бывшего tg_bot/services.py).

Фасад: хендлеры делают `from tg_bot import services` и `services.<func>` — все имена
реэкспортируются здесь из доменных модулей. Карта «домен → функции» — в README.md.
"""
from .users import (  # noqa: F401
    get_or_create_user, get_user, is_guest, complete_registration,
    update_profile, toggle_subscription, toggle_application_notifications, recognize_by_telegram,
    confirm_recognized_account, user_role_label, user_is_team_leader, user_is_manager,
    LOGIN_RE, validate_login, set_web_credentials, user_stats,
)
from .web_auth import (  # noqa: F401
    issue_web_login_link, verify_token_requester, confirm_telegram_verification, reject_telegram_verification,
)
from .events import (  # noqa: F401
    open_events, event_open_shifts, team_leader_events, active_events_with_organizers,
    unpublished_events, publish_event_from_bot, broadcastable_events, broadcast_event_from_bot,
)
from .applications import (  # noqa: F401
    apply_to_event, my_active_applications, get_own_application, application_cancel_eligibility,
    cancel_own_application, edit_own_application, submit_feedback, event_pending_applications,
    process_application_decision, process_application_shift_decision, application_shifts_for_decision, process_all_applications,
    event_ready_for_attendance, mark_all_attended, attendance_web_link, all_applications,
    notify_manager_processed_application,
)
from .comments import (  # noqa: F401
    add_user_comment,
)
from .feedback_queue import (  # noqa: F401
    pending_feedback_requests, mark_feedback_requested,
)
from .outbox import (  # noqa: F401
    BUTTON_TTL_SECONDS, schedule_button_removal, fetch_due_button_removals, delete_button_removal,
    MAX_ATTEMPTS, fetch_pending_outbox, mark_outbox_sent, mark_outbox_failed,
)
