# `blog/views/` — путеводитель по вьюхам

Бывший монолит `blog/views.py` (4373 строки) распилен по **бизнес-доменам**. Роутинг
(`blog/urls.py`) не изменился: `__init__.py` — фасад, реэкспортит все вьюхи, поэтому
`views.<имя>` работает как раньше.

## С чем работаешь → куда смотреть

| Работаешь с… | Файл | Что внутри |
|---|---|---|
| **Приглашениями с выдачей роли** | [`role_invitations.py`](role_invitations.py) | Менеджер создаёт/отзывает ссылки; `/join/` возвращает через вход и выдаёт роль; срок и ACL — services/role_invitations.py |
| **Планом FaP и Google Таблицами** | [`event_sheets.py`](event_sheets.py) | Страница плана, загрузка/привязка, явный обмен, XLSX, подключение Google и привязка ТЛ; бизнес-логика — services/event_sheets.py |
| **Вход / регистрация / Telegram-вход / Mini App** | [`auth.py`](auth.py) | `login_view`, `register_view`, `logout_view`, `telegram_login_callback`, `tg_link_login`, `webapp_entry`, `webapp_auth`, `verify_telegram_start` |
| **Мероприятиями** (карточка, CRUD, публикация, рассылка, закрытие, смены) | [`events.py`](events.py) | `event_list`, `event_detail`, `event_create/edit/delete`, `event_publish`, `event_broadcast`, `event_close/reopen`, `event_shift_add/edit/delete`, `shift_toggle_*`, `event_feedback_add`, `event_comment_add`, публичные витрины |
| **Заявками** (подача, обработка, ручное добавление, отмена, импорт Excel) | [`applications.py`](applications.py) | `application_create`, `application_manual_create`, `application_edit`, `application_cancel`, `application_process[_all]`, `application_shift_process`, `shift_applications_approve_all`, `import_preview/commit`, `pending_applications` |
| **Явкой / часами** волонтёра на смене | [`participations.py`](participations.py) | `participation_set_status`, `participation_set_hours`, `participation_edit` |
| **Личным QR / регистрацией на сменах** | [`qr_attendance.py`](qr_attendance.py) | `personal_qr[_png]`, `qr_scanner`, `qr_scan`, `qr_mark`, `qr_enroll` (ручная запись из карточки), `qr_scanner_grant/revoke`; правила — `blog/services/qr_attendance.py` |
| **Профилем волонтёра** (свой/чужой, комментарии, опыт, письма) | [`profiles.py`](profiles.py) | `profile_detail`, `profile_edit`, `complete_profile`, `profile_comment_add`, `letter_view`, `external_experience_*`, `public_experience` |
| **Списком волонтёров / блокировкой** | [`volunteers.py`](volunteers.py) | `user_list`, `users_picker_data`, `user_blacklist`, `user_unblacklist` |
| **Справкой ПГАС / верификацией** | [`pgas.py`](pgas.py) | `pgas_certificate_download/issue`, `pgas_template_download`, `pgas_request_verification`, `pgas_verify_user`, `pgas_unverify_user` |
| **Организациями / организаторами / локациями** | [`organizations.py`](organizations.py) | `location_*`, `organizations_list`, `organization_*`, `organizer_*` (list-вьюхи — панели хаба настроек) |
| **Хабом настроек** (константы, сезоны, роли, требования, категории) | [`settings_hub.py`](settings_hub.py) | `settings_view`, `const_edit`, `requirement_*`, `category_*`, `requirement_exception_*`, константы `SETTINGS_TABS`/`ROLE_ACTIONS` |
| **Отчётами / дашбордом / Добро.ру / экспортами** | [`reports.py`](reports.py) | `report_period`, `report_*_pdf`, `report_*_export`, `report_bundle`, `dobro_page`, `report_dobro_*`, `_dobro_rows`, `REPORT_VIEWS/TABLES` |
| **Главной страницей / инцидентами** | [`dashboard.py`](dashboard.py) | `dashboard`, `incident_resolve` |
| **Быстрым созданием справочника из формы** (AJAX «＋») | [`quick_create.py`](quick_create.py) | `quick_create_location/organization/organizer/category/volunteer/requirement` |
| **Технической аналитикой** (дашборд нагрузки, логи, даунтаймы) | [`analytics.py`](analytics.py) | `analytics_dashboard`, `analytics_*_data`, `analytics_ping/leave/click`, `analytics_downtime_*`, `analytics_log_*` |
| **Общей инфраструктурой представления** | [`_common.py`](_common.py) | `is_ajax`, `modal_form_response`, капча-2FA (`render_captcha_modal`), `_safe_next`, `_referer_or`, `healthz`, а также shared-импорты (django, модели, формы, сервисы, `dc`, `logger`) |

## Как писать код здесь

1. **Сначала найди домен** по таблице выше — скорее всего нужная вьюха/хелпер уже есть,
   переиспользуй её, а не пиши второй раз.
2. **Новая вьюха** → в подходящий доменный файл. Начни файл с `from ._common import *`
   (даёт django-shortcuts, модели, формы, сервисы, `dc`, `logger`, хелперы).
3. **Доступ к данным — через `dc`** (`data_controller`), не через `Model.objects`
   (agent-workflow §5). Исключения — `get_object_or_404(...)` и техническая аналитика.
4. **Бизнес-логика — в `blog/services/*`**, вьюха тонкая: разобрала вход → вызвала
   сервис → отрендерила (coding-principles §1).
5. **Зарегистрируй маршрут** в `blog/urls.py` и **реэкспортируй** вьюху в
   [`__init__.py`](__init__.py) (иначе `views.<имя>` её не найдёт).
6. Общий хелпер, нужный нескольким доменам, живёт в `_common.py`; если он специфичен
   для домена, но нужен ещё одному — импортируй его явно (как `dashboard.py` берёт
   `_published_active_events` из `events.py`).
