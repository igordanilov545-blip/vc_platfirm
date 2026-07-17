# Аудит переиспользования кода: выбор «n из m» и общие хелперы

_Дата: 2026-07-17. Метод: программный AST-обход (`ast`) всех `*.py` вне `.venv/migrations`, плюс grep по шаблонам и JS._

## TL;DR

Определено **681** функций/методов. Настоящих дублей логики немного, но **паттерн множественного выбора «n из m» реализован пятью разными способами**, из которых один — хороший (chip-select поверх `<select multiple>` + `ModelMultipleChoiceField`). Остальные — от «оправданно другого» (user-picker для тысяч пользователей, toggle-клавиатура бота) до «скопировано и разошлось» (manual-форма рендерит тысячи `<option>`, PGAS-справка — сырые checkbox + `getlist`). Плюс россыпь одноразовых форматтеров даты.

---

## 1. Карта паттернов выбора «n из m»

| # | Где | Механизм (фронт) | Механизм (бэк) | Вердикт |
|---|-----|------------------|----------------|---------|
| 1 | Категории, требования, тим-лидеры, менеджер, **смены заявки** ([_event_form_body.html](../blog/templates/blog/partials/_event_form_body.html), [_application_form_body.html](../blog/templates/blog/partials/_application_form_body.html)) | `data-chip-select` → `initCategoryChips` поверх скрытого `<select multiple>` | `ModelMultipleChoiceField` (+ `ShiftMultipleSelect` для `data-closed`) | ✅ **Эталон** |
| 2 | Назначение/снятие ролей, требования-исключения ([_role_section.html](../blog/templates/blog/partials/_role_section.html), [_settings_requirements.html](../blog/templates/blog/partials/_settings_requirements.html)) | `data-user-picker` → AJAX `/users/picker-data/`, общая модалка | `MultipleHiddenIntegerField` / `RoleUsersForm` | ✅ Оправданно другой (тысячи юзеров) |
| 3 | Выбор смен в боте ([volunteer.py](../tg_bot/handlers/volunteer.py), [keyboards.py](../tg_bot/keyboards.py)) | `shift_selection_keyboard` + toggle `cb_shift_pick` (✅ в label, set в FSM) | `services.apply_to_event(shift_ids)` | ⚠️ Консистентен внутри бота, но toggle-логика захардкожена только под смены |
| 4 | Ручное добавление волонтёров менеджером ([_application_manual_form_body.html](../blog/templates/blog/partials/_application_manual_form_body.html)) | `data-chip-select="manual-volunteers-select"` (chip-select #1) | сырой `request.POST.getlist('users')` ([views.py:1868](../blog/views.py#L1868)) | ❌ **Конфликт**: chip-select #1 рендерит **всех волонтёров** в `<option>` — ровно то, ради чего сделали #2 |
| 5 | Выбор мероприятий для справки ПГАС ([pgas_certificate_issue.html](../blog/templates/blog/pgas_certificate_issue.html)) | сырые `<input type="checkbox" name="event_ids">` в таблице | сырой `getlist('event_ids')` ([views.py:483](../blog/views.py#L483)) | ❌ **Свой велосипед**, ноль переиспользования |

**Вывод.** Целевой инвариант: *любой* множественный выбор идёт через **один из двух** легитимных виджетов —
- **chip-select** (`ModelMultipleChoiceField` + `[data-chip-select]`) — когда вариантов десятки (смены, категории, требования);
- **user-picker** (`MultipleHiddenIntegerField` + `[data-user-picker]`) — когда вариантов сотни/тысячи (люди).

Случаи #4 и #5 нарушают это; #3 — кандидат на обобщение toggle-конструктора.

---

## 2. Дубли и разнобой хелперов

Реальные (не Django-методы `__str__/save/clean/handle`):

- **Форматтеры даты — 7+ независимых копий**, каждая чуть по-своему:
  `_fmt_dt` ([report_builders.py:13](../blog/services/report_builders.py#L13), [report_exports.py:17](../blog/services/report_exports.py#L17) — почти идентичны),
  `_fmt_day` ([pgas_certificate.py:148](../blog/services/pgas_certificate.py#L148), [custom_tags.py:55](../blog/templatetags/custom_tags.py#L55)),
  `_fmt_date`, `_fmt_dt_local`, `_days_ago` ([reports.py](../blog/services/reports.py)), `_hm` ([event_timeline.py](../blog/services/event_timeline.py)).
  → свести в `blog/services/formatting.py` (`fmt_dt`, `fmt_date`, `fmt_day`).
- `mark_feedback_requested` — в [data_controller.py:720](../data_base/data_controller.py#L720) **и** [services.py:796](../tg_bot/services.py#L796): проверить, не разошлась ли логика между слоями.
- Ложные срабатывания (норма): `__init__`×14, `__str__`×17, `save`×6, `handle`×16, `add_arguments`×9, `compute_status`×2 (Event vs EventShift — разные модели).

---

## 3. Топ переиспользуемых функций (источник истины)

`modal_form_response` — 46 вызовов (единый ответ AJAX-модалок; см. [[modal-redirect-gotcha]]), `actor` — 41, `is_manager` — 22, `answer_with_expiring_keyboard` — 18, `can_process_applications` — 18, `recalc_user_aggregates` — 11. Эти уже правильно централизованы — их трогать не нужно, на них равняемся.

---

## 4. План унификации (см. artifact)

Фазы: (0) свести форматтеры, (1) `_application_manual_form_body` → user-picker, (2) PGAS-справка → chip-select, (3) обобщить toggle-клавиатуру бота, (4) закрепить partial `_multiselect_chips.html` и правило в CLAUDE.md.
