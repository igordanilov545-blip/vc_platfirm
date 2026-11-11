/*
 * static/blog/js/selects.js
 * Выбор «n из m»: chip-select (инлайн/модалка), общая модалка выбора,
 * remote user-picker. URL пикера пользователей — из window.VC_URLS.
 *
 * Часть распила инлайнового JS base.html (см. static/blog/js/README.md).
 * Грузится обычным <script> (не модуль) — все init-функции и хелперы остаются в
 * глобальном scope, как раньше; initPageContent зовёт их через window[fn].
 */
    var SELECT_INLINE_MAX = 40; // ≤ этого — инлайн-чипы, иначе модалка (совпадает с PAGE_SIZE модалки)

    var CHIP_PALETTE = ['c0', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7'];
    function chipColorClass(value) {
        var h = 0, s = String(value);
        for (var i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) >>> 0; }
        return 'cat-chip--' + CHIP_PALETTE[h % CHIP_PALETTE.length];
    }

    // Рендер строки выбранных чипов (общий для inline и модалочного режима).
    // getItems() → [{value, label, closed}], onRemove(value) — снять выбор.
    function renderSelectedChips(container, items, emptyText, onRemove) {
        container.innerHTML = '';
        if (!items.length) {
            var empty = document.createElement('span');
            empty.className = 'cat-chips-empty';
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (it) {
            var chip = document.createElement('span');
            chip.className = 'cat-chip ' + (it.closed ? 'cat-chip--closed' : chipColorClass(it.value));
            chip.innerHTML = '<span class="cat-chip-label"></span>' +
                '<button type="button" class="cat-chip-x" aria-label="Убрать">×</button>';
            chip.querySelector('.cat-chip-label').textContent = it.label;
            chip.querySelector('.cat-chip-x').addEventListener('click', function () { onRemove(it.value); });
            container.appendChild(chip);
        });
    }

    function initCategoryChips(root) {
        root.querySelectorAll('[data-chip-select]').forEach(function (widget) {
            if (widget.dataset.chipsInit) return;
            widget.dataset.chipsInit = '1';

            var remote = widget.getAttribute('data-select-remote'); // 'users' | null
            var single = widget.hasAttribute('data-chip-single');
            var emptyText = widget.getAttribute('data-chip-empty')
                || widget.getAttribute('data-empty-text') || 'Ничего не выбрано';
            var selectedRow = widget.querySelector('[data-chips-selected]');

            if (remote) {
                initRemoteSelect(widget, { single: single, emptyText: emptyText, selectedRow: selectedRow, source: remote });
                return;
            }

            // --- Локальный источник: скрытый <select multiple> ---
            var select = document.getElementById(widget.getAttribute('data-chip-select'));
            if (!select) return;
            select.hidden = true;
            var availableRow = widget.querySelector('[data-chips-available]');
            var inlineSearch = widget.querySelector('[data-chips-search]');

            function optionItems(onlySelected) {
                var items = [];
                Array.prototype.forEach.call(select.options, function (opt) {
                    if (onlySelected && !opt.selected) return;
                    items.push({ value: opt.value, label: opt.textContent, closed: opt.getAttribute('data-closed') === '1', opt: opt });
                });
                return items;
            }
            function setSelected(value, on) {
                Array.prototype.forEach.call(select.options, function (o) {
                    if (o.value === value) o.selected = on;
                    else if (on && single) o.selected = false;
                });
            }

            // Число вариантов определяет режим показа. Пересчитывается на каждый
            // render (у формы заявки пул смен подгружается по chips:refresh — меро
            // с 3 сменами показываем инлайн, с 60 — модалкой, без перепривязки).
            function render() {
                var total = select.options.length;
                if (total > SELECT_INLINE_MAX) renderModalMode();
                else renderInlineMode();
            }

            // ——— Инлайн-режим (≤ порога): выбранные сверху, доступные снизу ———
            function renderInlineMode() {
                widget.classList.remove('chips--modal');
                if (widget._modalTrigger) widget._modalTrigger.style.display = 'none';
                if (availableRow) availableRow.style.display = '';
                var query = inlineSearch ? inlineSearch.value.trim().toLowerCase() : '';
                renderSelectedChips(selectedRow, optionItems(true), emptyText, function (value) {
                    setSelected(value, false); render();
                });
                if (!availableRow) return;
                availableRow.innerHTML = '';
                var availableCount = 0;
                optionItems(false).forEach(function (it) {
                    if (it.opt.selected) return;
                    if (query && !window.searchMatches(it.label, query)) return;
                    availableCount++;
                    var avail = document.createElement('button');
                    avail.type = 'button';
                    avail.className = 'cat-chip cat-chip--add ' + (it.closed ? 'cat-chip--closed' : chipColorClass(it.value));
                    avail.innerHTML = '<span class="cat-chip-label"></span><span class="cat-chip-plus">+</span>';
                    avail.querySelector('.cat-chip-label').textContent = it.label;
                    avail.addEventListener('click', function () { setSelected(it.value, true); render(); });
                    availableRow.appendChild(avail);
                });
                if (inlineSearch && query && !availableCount) {
                    var nr = document.createElement('span');
                    nr.className = 'cat-chips-empty';
                    nr.textContent = 'Ничего не найдено';
                    availableRow.appendChild(nr);
                }
            }

            // ——— Модалочный режим (> порога): поле-триггер + общая модалка ———
            function renderModalMode() {
                widget.classList.add('chips--modal');
                if (availableRow) availableRow.style.display = 'none';
                if (widget._modalTrigger) widget._modalTrigger.style.display = '';
                renderSelectedChips(selectedRow, optionItems(true), emptyText, function (value) {
                    setSelected(value, false); render();
                });
                ensureModalTrigger(widget, function () {
                    ensureSelectModal().open({
                        single: single,
                        candidates: function (query) {
                            return optionItems(false).filter(function (it) {
                                return !it.opt.selected && (!query || window.searchMatches(it.label, query));
                            });
                        },
                        onPick: function (it) { setSelected(it.value, true); render(); },
                        // Полоса «Выбрано» внутри окна (мультивыбор): показать и дать снять.
                        selectedItems: function () {
                            return optionItems(true).map(function (it) { return { value: it.value, label: it.label }; });
                        },
                        onUnpick: function (value) { setSelected(value, false); render(); },
                    });
                });
            }

            select.addEventListener('chips:refresh', render);
            render();
        });
    }

    // Поле-триггер «＋ выбрать» под чипами (создаётся один раз на виджет). onOpen —
    // открыть модалку. Отдельно от строки инлайн-поиска: в модалочном режиме своего
    // поиска у виджета нет, он внутри модалки.
    function ensureModalTrigger(widget, onOpen) {
        if (widget._modalTrigger) return;
        var wrap = widget.querySelector('[data-chips-available-wrap]') || widget;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'cat-chip cat-chip--add cat-chip--pick';
        btn.innerHTML = '<span class="cat-chip-label">Выбрать из списка…</span><span class="cat-chip-plus">+</span>';
        btn.addEventListener('click', onOpen);
        (widget.querySelector('[data-chips-selected]') || widget).insertAdjacentElement('afterend', btn);
        widget._modalTrigger = btn;
    }

    // ======================================================================
    // ОБЩАЯ МОДАЛКА ВЫБОРА (одна на страницу, лениво создаётся при первом открытии).
    // Обслуживает оба режима единого виджета:
    //   • локальный — кандидаты приходят функцией candidates(query) из уже
    //     отрендеренного <select> (виджет с >40 вариантами: смены большого меро и т.п.);
    //   • remote — источник людей: список грузится с /users/picker-data/ с
    //     ранжированием (недавние/по имени), лимитом и кнопкой «показать всех».
    // Список рендерится порциями по PAGE_SIZE (догрузка при прокрутке вниз), поиск —
    // по подстроке. Выбор кладётся через cfg.onPick; single-режим закрывает модалку.
    // ======================================================================
    var selectModal = null;
    function ensureSelectModal() {
        if (selectModal) return selectModal;
        var PAGE_SIZE = 40;
        var backdrop = document.createElement('div');
        backdrop.className = 'user-picker-modal-backdrop';
        backdrop.hidden = true;
        backdrop.innerHTML =
            '<div class="user-picker-modal">' +
                '<div class="user-picker-modal-head">' +
                    '<input type="text" class="user-picker-modal-search" placeholder="Поиск по подстроке…">' +
                    '<div class="user-picker-modes" data-modes hidden>' +
                        '<button type="button" class="picker-mode-btn is-active" data-mode-btn="recent" title="Сначала недавние">🕑</button>' +
                        '<button type="button" class="picker-mode-btn" data-mode-btn="name" title="По алфавиту">А—Я</button>' +
                    '</div>' +
                    '<button type="button" class="user-picker-modal-close" aria-label="Закрыть">×</button>' +
                '</div>' +
                '<div class="user-picker-modal-selected" data-picker-selected hidden></div>' +
                '<div class="user-picker-modal-body"></div>' +
                '<div class="user-picker-modal-foot"></div>' +
            '</div>';
        document.body.appendChild(backdrop);

        var bodyEl = backdrop.querySelector('.user-picker-modal-body');
        var searchEl = backdrop.querySelector('.user-picker-modal-search');
        var footEl = backdrop.querySelector('.user-picker-modal-foot');
        var closeBtn = backdrop.querySelector('.user-picker-modal-close');
        var modesEl = backdrop.querySelector('[data-modes]');
        var selectedEl = backdrop.querySelector('[data-picker-selected]');

        var cfg = null;          // конфиг текущего открытия
        var visibleCount = 0;

        function candidates() {
            return cfg.candidates(searchEl.value.trim());
        }

        // Полоса «Выбрано: …» прямо внутри окна — чтобы при множественном выборе было
        // видно, что уже отмечено, и можно было снять, не закрывая модалку. Общая для всех
        // потребителей: работает, если конфиг отдаёт selectedItems() и onUnpick(value).
        // Single-режим полосу не показывает (там выбор — одно значение, окно закрывается).
        function renderSelected() {
            if (!cfg || cfg.single || typeof cfg.selectedItems !== 'function') {
                selectedEl.hidden = true;
                return;
            }
            var items = cfg.selectedItems() || [];
            selectedEl.hidden = false;
            selectedEl.innerHTML = '';
            var label = document.createElement('span');
            label.className = 'user-picker-selected-label';
            label.textContent = items.length ? 'Выбрано (' + items.length + '):' : 'Пока ничего не выбрано';
            selectedEl.appendChild(label);
            if (!items.length) return;
            var row = document.createElement('span');
            row.className = 'cat-chips-row';
            selectedEl.appendChild(row);
            renderSelectedChips(row, items, '', function (value) {
                if (cfg.onUnpick) cfg.onUnpick(value);
                renderPage(true);
            });
        }

        function renderPage(reset) {
            renderSelected();
            var list = candidates();
            if (reset) { visibleCount = 0; bodyEl.innerHTML = ''; }
            if (!list.length) {
                bodyEl.innerHTML = '<div class="cat-chips-empty" style="padding:16px;">' +
                    (cfg.searching ? 'Поиск по всей базе…' : 'Ничего не найдено.') + '</div>';
                footEl.innerHTML = '';
                return;
            }
            var slice = list.slice(visibleCount, visibleCount + PAGE_SIZE);
            slice.forEach(function (it) {
                var row = document.createElement('button');
                row.type = 'button';
                row.className = 'user-picker-row';
                row.textContent = it.label;
                row.addEventListener('click', function () {
                    cfg.onPick(it);
                    if (cfg.single) closeModal();
                    else renderPage(true);
                });
                if (cfg.linkable && it.value) {
                    row.title = 'Клик — выбрать, двойной клик — открыть профиль';
                    row.addEventListener('dblclick', function (e) {
                        e.stopPropagation();
                        window.open('/profile/' + it.value + '/', '_blank');
                    });
                }
                bodyEl.appendChild(row);
            });
            visibleCount += slice.length;
            renderFoot(list.length);
        }

        // Подвал: счётчик + (для remote при усечении) кнопка «показать всех».
        function renderFoot(shownTotal) {
            footEl.innerHTML = '';
            var info = document.createElement('span');
            info.textContent = 'Показано ' + visibleCount + ' из ' + shownTotal;
            footEl.appendChild(info);
            if (cfg.truncated && cfg.onShowAll) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn secondary btn-sm';
                btn.textContent = 'Показать всех';
                btn.addEventListener('click', function () {
                    btn.disabled = true; btn.textContent = 'Загрузка…';
                    cfg.onShowAll();
                });
                footEl.appendChild(btn);
            }
        }

        bodyEl.addEventListener('scroll', function () {
            if (bodyEl.scrollTop + bodyEl.clientHeight >= bodyEl.scrollHeight - 80) renderPage(false);
        });

        var debounceTimer = null;
        searchEl.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () {
                // Remote-выбор (люди) ищет на сервере по всей базе, а не по подгруженной
                // порции; пока ответ не пришёл, показываем локальные совпадения.
                if (cfg && cfg.onQuery) cfg.onQuery(searchEl.value);
                renderPage(true);
            }, 200);
        });

        // Табы ранжирования (только remote): переключение режима перезагружает данные.
        modesEl.querySelectorAll('[data-mode-btn]').forEach(function (b) {
            b.addEventListener('click', function () {
                if (!cfg || !cfg.onOrderChange) return;
                modesEl.querySelectorAll('[data-mode-btn]').forEach(function (o) { o.classList.remove('is-active'); });
                b.classList.add('is-active');
                cfg.onOrderChange(b.getAttribute('data-mode-btn'));
            });
        });

        function closeModal() {
            backdrop.hidden = true;
            cfg = null;
            searchEl.value = '';
            document.body.style.overflow = '';
        }
        closeBtn.addEventListener('click', closeModal);
        backdrop.addEventListener('click', function (e) { if (e.target === backdrop) closeModal(); });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !backdrop.hidden) closeModal(); });

        selectModal = {
            open: function (config) {
                cfg = config;
                backdrop.hidden = false;
                document.body.style.overflow = 'hidden';
                searchEl.value = '';
                modesEl.hidden = !config.onOrderChange; // табы — только у remote
                if (config.loading) {
                    bodyEl.innerHTML = '<div class="cat-chips-empty" style="padding:16px;">Загрузка…</div>';
                    footEl.innerHTML = '';
                } else {
                    renderPage(true);
                }
                searchEl.focus();
            },
            // Перерисовать открытую модалку (remote: после дозагрузки/смены порядка).
            refresh: function (config) {
                if (config) { cfg = config; modesEl.hidden = !config.onOrderChange; }
                if (!backdrop.hidden) renderPage(true);
            },
            isFor: function (token) { return cfg && cfg.token === token; },
        };
        return selectModal;
    }

    // ----------------------------------------------------------------------
    // Remote-режим единого виджета: люди (data-select-remote="users").
    // Данные грузятся с /users/picker-data/ по выбранному порядку. Кэшируем ответ
    // per-order в module-level Map — общий на все виджеты страницы, повторных запросов
    // при том же порядке нет. Выбранные значения уходят скрытыми input[name=field]
    // перед сабмитом формы.
    // ----------------------------------------------------------------------
    var USER_FILTERS = {
        team_lead: function (u) { return u.is_team_lead; },
        not_team_lead: function (u) { return !u.is_team_lead; },
        manager: function (u) { return u.is_manager; },
        not_manager: function (u) { return !u.is_manager; },
    };
    // Поиск (`q`) и фильтр ролей (`filter`) выполняет сервер ДО лимита
    // users_picker_limit — иначе человек вне первой порции не находится.
    var usersCache = {}; // key `${order}|${all}|${filter}|${q}` -> Promise<{users, truncated}>
    function loadUsers(order, all, filter, query) {
        var key = [order, all ? '1' : '0', filter || '', query || ''].join('|');
        if (!usersCache[key]) {
            var url = window.VC_URLS.usersPickerData + '?order=' + encodeURIComponent(order) + (all ? '&all=1' : '') +
                (filter ? '&filter=' + encodeURIComponent(filter) : '') + (query ? '&q=' + encodeURIComponent(query) : '');
            usersCache[key] = fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.json(); })
                .then(function (d) { return { users: d.users || [], truncated: !!d.truncated, total: d.total || 0 }; })
                .catch(function () { delete usersCache[key]; return { users: [], truncated: false, total: 0 }; });
        }
        return usersCache[key];
    }

    function initRemoteSelect(widget, opts) {
        var fieldName = widget.getAttribute('data-field-name');
        var filterKey = USER_FILTERS[widget.getAttribute('data-filter')] ? widget.getAttribute('data-filter') : '';
        var filterFn = USER_FILTERS[filterKey] || null;
        var linkable = widget.hasAttribute('data-linkable');
        var form = widget.closest('form');
        var selected = new Map(); // value(str) -> label
        var searchInput = widget.querySelector('[data-chips-search]');

        // Локальное состояние загрузки: текущий порядок и «показаны все».
        // query — поиск, по которому загружены users; wanted — последний введённый.
        var st = { order: 'recent', all: false, users: [], truncated: false, query: '', wanted: '', searching: false };
        var token = {}; // идентификатор этого виджета для модалки

        function items(query) {
            var pool = filterFn ? st.users.filter(filterFn) : st.users;
            // Сервер уже отобрал по этому запросу (в т.ч. по Telegram, которого нет в
            // подписи) — повторно не фильтруем; иначе — локально до ответа сервера.
            var serverMatched = window.normalizeSearchText(query) === st.query;
            return pool
                .filter(function (u) { return !selected.has(String(u.id)); })
                .filter(function (u) { return !query || serverMatched || window.searchMatches(u.label, query); })
                .map(function (u) { return { value: String(u.id), label: u.label }; });
        }

        function renderSelected() {
            var arr = [];
            selected.forEach(function (label, value) { arr.push({ value: value, label: label }); });
            renderSelectedChips(opts.selectedRow, arr, opts.emptyText, function (value) {
                selected.delete(value); renderSelected();
            });
        }

        function modalConfig() {
            return {
                token: token,
                single: opts.single,
                linkable: linkable,
                truncated: st.truncated,
                searching: st.searching,
                candidates: items,
                onQuery: function (query) {
                    var q = window.normalizeSearchText(query);
                    if (q === st.wanted) return;
                    st.wanted = q;
                    st.searching = true;
                    ensureSelectModal().refresh(modalConfig());
                    load(function () { ensureSelectModal().refresh(modalConfig()); });
                },
                onPick: function (it) {
                    if (opts.single) selected.clear();
                    selected.set(it.value, it.label);
                    renderSelected();
                },
                // Полоса «Выбрано» внутри окна (мультивыбор людей): видно и можно снять.
                selectedItems: function () {
                    var arr = [];
                    selected.forEach(function (label, value) { arr.push({ value: value, label: label }); });
                    return arr;
                },
                onUnpick: function (value) { selected.delete(value); renderSelected(); },
                onOrderChange: function (order) {
                    st.order = order;
                    load(function () { ensureSelectModal().refresh(modalConfig()); });
                },
                onShowAll: function () {
                    st.all = true;
                    load(function () { ensureSelectModal().refresh(modalConfig()); });
                },
            };
        }

        function load(after) {
            var q = st.wanted;
            loadUsers(st.order, st.all, filterKey, q).then(function (res) {
                if (q !== st.wanted) return; // устаревший ответ на прежний запрос
                st.users = res.users; st.truncated = res.truncated; st.query = q; st.searching = false;
                if (after) after();
            });
        }

        function openPicker() {
            var modal = ensureSelectModal();
            // Модалка открывается с пустым поиском — сбрасываем прежний серверный запрос.
            if (st.wanted) { st.wanted = ''; st.query = ''; st.users = []; }
            var cfg = modalConfig();
            if (st.users.length) { modal.open(cfg); }
            else {
                modal.open(Object.assign({ loading: true }, cfg));
                load(function () { if (modal.isFor(token)) modal.refresh(modalConfig()); });
            }
        }

        // Клик по (readonly) полю поиска открывает модалку — ввод только внутри неё.
        if (searchInput) {
            searchInput.setAttribute('readonly', 'readonly');
            searchInput.addEventListener('click', openPicker);
        }
        // Если поля поиска в разметке нет — вешаем на всё поле.
        else widget.addEventListener('click', openPicker);

        // Внешний API (создание нового волонтёра «＋» подкладывает его в выбранные).
        widget._pickerSelected = selected;
        widget._pickerRenderSelected = renderSelected;
        widget._pickerAddUser = function (u) { st.users.push(u); };

        // Предвыбор с сервера: если форма перерисована после ошибки (напр. неверная
        // капча), ранее выбранные пользователи приходят в data-preselect как
        // [{id,label},…] — восстанавливаем их, чтобы ввод не сбрасывался.
        try {
            var pre = JSON.parse(widget.getAttribute('data-preselect') || '[]');
            pre.forEach(function (u) {
                if (u && u.id != null) selected.set(String(u.id), u.label || ('#' + u.id));
            });
        } catch (e) {}

        renderSelected();

        if (form) {
            form.addEventListener('submit', function () {
                widget.querySelectorAll('input[type=hidden][data-picker-value]').forEach(function (el) { el.remove(); });
                selected.forEach(function (label, value) {
                    var hidden = document.createElement('input');
                    hidden.type = 'hidden';
                    hidden.name = fieldName;
                    hidden.value = value;
                    hidden.setAttribute('data-picker-value', '1');
                    widget.appendChild(hidden);
                });
            });
        }
    }

    initEventForm(document);

    // ======================================================================
    // Сортировка таблиц по клику на заголовок — три режима, переключаются по
    // циклу: обычный (без сортировки, порядок с сервера) → по возрастанию →
    // по убыванию → обычный. Стрелка показывается в правом нижнем углу активного
    // заголовка. Значение для сравнения берётся из data-sort-value на <td>
    // (если есть) или из текстового содержимого ячейки; сравнение — числовое,
    // если все значения колонки — числа, иначе алфавитное (localeCompare).
    // ======================================================================
