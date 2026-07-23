"""Пакет вьюх платформы ВЦ (распил бывшего blog/views.py).

Фасад обратной совместимости: `urls.py` делает `from . import views` и
`views.<имя>` — все вьюхи реэкспортируются здесь из доменных модулей, поэтому
urls.py и прочий код не меняются. Карта «домен → что внутри» — в README.md.
"""
from ._common import healthz  # noqa: F401
from .quick_create import (  # noqa: F401
    quick_create_location, quick_create_organization, quick_create_organizer, quick_create_category,
    quick_create_perk, quick_create_volunteer, quick_create_requirement,
)
from .auth import (  # noqa: F401
    login_view, register_view, telegram_login_callback, tg_link_login,
    logout_view, webapp_entry, webapp_auth, verify_telegram_start,
)
from .profiles import (  # noqa: F401
    profile_edit, complete_profile, profile_detail, profile_comment_add,
    letter_view, external_experience_add, external_experience_edit, external_experience_delete,
    public_experience,
)
from .volunteers import (  # noqa: F401
    user_list, users_picker_data, user_blacklist, user_unblacklist,
)
from .pgas import (  # noqa: F401
    pgas_certificate_download, pgas_certificate_issue, pgas_template_download, pgas_request_verification,
    pgas_verify_user, pgas_unverify_user,
)
from .dashboard import (  # noqa: F401
    dashboard, incident_resolve,
)
from .events import (  # noqa: F401
    public_event_list, public_event_detail, event_list, event_detail,
    event_comment_add, event_change_log_mark_read, event_feedback_add, event_create,
    event_edit, event_delete, event_publish, event_broadcast,
    shift_toggle_recruit, shift_toggle_attendance_confirmed, event_reopen, event_close,
    event_dobro_toggle, event_shift_add, event_shift_edit, event_shift_delete,
)
from .participations import (  # noqa: F401
    participation_set_status, participation_set_hours, participation_edit,
)
from .applications import (  # noqa: F401
    application_create, application_manual_create, application_edit, application_cancel,
    event_shifts_json, application_process, application_shift_process, shift_applications_approve_all,
    application_process_all, import_preview, import_commit, pending_applications,
)
from .reports import (  # noqa: F401
    report_period, report_events_search, report_period_export, report_period_pdf,
    report_event_export, report_event_pdf, report_person_pdf, report_volunteers_pdf,
    report_volunteers_export, report_organization_pdf, report_people_search, report_organizations_search,
    report_complex_pdf, dobro_page, report_dobro_toggle, report_dobro_set_link,
    report_dobro_export, report_bundle,
)
from .organizations import (  # noqa: F401
    location_list, location_create, location_edit, organizations_list,
    organization_create, organization_edit, organization_detail, organizer_list,
    organizer_create, organizer_edit, organizer_detail,
)
from .settings_hub import (  # noqa: F401
    const_edit, settings_view, requirement_list, requirement_create,
    requirement_edit, requirement_delete, category_list, category_create,
    category_edit, category_delete,
    perk_list, perk_create, perk_edit, perk_delete,
    requirement_exception_add, requirement_exception_remove,
)
from .analytics import (  # noqa: F401
    analytics_ping, analytics_leave, analytics_click, analytics_dashboard,
    analytics_online_data, analytics_clicks_data, analytics_load_data, analytics_duration_data,
    analytics_top_pages_data, analytics_top_bot_commands_data, analytics_downtimes_data, analytics_downtime_add,
    analytics_downtime_delete, analytics_log_download, analytics_log_tail,
)
