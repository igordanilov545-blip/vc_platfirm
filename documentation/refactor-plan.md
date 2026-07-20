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

## Фаза 2 — Перенос прямого ORM из `views.py` в контроллер  ✅ (бизнес-домен)

**Итог: 79 → 18 `.objects.`**, и все 18 оставшихся — осознанные исключения:
- **9× `get_object_or_404(Model.objects…, pk=…)`** — веб-идиома «получить-или-404»,
  контроллер не должен знать про HTTP-404.
- **1× `User.objects.create_user`** в `register_view` — веб-регистрация со спецификой
  (login/пароль/web_credentials), не покрывается бизнес-`dc.create_user`.
- **8× технической аналитики** (`WebSession`/`WebPageView`/`ButtonClickEvent`/
  `SystemDowntime`) — это **не бизнес-домен ВЦ**, а телеметрия техадмин-дашборда. Их
  модели намеренно НЕ в `TABLE_MODEL_MAP`; тащить их в бизнес-контроллер (единая точка
  данных ВЦ + аудит `vc.db`) исказило бы его. Отдельный слой/сервис аналитики — вне
  Фазы 2.

Новые аксессоры контроллера, добавленные по ходу: `locations_qs/organizations_qs/
organizers_qs/event_categories_qs/requirements_qs/seasons_qs/application_shift_decisions_qs`;
тонкие сеттеры `set_user_status/set_user_verification/create_churn_log/resolve_incidents`.
Новый сервис `blog/services/moderation.py` (blacklist/verify через контроллер).

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

## Фаза 3 — Декомпозиция `views.py`  ✅

`views.py` (4373 стр, 161 функция) → пакет `blog/views/` из **15 файлов** по бизнес-
доменам (по просьбе — гранулярно, «один файл на область»):
`_common` (фундамент+shared-импорты+капча), `quick_create`, `auth`, `events`,
`applications`, `participations`, `profiles`, `volunteers`, `pgas`, `organizations`,
`settings_hub`, `reports`, `dashboard`, `analytics` + фасад `__init__` + `README.md`
(путеводитель «с чем работаешь → какой файл»). Самый большой файл — 813 строк
(reports), медиана ~200.

- Распил выполнен программно (AST по границам определений), раскладка — по карте
  доменов; ни одного имени не потеряно, ни одной перепутанной функции.
- Фасад `__init__.py` реэкспортит все вьюхи → `urls.py` и прочий код не менялись.
- Cross-domain: единственная общая приватная зависимость `_published_active_events`
  (dashboard берёт из events явным импортом) — найдена сеткой безопасности.
- Проверено: `manage.py check`; тесты 44/44; импорт всех 15 модулей; фасад покрывает
  все url-имена; `/run` — 9 доменов + отчёты (дашборд с графиками) рендерятся живьём.

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

## Фаза 4 — Вынос JS из `base.html` в `static/blog/js/`  ✅

`base.html`: **2876 → 455 строк** (−84%). Инлайновый `<script>` (~2430 строк) вынесен в
`static/blog/js/`: `calendar-utils.js` (в `<head>`, нужен рано) + тематические
`ui/modal/forms/calendar/selects/tables/misc.js` + README-путеводитель.

- Резка программная (по границам top-level функций), синтаксис каждого модуля проверен
  `node --check`.
- Django-теги в JS невозможны → 7 `{% url %}` вынесены в инлайн-конфиг `window.VC_URLS`
  (base.html), модули читают оттуда. Тема-до-рендера и ролевой companion-тур остаются
  инлайн (нужны серверные данные).
- Модули грузятся обычными `<script>` (глобальный scope сохранён, `window[fn]`
  работает). Порядок подключения выверен: проверено, что все `initXxx(document)`-
  самовызовы идут после определения функции.
- Проверено `/run`: 0 console-ошибок на 6 страницах; AJAX-модалка создания заявки
  открывается и работает (modal+forms+selects+ui вместе).

