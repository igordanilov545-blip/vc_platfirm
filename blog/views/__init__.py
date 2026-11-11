"""Пакет вьюх платформы ВЦ (распил бывшего blog/views.py).

Фасад обратной совместимости: `urls.py` делает `from . import views` и
`views.<имя>` — все вьюхи реэкспортируются здесь из доменных модулей, поэтому
urls.py и прочий код не меняются. Карта «домен → что внутри» — в README.md.
"""
from ._common import healthz  # noqa: F401
from .settings_hub import appearance_update  # noqa: F401
from .legacy_migration import legacy_migration, legacy_migration_base, legacy_migration_group, legacy_migration_job  # noqa: F401
from .profile_actualize import profile_actualize  # noqa: F401
from .volunteer_wishes import (  # noqa: F401
    volunteer_wishes, volunteer_wish_add, volunteer_wish_edit, volunteer_wish_delete,
    volunteer_wish_take, volunteer_wish_take_shift, volunteer_wish_untake,
)
from .role_invitations import role_invitation_list, role_invitation_detail, role_invitation_create, role_invitation_accept, role_invitation_revoke  # noqa: F401
from .event_sheets import (  # noqa: F401
    event_sheet, event_sheet_link, event_sheet_sync, event_sheet_export,
    google_sheets_settings, sheet_team_leader_bind,
)
from .qr_attendance import (  # noqa: F401
    personal_qr, personal_qr_png, qr_scanner, qr_scan, qr_mark, qr_commit, qr_enroll,
    qr_scanner_grant, qr_scanner_revoke,
)
from .quick_create import (  # noqa: F401
    quick_create_location, quick_create_organization, quick_create_organizer, quick_create_category,
    quick_create_perk, quick_create_volunteer, quick_create_requirement,
)
from .auth import (  # noqa: F401
    login_view, register_view, telegram_login_callback, tg_link_login,
    logout_view, webapp_entry, webapp_auth, verify_telegram_start,
)
from .profiles import (  # noqa: F401
    profile_edit, complete_profile, profile_detail, profile_achievements, profile_stats, profile_comment_add,
    letter_view, letters_download_all, external_experience_add, external_experience_edit, external_experience_delete,
    public_experience, profile_admin_edit, profile_admin_delete,
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
    event_group_create, event_group_edit, event_group_detail, event_group_roster_export, position_roster_export,
    public_event_list, public_event_detail, event_list, event_detail,
    event_comment_add, event_change_log_mark_read, event_feedback_add, event_create,
    event_edit, event_delete, event_publish, event_broadcast,
    shift_toggle_recruit, shift_toggle_attendance_confirmed, event_reopen, event_close,
    event_dobro_toggle, event_shift_add, event_shift_edit, event_shift_delete, event_function_create,
)
from .participations import (  # noqa: F401
    participation_set_status, participation_set_hours, participation_edit, participation_handout,
)
from .applications import (  # noqa: F401
    application_create, application_manual_create, application_edit, application_cancel,
    event_shifts_json, application_process, application_shift_process, shift_decision_role, shift_applications_approve_all,
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
    category_edit, category_delete, position_template_create, position_template_edit, position_template_delete,
    perk_list, perk_create, perk_edit, perk_delete,
    requirement_exception_add, requirement_exception_remove,
)
from .letters import (  # noqa: F401
    letter_template_list, letter_template_create, letter_template_editor,
    letter_template_background, letter_template_upload_bg, letter_template_save_fields,
    letter_template_preview, letter_template_delete,
    letter_font_upload, letter_font_delete, letter_font_file,
)
from .analytics import (  # noqa: F401
    analytics_ping, analytics_leave, analytics_click, analytics_dashboard,
    analytics_online_data, analytics_clicks_data, analytics_load_data, analytics_duration_data,
    analytics_top_pages_data, analytics_top_bot_commands_data, analytics_downtimes_data, analytics_downtime_add,
    analytics_downtime_delete, analytics_log_download, analytics_log_tail,
)
from .demo import demo_page  # noqa: F401  # fest_platform: раздача независимой демки под /demo/
