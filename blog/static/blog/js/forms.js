/*
 * static/blog/js/forms.js
 * Поведение форм: форма меро, связка организация↔организатор, чипы смен,
 * форма заявки (динамическая подгрузка смен).
 *
 * Часть распила инлайнового JS base.html (см. static/blog/js/README.md).
 * Грузится обычным <script> (не модуль) — все init-функции и хелперы остаются в
 * глобальном scope, как раньше; initPageContent зовёт их через window[fn].
 */
    function initEventForm(root) {
        initCategoryChips(root);
        initShiftChips(root);
        initDatepickers(root);
        initDateRangePair(root);
        initTimepickers(root);
        initApplicationForm(root);
        initOrgOrganizerLink(root);
    }

    // ======================================================================
    // Зависимая фильтрация выбора «организация ↔ организатор» в форме меро.
    // Выбрал организацию → в списке организаторов остаются только связанные с ней
    // (OrganizerOrganizationLink), и наоборот. «＋» (создание новой записи) и уже
    // выбранное значение не прячем никогда. Кнопка «показать всех» снимает фильтр.
    // Источник связей — data-org-links (JSON [{organization, organizer}, …]).
    // ======================================================================
    function initOrgOrganizerLink(root) {
        root.querySelectorAll('[data-org-links]').forEach(function (wrap) {
          if (wrap.dataset.orgLinkInit) return;
          wrap.dataset.orgLinkInit = '1';
          // Зависимая фильтрация — вспомогательная; её сбой не должен ломать форму меро.
          try {
            var links;
            try { links = JSON.parse(wrap.getAttribute('data-org-links') || '[]'); }
            catch (e) { links = []; }
            var orgSelect = document.getElementById(wrap.getAttribute('data-org-select'));
            var organizerSelect = document.getElementById(wrap.getAttribute('data-organizer-select'));
            if (!orgSelect || !organizerSelect) return;

            // Индексы связей в обе стороны: организация → set(организаторов) и обратно.
            var organizersByOrg = {}, orgsByOrganizer = {};
            links.forEach(function (l) {
                (organizersByOrg[l.organization] = organizersByOrg[l.organization] || {})[l.organizer] = 1;
                (orgsByOrganizer[l.organizer] = orgsByOrganizer[l.organizer] || {})[l.organization] = 1;
            });

            // Подсказки/кнопки сброса живут в соседних полях (организация и организатор),
            // поэтому ищем от общего контейнера, а не только внутри wrap.
            var scope = wrap.parentNode || wrap;
            var organizerHint = scope.querySelector('[data-org-filter-hint]');
            var orgHint = scope.querySelector('[data-organizer-filter-hint]');
            var suppress = { organizer: false, org: false }; // «показать всех» снял фильтр

            // Прячем в select те option, чей id не входит в allowed (кроме пустого «—»
            // и текущего выбранного). Возвращает, был ли реально применён фильтр.
            function filterSelect(select, allowed) {
                var applied = false;
                Array.prototype.forEach.call(select.options, function (opt) {
                    if (!opt.value) { opt.hidden = false; return; }        // «— не выбрано —»
                    if (opt.selected) { opt.hidden = false; return; }      // текущее значение
                    var ok = !allowed || allowed[opt.value];
                    opt.hidden = !ok;
                    if (!ok) applied = true;
                });
                return applied;
            }

            // Есть ли у ключа хотя бы одна связь (иначе фильтровать нельзя — иначе
            // спрячем ВСЕ варианты и поле станет пустым/непригодным).
            function hasAny(map) { for (var k in map) return true; return false; }

            function apply() {
                // Организация выбрана и у неё есть связанные организаторы → фильтруем
                // (если менеджер не нажал «показать всех»). Нет связей — показываем всех.
                var orgVal = orgSelect.value;
                var orgAllowed = orgVal ? (organizersByOrg[orgVal] || {}) : null;
                if (orgVal && !suppress.organizer && hasAny(orgAllowed)) {
                    var applied = filterSelect(organizerSelect, orgAllowed);
                    if (organizerHint) organizerHint.hidden = !applied;
                } else {
                    filterSelect(organizerSelect, null);
                    if (organizerHint) organizerHint.hidden = true;
                }
                // Симметрично: организатор выбран и у него есть связанные организации.
                var organizerVal = organizerSelect.value;
                var organizerAllowed = organizerVal ? (orgsByOrganizer[organizerVal] || {}) : null;
                if (organizerVal && !suppress.org && hasAny(organizerAllowed)) {
                    var applied2 = filterSelect(orgSelect, organizerAllowed);
                    if (orgHint) orgHint.hidden = !applied2;
                } else {
                    filterSelect(orgSelect, null);
                    if (orgHint) orgHint.hidden = true;
                }
            }

            orgSelect.addEventListener('change', function () { suppress.organizer = false; apply(); });
            organizerSelect.addEventListener('change', function () { suppress.org = false; apply(); });

            var resetOrganizer = scope.querySelector('[data-org-filter-reset]');
            if (resetOrganizer) resetOrganizer.addEventListener('click', function () {
                suppress.organizer = true; filterSelect(organizerSelect, null);
                if (organizerHint) organizerHint.hidden = true;
            });
            var resetOrg = scope.querySelector('[data-organizer-filter-reset]');
            if (resetOrg) resetOrg.addEventListener('click', function () {
                suppress.org = true; filterSelect(orgSelect, null);
                if (orgHint) orgHint.hidden = true;
            });

            apply(); // применить сразу (напр. при редактировании с уже выбранной парой)
          } catch (e) { /* фильтрация опциональна — не мешаем сохранению меро */ }
        });
    }

    // ======================================================================
    // Смены в форме создания мероприятия — тот же визуальный язык, что у чипов
    // категорий: уже добавленные смены показываются чипами с крестиком (убрать),
    // поля ввода ниже собирают одну новую смену за раз (дата — обычный календарь
    // data-datepicker, время — data-timepicker, как везде в проекте), кнопка "＋"
    // добавляет её в список. Итоговый массив уходит на сервер JSON-строкой в
    // shifts_json — сервер валидирует каждую смену отдельно (EventForm._build_shift_forms).
    // Вызывается ДО initDatepickers/initTimepickers, чтобы найти исходные поля по
    // data-shift-day/-start/-end, пока их ещё не подменили виджеты.
    // ======================================================================
    function initShiftChips(root) {
        root.querySelectorAll('[data-shift-chips-json]').forEach(function (jsonInput) {
            if (jsonInput.dataset.shiftInit) return;
            jsonInput.dataset.shiftInit = '1';

            var wrap = jsonInput.parentNode;
            var selectedRow = wrap.querySelector('[data-shift-chips-selected]');
            var dayInput = wrap.querySelector('[data-shift-day]');
            var startInput = wrap.querySelector('[data-shift-start]');
            var endInput = wrap.querySelector('[data-shift-end]');
            var neededInput = wrap.querySelector('[data-shift-needed]');
            var addBtn = wrap.querySelector('[data-shift-add]');
            var errorBox = wrap.querySelector('[data-shift-error]');
            if (!selectedRow || !dayInput || !addBtn) return;

            // initDatepickers удаляет исходный dayInput и кладёт рядом hidden с
            // реальным значением — запоминаем родителя сейчас, пока dayInput жив.
            var dayFieldParent = dayInput.parentNode;

            var shifts = [];
            try { shifts = JSON.parse(jsonInput.value || '[]'); } catch (e) { shifts = []; }

            function showError(text) {
                if (!errorBox) return;
                errorBox.textContent = text;
                errorBox.hidden = !text;
            }

            function render() {
                selectedRow.innerHTML = '';
                if (!shifts.length) {
                    var empty = document.createElement('span');
                    empty.className = 'cat-chips-empty';
                    empty.textContent = 'Смены ещё не добавлены';
                    selectedRow.appendChild(empty);
                }
                shifts.forEach(function (s, idx) {
                    var chip = document.createElement('span');
                    chip.className = 'cat-chip ' + shiftChipColor(idx);
                    chip.innerHTML = '<span class="cat-chip-label"></span>' +
                        '<button type="button" class="cat-chip-x" aria-label="Убрать смену">×</button>';
                    chip.querySelector('.cat-chip-label').textContent =
                        s.dayLabel + ' ' + s.start_time + '–' + s.end_time +
                        (s.volunteer_needed ? ' (' + s.volunteer_needed + ' чел.)' : '');
                    chip.querySelector('.cat-chip-x').addEventListener('click', function () {
                        shifts.splice(idx, 1);
                        sync();
                    });
                    selectedRow.appendChild(chip);
                });
                jsonInput.value = JSON.stringify(shifts.map(function (s) {
                    return { day: s.day, start_time: s.start_time, end_time: s.end_time, volunteer_needed: s.volunteer_needed };
                }));
            }

            // Кнопка «Создать» блокируется, пока смен нет (require_shift) — так менеджер
            // просто не может отправить форму без смены, вместо ошибки после сабмита.
            var submitBtn = null;
            var formEl = jsonInput.closest('form');
            if (formEl) submitBtn = formEl.querySelector('button[type=submit]');
            function updateSubmitState() {
                if (!submitBtn) return;
                var ok = shifts.length > 0;
                submitBtn.disabled = !ok;
                submitBtn.title = ok ? '' : 'Добавьте хотя бы одну смену';
            }

            function sync() { render(); updateSubmitState(); }

            var CHIP_COLORS = ['c0', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7'];
            function shiftChipColor(idx) { return 'cat-chip--' + CHIP_COLORS[idx % CHIP_COLORS.length]; }

            // Пересекается ли новая смена по времени с уже добавленными в тот же день
            // (полуинтервалы [start,end); встык — не пересечение). Совпадает с серверной
            // проверкой в forms._shifts_overlap.
            function overlapsExisting(dayIso, start, end) {
                return shifts.some(function (s) {
                    return s.day === dayIso && start < s.end_time && s.start_time < end;
                });
            }

            function dpFmtLabel(iso) {
                var p = iso.split('-');
                return p[2] + '.' + p[1] + '.' + p[0];
            }

            addBtn.addEventListener('click', function () {
                // Значение даты берём из hidden-поля, которое initDatepickers создаёт
                // рядом с исходным input (сам input к этому моменту уже удалён из DOM).
                var dayHidden = dayFieldParent.querySelector('input[type=hidden]');
                var dayIso = dayHidden ? dayHidden.value : '';
                if (!dayIso) {
                    showError('Выберите дату смены в календаре.');
                    return;
                }
                var start = (startInput.value || '').trim();
                var end = (endInput.value || '').trim();
                if (!/^\d{2}:\d{2}$/.test(start) || !/^\d{2}:\d{2}$/.test(end)) {
                    showError('Укажите время начала и окончания смены.');
                    return;
                }
                if (end <= start) {
                    showError('Время окончания должно быть позже времени начала.');
                    return;
                }
                if (overlapsExisting(dayIso, start, end)) {
                    showError('Смена пересекается по времени с уже добавленной в этот день.');
                    return;
                }
                var needed = parseInt(neededInput.value, 10);
                if (!needed || needed < 1) {
                    showError('Укажите, сколько волонтёров нужно на смену (не менее 1).');
                    return;
                }
                showError('');
                shifts.push({
                    day: dayIso,
                    dayLabel: dpFmtLabel(dayIso),
                    start_time: start,
                    end_time: end,
                    volunteer_needed: needed,
                });
                sync();
                if (typeof window.showToast === 'function') window.showToast('Смена добавлена', 'success');
            });

            sync();
        });
    }

    // ======================================================================
    // Форма подачи заявки: выбор смен — те же чипы, что у категорий, но пул
    // вариантов зависит от выбранного мероприятия. При смене select'а "Мероприятие"
    // подтягиваем открытые смены этого меро через AJAX и пересобираем скрытый
    // <select multiple name="selected_shifts"> — чип-виджет перерисовывается сам
    // по событию chips:refresh (initCategoryChips слушает его на select'е).
    // ======================================================================
    function initApplicationForm(root) {
        var form = root.querySelector('#application-form');
        if (!form || form.dataset.appFormInit) return;
        form.dataset.appFormInit = '1';

        var eventSelect = form.querySelector('[name=event]');
        var shiftsSelect = form.querySelector('[name=selected_shifts]');
        if (!eventSelect || !shiftsSelect) return;

        function loadShifts(eventId, preselectedIds) {
            if (!eventId) {
                shiftsSelect.innerHTML = '';
                shiftsSelect.dispatchEvent(new Event('chips:refresh'));
                return;
            }
            fetch('/applications/event-shifts/' + eventId + '/', {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                shiftsSelect.innerHTML = '';
                (data.shifts || []).forEach(function (shift) {
                    var option = document.createElement('option');
                    option.value = shift.id;
                    option.textContent = shift.label;
                    // Закрытая по набору смена — выбираема, но серым (заявка → резерв).
                    if (shift.closed) option.setAttribute('data-closed', '1');
                    if (preselectedIds && preselectedIds.indexOf(String(shift.id)) !== -1) option.selected = true;
                    shiftsSelect.appendChild(option);
                });
                shiftsSelect.dispatchEvent(new Event('chips:refresh'));
            });
        }

        // При первой загрузке формы (редактирование/повторный рендер после ошибки)
        // сервер уже прислал нужные <option> — сохраняем их selected-состояние.
        var initialSelected = Array.prototype.filter.call(shiftsSelect.options, function (o) { return o.selected; })
            .map(function (o) { return o.value; });
        if (eventSelect.value && !shiftsSelect.options.length) {
            loadShifts(eventSelect.value, initialSelected);
        }

        eventSelect.addEventListener('change', function () {
            loadShifts(eventSelect.value, []);
        });
    }

    // ======================================================================
    // Одиночный date-picker (brandbook §6.3): текстовое поле-триггер (data-datepicker)
    // раскрывает popover с одним месяцем; выбор даты закрывает popover сразу.
    // Переиспользует .cal/.cal-grid стили из nexus.css (общие с Date Range Picker)
    // и утилиты дат из window.CalendarUtils.
    // ======================================================================