- [ ] Разбить инлайновый JS на модули: `calendar.js` (CalendarUtils+datepickers),
  `modal.js` (модалки/bottom-sheet/тосты/навигация), `selects.js` (chip-select/
  user-picker/org-link/remote), `tables.js` (sortable/hideable/infinite/report-tools),
  `ui.js` (сайдбар/тема/счётчики/пароль). Подключить через `{% static %}` + `defer`.
- [ ] `base.html` оставить как каркас разметки + подключения. Цель < ~600 строк.
- [ ] Проверить CSP/порядок инициализации (`initPageContent`).

## Фаза 5 — `forms.py` и `tg_bot/services.py`  ✅

- [x] `blog/forms.py` (1089 стр, 34 класса) → пакет `blog/forms/`
  (`auth/references/events/applications/profiles/roles` + `_common` + фасад + README).
  Фасад реэкспортит все формы (+ alias `ProfileCompletionForm`); контракт `views/_common`
  покрыт. Тесты 44/44.
- [x] `tg_bot/services.py` (868 стр, 53 функции) → пакет `tg_bot/services/`
  (`users/web_auth/events/applications/comments/feedback_queue/outbox` + `_common` +
  фасад + README). Фасад реэкспортит все 56 имён; все 52 обращения `services.*` из
  хендлеров/notifier/ui резолвятся; вся цепочка бота импортируется.
- ⚠️ **Найдено:** ~25 прямых `.objects.` в services бота — нарушение «бот только через
  контроллер» (при том что docstring файла это правило декларирует). При распиле ORM
  **не трогал** (поведение 1:1); перенос — отдельная будущая фаза (записан ниже).

### Под-фаза «ORM бота → контроллер»  ✅ (2026-07-21)
- [x] Все ~25 обращений к **бизнес-моделям** в `tg_bot/services/*` переведены на `dc`.
  Новые тонкие геттеры контроллера: `get_user_by_id`, `is_login_taken`,
  `get_application_by_id` (with_event/prefetch_shifts), `get_own_application`,
  `get_shift_by_id`, `get_shifts_by_ids`, `get_participation_by_id`,
  `create_application_change_log`.
- Инфра бота оставлена осознанно: `BotOutbox`/`PendingButtonRemoval` (`outbox.py`),
  Django-`Session` (`users.py`) — не бизнес-данные ВЦ (как analytics).
- Сетка безопасности: **+11 тестов** `test_bot_services.py` (сервисы бота синхронны →
  тестируются напрямую). Они же вскрыли и починили **cross-module баг Фазы 5**:
  `comments/events/web_auth/applications` звали `get_user`/`is_guest` из `users`, но
  после распила эти имена не были импортированы (упало бы в рантайме бота). Добавлены
  явные `from .users import …`.
- Проверено: тесты 55/55; вся цепочка бота импортируется; фасад полон.

## Фаза 6 — Дубли и переиспользование (из audit-reuse.md)  ✅

- [x] **Форматтеры даты** → `blog/services/formatting.py` (`fmt_date`/`fmt_dt`). 4+ копии
  сведены в одну реализацию, старые имена — тонкие алиасы (call-sites не тронуты).
  +9 тестов. `/run`: отчёты и Excel-экспорт работают.
