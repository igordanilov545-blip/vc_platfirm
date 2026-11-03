# `blog/forms/` — путеводитель по формам

Бывший `blog/forms.py` (1089 строк, 34 класса) распилен по доменам. Фасад
`__init__.py` реэкспортит все формы, поэтому `from blog.forms import <ФормаForm>`
работает как раньше (основной потребитель — `blog/views/_common.py`).

## С чем работаешь → куда смотреть

| Домен | Файл | Формы |
|---|---|---|
| **Приглашения** | [`role_invitations.py`](role_invitations.py) | `RoleInvitationForm`: роль тим-лидера/менеджера и срок действия ссылки в часах |
| **Вход / регистрация** | [`auth.py`](auth.py) | `LoginForm`, `RegisterForm` |
| **Планы FaP / Google Таблицы** | [`event_sheets.py`](event_sheets.py) | `EventSheetImportForm`, `GoogleSheetsConnectionForm`, `SheetTeamLeaderBindingForm`; загрузка при создании — `EventGroupForm` в events.py |
| **Доступ к сканеру QR** | [`qr_attendance.py`](qr_attendance.py) | `ScannerGrantForm` (пользователь + мероприятие), общий `_modal_form.html` |
| **Справочники** (локации/организации/организаторы/категории/требования/константы/сезоны) | [`references.py`](references.py) | `LocationForm`, `OrganizationForm`, `OrganizerForm`, `CategoryForm`, `RequirementForm`, `RequirementEditForm`, `RequirementExceptionForm`, `ConstForm`, `SeasonForm` + их `Quick*`-версии |
| **Мероприятия** | [`events.py`](events.py) | `EventForm`, `EventShiftForm`, `EventCommentForm`, `EventFeedbackForm`, поля выбора `TeamLeadChoiceField`/`ManagerChoiceField` |
| **Заявки / явка** | [`applications.py`](applications.py) | `ApplicationForm`, `ApplicationCancelForm`, `ParticipationForm`, `ExcelImportForm`, виджет `ShiftMultipleSelect` |
| **Профиль** | [`profiles.py`](profiles.py) | `ProfileForm` (+ alias `ProfileCompletionForm`), `ExternalExperienceForm`, `UserCommentForm`, `QuickVolunteerForm` |
| **Роли / капча** | [`roles.py`](roles.py) | `RoleUsersForm`, `CaptchaForm`, поле `MultipleHiddenIntegerField` |
| **Общие импорты** | [`_common.py`](_common.py) | `forms`, утилиты времени, все модели (для `from ._common import *`) |

## Как добавлять

- Новая форма → в подходящий доменный файл; начни файл с `from ._common import *`
  (даёт `forms`, модели, утилиты времени).
- **Реэкспортируй** новую форму в [`__init__.py`](__init__.py), иначе
  `from blog.forms import …` её не найдёт.
- Множественный выбор — через готовые поля/виджеты (`ModelMultipleChoiceField` +
  chip-select, `MultipleHiddenIntegerField` + user-picker), не изобретай свой
  (agent-workflow §4, audit-reuse.md).
