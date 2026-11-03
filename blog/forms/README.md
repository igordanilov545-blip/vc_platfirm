# `blog/forms/` — путеводитель по формам

Бывший `blog/forms.py` (1089 строк, 34 класса) распилен по доменам. Фасад
`__init__.py` реэкспортит все формы, поэтому `from blog.forms import <ФормаForm>`
работает как раньше (основной потребитель — `blog/views/_common.py`).

## С чем работаешь → куда смотреть

| Домен | Файл | Формы |
|---|---|---|
| **Приглашения** | [`role_invitations.py`](role_invitations.py) | `RoleInvitationForm`: роль тим-лидера/менеджера и срок действия ссылки в часах |
| **Загрузка базы** | [`legacy_import.py`](legacy_import.py) | `LegacyBaseUploadForm` (.xlsx) и `LegacyDatesForm`: общие date-picker; неизвестные даты по умолчанию 01.01.2026. Ошибки дат доступны через error_summary сверху формы |
| **Вход / регистрация** | [`auth.py`](auth.py) | `LoginForm`, `RegisterForm` |
| **Планы FaP / Google Таблицы** | [`event_sheets.py`](event_sheets.py) | `EventSheetImportForm`, `GoogleSheetsConnectionForm`, `SheetTeamLeaderBindingForm`; загрузка при создании — `EventGroupForm` в events.py |
| **Доступ к сканеру QR** | [`qr_attendance.py`](qr_attendance.py) | `ScannerGrantForm` (пользователь + мероприятие), общий `_modal_form.html` |
| **Справочники** (локации/организации/организаторы/категории/требования/константы/сезоны) | [`references.py`](references.py) | `LocationForm`, `OrganizationForm`, `OrganizerForm`, `CategoryForm`, `RequirementForm`, `RequirementEditForm`, `RequirementExceptionForm`, `ConstForm`, `SeasonForm` + их `Quick*`-версии |
| **Мероприятия** | [`events.py`](events.py) | `EventForm`, `EventShiftForm`, `EventCommentForm`, `EventFeedbackForm`, поля выбора `TeamLeadChoiceField`/`ManagerChoiceField` |
| **Заявки / явка** | [`applications.py`](applications.py) | `ApplicationForm`, `ApplicationCancelForm`, `ParticipationForm`, `ExcelImportForm`, виджет `ShiftMultipleSelect` |
| **Профиль** | [`profiles.py`](profiles.py) | `ProfileForm` (+ alias `ProfileCompletionForm`): анкета, способы связи чекбоксами (минимум один), да/нет, размер XS–XXXL, текст до 255; `ExternalExperienceForm`, `UserCommentForm`, `QuickVolunteerForm` |
| **Роли / капча** | [`roles.py`](roles.py) | `RoleUsersForm`, `CaptchaForm`, поле `MultipleHiddenIntegerField` |
| **Общие импорты** | [`_common.py`](_common.py) | `forms`, утилиты времени, все модели (для `from ._common import *`) |

## Как добавлять

`ProfileForm.sections` использует три группы из
`blog/services/profile_completion.py::PROFILE_SECTIONS`. Там же задан состав всей
анкеты (20 полей); `form.completion` считает валидные ответы bound-формы либо
сохранённые данные. Общий партиал `_profile_form_field.html` сохраняет чекбоксы,
справку футболок, ошибки и поведение лимита текста во всех разделах.

Соцсети нормализуются общим `services/social_profiles.py`: VK/Instagram сохраняются
как username (поля `VK_username`/`instagram_url`), Telegram — без @. Полные ссылки
возвращают свойства пользователя `vk_profile_url` и `instagram_profile_url`;
старые сохранённые URL также поддерживаются. Импорт не меняет существующие анкеты.
Если VK/Instagram не распознаны, `social_value` сохраняет исходный текст; форма
редактирования его не стирает. `social_username` остаётся строгим распознавателем
для ссылок и матчинга; нераспознанное значение отображается простым текстом.

- Новая форма → в подходящий доменный файл; начни файл с `from ._common import *`
  (даёт `forms`, модели, утилиты времени).
- **Реэкспортируй** новую форму в [`__init__.py`](__init__.py), иначе
  `from blog.forms import …` её не найдёт.
- Множественный выбор — через готовые поля/виджеты (`ModelMultipleChoiceField` +
  chip-select, `MultipleHiddenIntegerField` + user-picker), не изобретай свой
  (agent-workflow §4, audit-reuse.md).
