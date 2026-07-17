# Компаньон-гид по платформе (гусь 🦆)

> Сценарии интерактивного тура, который объясняет **весь** функционал платформы.
> Запускается кнопкой «🦆 Гайд по платформе» (в сайдбаре у авторизованных, в шапке у
> гостя — `#companion-guide-btn`, base.html) и автозапуском при первом заходе.
> **Всё описано по реальному коду** (`base.html`, `event_list.html`, `event_detail.html`,
> `report_period.html`, `settings.html`, `pending_applications.html`, `views.py`).
> Домысливать элементы нельзя — только то, что реально есть в DOM.

---

## 0. Как устроен движок (факт из кода)

`blog/static/blog/js/companion.js` → `window.CompanionTour`. Запуск:

```js
CompanionTour.start(STEPS, {
    storageKey: 'companion_<scope>_seen',   // не автозапускать повторно
    outro: { photo, title, text },          // финал «дошёл до конца»
    interrupted: { photo, title, text },    // финал «я знаю, бб» / крестик / Esc
    onStepEnter: function (step, index) {    // подготовить экран под шаг
        // напр. вернуть settingsOpenTab(step.tabKey) — Promise, тур дождётся
    },
});
```

**Формат одного шага:**

```js
{
    target: 'css-селектор' | null,   // что подсветить spotlight-вырезом; null → окно по центру
    title:  'Заголовок',
    text:   'Текст подсказки',
    photo:  GOOSE[0..3],             // фото гуся, 4 слота
    placement: 'auto|right|left|top|bottom|center',
    // + произвольные поля (напр. tabKey) — читает onStepEnter
}
```

Управление: клик по экрану / стрелки / Enter — вперёд, «Назад», «Я знаю, бб» — прерывание,
Esc / крестик — тоже прерывание. Прогресс `N / total`. Всё уже реализовано — эти .md
описывают **контент шагов**, который подставляется в `STEPS`.

Реально подключённый сценарий сейчас один — **тур по настройкам** (`settings.html`).
Остальные секции берутся из этих файлов при подключении на своих страницах.

---

## 1. Роли и наследование

Права аддитивны (`access-control.md`): Волонтёр ⊂ Тим-лидер ⊂ Менеджер. Гайд собирается тем же наследованием, ничего не дублируя:

```
Гость      = [guest]                                              (не в системе — приглашение войти)
Волонтёр   = [volunteer]
Тим-лидер  = [volunteer] + [handoff_tl] + [team-leader]
Менеджер   = [volunteer] + [handoff_tl] + [team-leader] + [handoff_mgr] + [manager]
```

Одно место (напр. «Мероприятия») описано **ровно один раз** — в `volunteer.md`.
`handoff_tl` / `handoff_mgr` — кадровые заглушки-мостики между блоками ролей.

---

## 2. Правила текста

- Коротко, на «ты», тон гуся: дружелюбно, с лёгким юмором (как в `settings.html`: «редко, но метко», «бб»).
- Волонтёр/гость: ≤ 20–25 слов на шаг. ТЛ/менеджер: можно чуть больше — блоки функциональные.
- Мемы/отсылки — дозированно (🎬), одна на секцию.
- Каждый шаг = один экранный элемент или одна вкладка. Ничего не выдумываем: якорь обязан существовать.

---

## 3. Якоря (реальные, проверены в DOM)

**Сайдбар / шапка (base.html):**
- `.sidebar-account` — карточка аккаунта (у авторизованных)
- `[data-track="nav:dashboard"]`, `[data-track="nav:event_list"]`
- `[data-track="nav:pending_applications"]`, `[data-track="nav:user_list"]`
- `[data-track="nav:report_period"]`, `[data-track="nav:dobro_page"]`, `[data-track="nav:analytics_dashboard"]`
- `#theme-toggle`, `#sidebar-toggle`, `#companion-guide-btn`
- ссылка «⚙️ Настройки» и «🚪 Выйти» в `.sidebar-footer`
- гость: `.guest-account`, `.guest-banner`, кнопка «Войти»

**Мероприятия (event_list / event_detail):** кнопка «📝 Подать заявку», «+ Новое мероприятие»,
`#event-search`, `#hide-passed`, `#events-table`, тулбар меро (Опубликовать/Рассылка/Завершить/…),
`.event-dashboard`, таблица смен, `#applications`, кнопки явки `.att-btn`, «Принять всех».

**Заявки (pending_applications):** «➕ Добавить заявки», «📥 Загрузить из Excel», «Принять всех», `#apps-table`.

**Отчёты (report_period):** `#report-views` (вкладки dashboard/tables/dobro), `#report-scope-card`, `#report-panel`.

**Настройки (settings):** `.settings-tab[data-tab="<key>"]`, ключи:
`locations, organizers, organizations, requirements, constants, seasons, team_leaders, managers, pgas_template`.
Открытие вкладки в туре — `window.settingsOpenTab(tabKey)`.

---

## 4. Файлы

| Файл | Кого | Что покрывает |
|---|---|---|
| `guest.md` | гость | приглашение войти, что видно без входа, как получить доступ |
| `volunteer.md` | все | аккаунт, профиль, мероприятия (список+карточка), подача заявки, статистика/ПГАС, тема, гид, выход |
| `team-leader.md` | ТЛ+МН | заглушка + мои меро, обработка заявок, набор/смены, явка/часы, профиль волонтёра, лента изменений |
| `manager.md` | МН | заглушка + дашборд, полный жизненный цикл меро, заявки в масштабе, импорт, пользователи/ПГАС, отчёты (все вкладки), настройки (все вкладки) |
