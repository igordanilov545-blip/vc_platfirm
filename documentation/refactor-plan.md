# План рефакторинга «расчистка говнокода»

> Живой документ-трекер большой чистки кодовой базы (заменяет утраченный
> `hot_fix_1.md`, на который ссылается `README.md` и `coding-principles.md §5`).
> Ведётся по ходу работы: сделанное помечается ✅ с датой и коммитом.
> Правила, по которым чистим, — [agent-workflow.md](agent-workflow.md) и
> [coding-principles.md](coding-principles.md). Этот файл — про *что именно* грязно и
> *в каком порядке* чиним.

Дата старта: 2026-07-20. Ведущий агент: opus.

---

## 0. Что сейчас сделано ебано (диагноз)

Замеры на 2026-07-20 (`grep`/`wc` по репозиторию, без `.venv`):

| Файл | Размер | Проблема |
|---|---|---|
| `blog/views.py` | **4372 строки, 161 функция** | Монолит. Внутри — бизнес-логика, ветвления ACL, пересчёты, ручной разбор `getlist`. **79 прямых `.objects.`** + `from blog.models import ...`. Нарушает слоистость (coding-principles §1). |
| `blog/templates/blog/base.html` | **2876 строк** | Почти весь JS проекта инлайном в `<head>`/`<body>` (`initCategoryChips`, `initDatepickers`, `CalendarUtils`, модалки, тосты, пикеры…). Должно жить в подключаемых `static/blog/js/*`. |
| `data_base/data_controller.py` | **953 строки, 84 функции** | Один плоский файл. Логически уже сгруппирован (create/get/update/qs), но не разбит на модули по доменам. Есть кандидаты в дубли (`mark_feedback_requested` дублируется с `tg_bot/services.py`). |
| `blog/forms.py` | **1089 строк** | Все формы в одном файле. |
| `blog/models.py` | **1220 строк** | Все модели в одном файле (терпимо для Django, но крупно). |
| `tg_bot/services.py` | **868 строк** | Монолит бизнес-логики бота. |
| прямой ORM в `blog/services/*` | **~100 обращений** | По старым правилам вебу ORM разрешён; по новому требованию (ToDo.md) — техдолг. Тяжёлая аналитика (`reports.py`) легитимно на `*_qs()`-аксессорах. |
| `documentation/hot_fix_1.md` | **отсутствует** | Файл-трекер техдолга, на который ссылается README, потерян. Этот документ его заменяет. |

Дубли форматтеров даты (7+ копий) и паттернов «выбор n из m» (5 реализаций) уже
задокументированы в [audit-reuse.md](audit-reuse.md) — переносим их фазы сюда как под-задачи.

---

## Порядок работы (согласовано с пользователем 2026-07-20)

- **Сначала data_controller, потом views** — файлы пересекаются, параллелить нельзя
  (agent-workflow §1). Фундамент до фасада.
- **ORM-миграция прагматично:** чистый разделённый контроллер + аксессоры → перенос
  ORM из **вьюх** (79 шт). Тяжёлую аналитику оставляем на `*_qs()`. Полная зачистка
  `blog/services/*` — отдельной поздней фазой.
- **Оформление:** ветка `agent/opus/<этап>`, поэтапные коммиты; по договорённости с
  пользователем допускается автопуш/мёрж в `main` (durable authorization на эту
  задачу; ср. память `autopublish-to-main`). Каждая фаза = отдельный коммит, чтобы
  откат был чистым.
- **После каждой фазы:** `python manage.py check` + прогон затронутого сценария.

---

## Фаза 1 — Распил `data_controller` на пакет  ⬜

Цель: `data_base/data_controller.py` → пакет `data_base/data_controller/` с сохранением
**обратной совместимости импортов** (весь код импортит `from data_base.data_controller
import get_user...` — эти имена должны продолжать работать через `__init__.py`).

- [ ] `data_base/data_controller/__init__.py` — реэкспорт всего `__all__` (фасад).
- [ ] Разбить по доменам:
  - `users.py` — user/manager/team_leader (create/get/update/qs юзеров и ролей)
  - `events.py` — event/shift/category/staff/publish/broadcast
  - `applications.py` — application/participation/decisions
  - `orgs.py` — organization/organizer/links/interactions/location
  - `requirements.py` — requirement/exception/category-map
  - `reference.py` — const/season/feedback/comment/churn/dobro-link
  - `querysets.py` — все `*_qs()` аксессоры + скаляры для отчётов
  - `_base.py` — общий логгер, `actor`, `create_record_generic`, `get_full_table`
- [ ] Единый геттер/сеттер-стиль, убрать дубль `mark_feedback_requested` (свести слои).
- [ ] `MEMORY`-пометка `.md` внутри пакета: что где лежит.
- [ ] `python manage.py check` зелёный.

## Фаза 2 — Перенос прямого ORM из `views.py` в контроллер  🔄

- [x] Справочные list-вьюхи (locations/organizations/organizers/categories/
  requirements) → новые `*_qs()`-аксессоры контроллера + сортировка во вьюхе.