- [x] **manual-волонтёры (#4)** — оказалось уже исправлено ранее: remote user-picker
  (`data-select-remote="users"`), а не chip-select-велосипед.
- [x] **PGAS event_ids (#5)** — уже исправлено: `<select multiple hidden>` под
  chip-select, а не сырые checkbox.
- [~] **toggle-клавиатура бота (#3)** — оставлено осознанно (YAGNI: обобщать ради
  одного использования преждевременно; аудит помечал как «кандидат», не нарушение).
- Проверено: сырых checkbox-велосипедов множественного выбора в шаблонах не осталось.
  `audit-reuse.md` дополнен разделом «Статус».

## Фаза 7 — `.md`-описания в каждый пакет + правила в системный промт  ✅

- [x] README-путеводитель в каждом пакете: `data_base/data_controller/`, `blog/views/`,
  `blog/forms/`, `tg_bot/services/`, `blog/static/blog/js/` (созданы по ходу Фаз 1–5).
- [x] **Корневой [CLAUDE.md](../CLAUDE.md)** — грузится в контекст каждой сессии
  автоматически (это и есть «вшить в системный промт»): стек, железные правила, карта
  «где что» со ссылками на все README и ключевые доки, рабочий цикл.
- [x] `agent-workflow.md` (пункт 0 в TL;DR) и `coding-principles.md` (врезка после схемы
  слоёв) обновлены: монолиты стали пакетами, входная точка — CLAUDE.md.
- [x] Индекс `documentation/README.md`: добавлены CLAUDE.md, refactor-plan, audit-reuse;
  убрана мёртвая ссылка на утраченный `hot_fix_1.md` (и в живых файлах — dashboard.py,
  agent-workflow.md; append-only `work-history.md` не трогали).
- Проверено: `manage.py check`; тесты 64/64; все ссылки из CLAUDE.md ведут на
  существующие файлы.

---

## Итог рефакторинга «расчистка» (2026-07-20 … 2026-07-21)

Все 7 фаз + под-фаза ORM бота закрыты и в проде. Крупные монолиты → пакеты по доменам
с фасадами (импорты снаружи не менялись):

| Было | Стало |
|---|---|
| `data_controller.py` 953 стр | пакет из 8 модулей |
| `views.py` 4373 стр | пакет из 15 модулей |
| `forms.py` 1089 стр | пакет из 7 модулей |
| `tg_bot/services.py` 868 стр | пакет из 8 модулей |
| `base.html` 2876 стр | 455 стр + 8 JS-модулей в `static/blog/js/` |

Плюс: бизнес-ORM веба и бота переведён на контроллер (осознанные исключения
задокументированы); форматтеры даты сведены в один модуль; **сетка безопасности с нуля
до 64 тестов** (контроллер, вьюхи, потоки, модерация, бот, форматтеры); каждый пакет с
README; входная точка для агентов — CLAUDE.md.

- [ ] В каждую новую папку-пакет (`data_controller/`, `views/`, `forms/`, `static/js/`)
  положить `README.md`: что за файлы, где что лежит, в каком стиле писать.
- [ ] Дополнить `agent-workflow.md`/`coding-principles.md` ссылками на эти README и на
  этот план (чтобы чтение стало частью онбординга агента → в системный промт).

---

## Журнал выполнения

_(дописывается по мере работы: фаза → дата → коммит → что реально сделано)_

- **Фаза 2 ✅ — 2026-07-20** (порции `a2f1bfb`/`8f0156c`/финал, смёржено `dbd2167`).
  Прямой бизнес-ORM во `views.py`: 79 → 18 `.objects.` (18 = осознанные исключения:
  get_object_or_404 ×9, веб-регистрация ×1, теханалитика ×8). Добавлены аксессоры и
  тонкие сеттеры контроллера, вынесена модерация в сервис, починен баг ChurnLog.
  Сетка безопасности выросла до **44 тестов** (+модерация). Каждая порция: тесты +
  живой `/run` со скриншотами (event_detail, профиль, настройки — ок).

- **Фаза 1 ✅ — 2026-07-20** (`2aca437`, смёржено в main `f5abc5e`).
  `data_controller.py` (953 стр, 84 фн) → пакет `data_base/data_controller/`
  (`users/orgs/events/applications/requirements/reference/querysets/_base` + `__init__`
  фасад + README). Публичный контракт сохранён (реэкспорт всего `__all__`), вызывающий
  код не менялся. `manage.py check` зелёный; импорт всех потребителей без ошибок; ни
  один экспорт не потерян. Проверено, что `mark_feedback_requested` в `tg_bot/services`
  не разошёлся — это тонкая async-обёртка над `dc.mark_feedback_requested` (её ORM-строка
  `Participation.objects` — на Фазу 5, «бот не пишет ORM»).