- [x] `settings_view` панели constants/seasons → `dc.get_all_consts()`/`dc.get_seasons()`.
- [x] `organization_detail`/`organizer_detail` перекрёстные списки → `*_qs()`.
- [ ] Крупные вьюхи: dashboard-область, event_list, event_detail, application_*,
  profile_detail, user_list (annotate/OuterRef → `*_qs()` + композиция во вьюхе),
  report-области, analytics.

**Решение по `get_object_or_404(Model.objects…, pk=…)`** (≈5 мест): оставляем как
есть — это стандартная веб-идиома «получить-или-404», а контроллер не должен знать
про HTTP-404. Перенос «геттер по id в контроллере + 404 во вьюхе» раздул бы контроллер
геттерами-однодневками без выгоды. Прагматика (выбор пользователя: «инфра сначала»).

- [ ] Ручные `request.POST.getlist(...)` разборы (manual-волонтёры, PGAS event_ids) —
  через формы/виджеты (см. audit-reuse #4/#5), а не сырьём во вьюхе. → Фаза 6.

## Фаза 3 — Декомпозиция `views.py`  ⬜

Разбиваем **по доменам** (не по «страницам» и не по «функциям» строго): часть логики
переиспользуется, поэтому граница по бизнес-сущности даёт меньше всего дублей.
Django-роутинг остаётся в `blog/urls.py` (импорты правим на пакет).

Целевой пакет `blog/views/`:
- `auth.py` — login/logout/register/tg-login/webapp/verify
- `events.py` — список/деталь/CRUD меро, смены, публикация, broadcast, closing
- `applications.py` — подача/обработка/manual/cancel/import-preview-commit
- `participations.py` — явка/часы
- `profiles.py` — профиль, комментарии, blacklist, pgas-verify
- `reports.py` — report_period/dashboard/tables/dobro/exports/pdf
- `settings_hub.py` — settings_view + справочники (locations/orgs/organizers/
  categories/requirements/consts/seasons/roles)
- `pgas.py` — справка ПГАС (issue/download/template)
- `analytics.py` — ping/leave/click/dashboard/downtime/log
- `_common.py` — `is_ajax`, `modal_form_response`, captcha, `_safe_next`, quick_create_*
- `__init__.py` — реэкспорт для `urls.py`.

## Фаза 4 — Вынос JS из `base.html` в `static/blog/js/`  ⬜

- [ ] Разбить инлайновый JS на модули: `calendar.js` (CalendarUtils+datepickers),
  `modal.js` (модалки/bottom-sheet/тосты/навигация), `selects.js` (chip-select/
  user-picker/org-link/remote), `tables.js` (sortable/hideable/infinite/report-tools),
  `ui.js` (сайдбар/тема/счётчики/пароль). Подключить через `{% static %}` + `defer`.
- [ ] `base.html` оставить как каркас разметки + подключения. Цель < ~600 строк.
- [ ] Проверить CSP/порядок инициализации (`initPageContent`).

## Фаза 5 — `forms.py` и `tg_bot/services.py`  ⬜

- [ ] `blog/forms.py` → пакет `blog/forms/` по доменам.
- [ ] `tg_bot/services.py` → разбить по доменам, убедиться что всё идёт через
  `data_controller` (правила §1: бот **не** пишет ORM).

## Фаза 6 — Дубли и переиспользование (из audit-reuse.md)  ⬜

- [ ] Форматтеры даты → `blog/services/formatting.py` (`fmt_dt/fmt_date/fmt_day`).
- [ ] manual-волонтёры (#4) → user-picker.
- [ ] PGAS event_ids (#5) → chip-select.
- [ ] toggle-клавиатура бота (#3) → обобщить.

## Фаза 7 — `.md`-описания в каждый пакет  ⬜

- [ ] В каждую новую папку-пакет (`data_controller/`, `views/`, `forms/`, `static/js/`)
  положить `README.md`: что за файлы, где что лежит, в каком стиле писать.
- [ ] Дополнить `agent-workflow.md`/`coding-principles.md` ссылками на эти README и на
  этот план (чтобы чтение стало частью онбординга агента → в системный промт).

---

## Журнал выполнения

_(дописывается по мере работы: фаза → дата → коммит → что реально сделано)_

- **Фаза 1 ✅ — 2026-07-20** (`2aca437`, смёржено в main `f5abc5e`).
  `data_controller.py` (953 стр, 84 фн) → пакет `data_base/data_controller/`
  (`users/orgs/events/applications/requirements/reference/querysets/_base` + `__init__`
  фасад + README). Публичный контракт сохранён (реэкспорт всего `__all__`), вызывающий
  код не менялся. `manage.py check` зелёный; импорт всех потребителей без ошибок; ни
  один экспорт не потерян. Проверено, что `mark_feedback_requested` в `tg_bot/services`
  не разошёлся — это тонкая async-обёртка над `dc.mark_feedback_requested` (её ORM-строка
  `Participation.objects` — на Фазу 5, «бот не пишет ORM»).
