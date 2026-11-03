/*
 * static/blog/js/tables.js
 * Таблицы-списки: сортировка, скрытие/возврат колонок, инструменты отчётных
 * таблиц (колонки+фильтр), поиск строк, infinite-scroll, сворачивание.
 *
 * Часть распила инлайнового JS base.html (см. static/blog/js/README.md).
 * Грузится обычным <script> (не модуль) — все init-функции и хелперы остаются в
 * глобальном scope, как раньше; initPageContent зовёт их через window[fn].
 */
    function initSortableTables(root) {
        root.querySelectorAll('table[data-sortable]').forEach(function (table) {
            if (table.dataset.sortInit) return;
            table.dataset.sortInit = '1';

            var headers = Array.prototype.slice.call(table.querySelectorAll('thead th[data-sort-key]'));
            var tbody = table.querySelector('tbody');
            if (!tbody) return;

            var nextOrigIndex = 0;
            function getRows() {
                var rows = Array.prototype.filter.call(tbody.querySelectorAll('tr'), function (tr) {
                    return tr.querySelector('td') && !tr.hasAttribute('data-table-empty') && !tr.querySelector('td[colspan]');
                });
                // Строки, подгруженные позже (infinite scroll), ещё не имеют origIndex —
                // присваиваем по мере появления, чтобы "обычный" режим сортировки не
                // ломался и продолжал восстанавливать порядок с сервера.
                rows.forEach(function (row) {
                    if (row.dataset.origIndex === undefined) row.dataset.origIndex = nextOrigIndex++;
                });
                return rows;
            }

            function cellValue(row, index) {
                var cell = row.children[index];
                if (!cell) return '';
                return cell.hasAttribute('data-sort-value') ? cell.getAttribute('data-sort-value') : cell.textContent.trim();
            }

            function clearIndicators(except) {
                headers.forEach(function (h) {
                    if (h !== except) { h.removeAttribute('data-sort-dir'); }
                });
            }

            function sortRows(th, next) {
                    var index = th.cellIndex;
                    var rows = getRows();
                    if (!next) {
                        // Обычный режим — восстановить исходный порядок с сервера.
                        rows.sort(function (a, b) {
                            return (+a.dataset.origIndex || 0) - (+b.dataset.origIndex || 0);
                        });
                    } else {
                        var allNumeric = rows.every(function (r) {
                            var v = cellValue(r, index);
                            return v === '' || !isNaN(parseFloat(v));
                        });
                        rows.sort(function (a, b) {
                            var va = cellValue(a, index), vb = cellValue(b, index);
                            var cmp;
                            if (allNumeric) {
                                cmp = (parseFloat(va) || 0) - (parseFloat(vb) || 0);
                            } else {
                                cmp = va.localeCompare(vb, 'ru');
                            }
                            return next === 'asc' ? cmp : -cmp;
                        });
                    }
                    rows.forEach(function (r) { tbody.appendChild(r); });
            }
            table._applyTableSort = function () {
                var active = headers.find(function (th) { return th.hasAttribute('data-sort-dir'); });
                if (active) sortRows(active, active.getAttribute('data-sort-dir'));
            };
            headers.forEach(function (th) {
                th.classList.add('sortable-th');
                th.addEventListener('click', function () {
                    var current = th.getAttribute('data-sort-dir');
                    var next = current === 'asc' ? 'desc' : (current === 'desc' ? null : 'asc');
                    clearIndicators(th);
                    if (next) th.setAttribute('data-sort-dir', next);
                    else th.removeAttribute('data-sort-dir');
                    sortRows(th, next);
                });
            });

            // Запоминаем исходный порядок строк, чтобы можно было вернуться к нему.
            getRows();

            // Опциональная колонка с сортировкой по умолчанию при загрузке страницы.
            var defaultTh = headers.find(function (h) { return h.hasAttribute('data-sort-default'); });
            if (defaultTh) {
                defaultTh.setAttribute('data-sort-dir', defaultTh.getAttribute('data-sort-default'));
                table._applyTableSort();
            }
        });
    }
    initSortableTables(document);

    // ======================================================================
    // Скрытие/возврат колонок в стиле Excel — таблица с data-hideable-columns.
    //  - у каждого заголовка появляется кнопка-«глаз» 👁, прячущая колонку
    //    (заголовок + все ячейки этого столбца во всех строках, включая
    //    подгруженные позже infinite-scroll'ом);
    //  - для каждого непрерывного «прогона» скрытых колонок на ближайшей видимой
    //    границе (справа, иначе слева) рисуется стрелка-возврат ◂/▸ — клик по ней
    //    возвращает ВСЕ скрытые между этими соседями колонки разом.
    // Совместимо с data-sortable (индексы колонок не меняются — колонка лишь
    // display:none) и data-infinite-scroll (applyHidden вызывается для новых строк).
    // ======================================================================
    function initHideableColumns(root) {
        root.querySelectorAll('table[data-hideable-columns]').forEach(function (table) {
            if (table.dataset.hideInit) return;
            table.dataset.hideInit = '1';

            var headRow = table.querySelector('thead tr');
            var tbody = table.querySelector('tbody');
            if (!headRow || !tbody) return;

            var headers = Array.prototype.filter.call(headRow.children, function (el) {
                return el.tagName === 'TH';
            });
            var hidden = {}; // индекс колонки -> true

            // Проставляем индекс колонки на каждый заголовок и добавляем «глаз».
            headers.forEach(function (th, index) {
                th.dataset.col = index;
                th.classList.add('hideable-th');
                // Колонку без осмысленного заголовка (пустой th действий) прятать
                // не даём — «глаз» вешаем только на именованные колонки.
                if (!th.textContent.trim()) return;
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'col-hide-btn';
                btn.title = 'Скрыть колонку';
                btn.textContent = '👁';
                btn.addEventListener('click', function (e) {
                    e.stopPropagation(); // не триггерить сортировку заголовка
                    hidden[index] = true;
                    refresh();
                });
                th.appendChild(btn);
            });

            function bodyCells(index) {
                // index-я ячейка каждой строки тела (по порядку колонок).
                var cells = [];
                Array.prototype.forEach.call(tbody.querySelectorAll('tr'), function (tr) {
                    var tds = tr.children;
                    if (tds[index]) cells.push(tds[index]);
                });
                return cells;
            }

            function clearRevealMarkers() {
                table.querySelectorAll('.col-reveal-btn').forEach(function (b) { b.remove(); });
                table.querySelectorAll('.has-reveal').forEach(function (c) { c.classList.remove('has-reveal'); });
            }

            // Применяет текущее состояние hidden к заголовкам и телу (в т.ч. к строкам,
            // добавленным после инициализации — вызывается и из infinite-scroll).
            function applyHidden() {
                headers.forEach(function (th, index) {
                    var isHidden = !!hidden[index];
                    th.classList.toggle('col-hidden', isHidden);
                    bodyCells(index).forEach(function (cell) {
                        cell.classList.toggle('col-hidden', isHidden);
                    });
                });
            }

            function revealRange(fromIndex, toIndex) {
                for (var i = fromIndex; i <= toIndex; i++) { delete hidden[i]; }
                refresh();
            }

            // Рисует стрелки-возврат: для каждого непрерывного прогона скрытых колонок
            // ставит одну стрелку на ближайшей видимой соседней колонке.
            function drawRevealMarkers() {
                clearRevealMarkers();
                var n = headers.length;
                var i = 0;
                while (i < n) {
                    if (!hidden[i]) { i++; continue; }
                    var start = i;
                    while (i < n && hidden[i]) { i++; }
                    var end = i - 1; // [start..end] — прогон скрытых колонок
                    var rightVisible = i < n ? i : -1;        // ближайшая видимая справа
                    var leftVisible = start - 1 >= 0 ? start - 1 : -1; // ближайшая видимая слева
                    var anchorIndex, direction;
                    if (rightVisible !== -1) { anchorIndex = rightVisible; direction = '◂'; }
                    else if (leftVisible !== -1) { anchorIndex = leftVisible; direction = '▸'; }
                    else { continue; } // скрыты все колонки — возвращать некуда (не бывает, «глаз» не у всех)

                    placeReveal(headers[anchorIndex], direction, start, end);
                    // Дублируем стрелку на первую ячейку тела той же колонки, чтобы
                    // указатель был виден и в области данных, а не только в шапке.
                    var anchorCells = bodyCells(anchorIndex);
                    if (anchorCells.length) placeReveal(anchorCells[0], direction, start, end);
                }
            }

            function placeReveal(anchorEl, direction, start, end) {
                anchorEl.classList.add('has-reveal');
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'col-reveal-btn';
                btn.title = 'Показать скрытые колонки';
                btn.textContent = direction;
                btn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    revealRange(start, end);
                });
                anchorEl.appendChild(btn);
            }

            function refresh() {
                applyHidden();
                drawRevealMarkers();
            }

            // Доступ извне: infinite-scroll после вставки новых строк вызывает это,
            // чтобы к ним применилось текущее скрытие колонок.
            table._applyHiddenColumns = refresh;

            refresh();
        });
    }
    initHideableColumns(document);

    // ======================================================================
    // Инструменты таблицы отчётов (data-report-tools): панель НАД таблицей с
    //  1) переключателем колонок — чипы «показать/скрыть» по механике выбора смен
    //     мероприятия (клик по чипу прячет/возвращает колонку целиком, без
    //     перезагрузки; скрытая колонка = display:none у th и всех td);
    //  2) фильтром-исключением значений по колонке (как автофильтр Excel): клик по
    //     «▾» в заголовке открывает список уникальных значений колонки с галочками —
    //     снятая галочка прячет строки с этим значением.
    // Сортировка (data-sortable) продолжает работать: скрытие/фильтрация — это только
    // display:none, индексы колонок и порядок строк не трогаются. Всё клиентское —
    // строится из уже отрендеренной таблицы, никаких запросов на сервер.
    // Разметка: <div data-report-tools data-table="#id"></div> прямо перед таблицей.
    // ======================================================================
    function initReportTableTools(root) {
        root.querySelectorAll('[data-report-tools]').forEach(function (bar) {
            if (bar.dataset.toolsInit) return;
            bar.dataset.toolsInit = '1';
            var table = document.querySelector(bar.getAttribute('data-table'));
            if (!table) return;
            var headRow = table.querySelector('thead tr');
            var tbody = table.querySelector('tbody');
            if (!headRow || !tbody) return;
            var headers = Array.prototype.filter.call(headRow.children, function (el) { return el.tagName === 'TH'; });

            // Множества исключённых значений по индексу колонки (для фильтра).
            var excluded = {}; // colIndex -> Set(values)

            function dataRows() {
                return Array.prototype.filter.call(tbody.querySelectorAll('tr'), function (tr) {
                    return tr.querySelector('td') && !tr.querySelector('td[colspan]');
                });
            }
            function cellText(row, index) {
                var cell = row.children[index];
                if (!cell) return '';
                return (cell.getAttribute('data-filter-value') || cell.textContent || '').trim();
            }

            // --- Скрытие колонок ---
            function setColHidden(index, hidden) {
                var th = headers[index];
                if (th) th.classList.toggle('col-hidden', hidden);
                dataRows().forEach(function (row) {
                    if (row.children[index]) row.children[index].classList.toggle('col-hidden', hidden);
                });
            }

            // --- Фильтрация строк по исключённым значениям ---
            function applyFilters() {
                dataRows().forEach(function (row) {
                    var hide = false;
                    Object.keys(excluded).forEach(function (idx) {
                        if (excluded[idx].size && excluded[idx].has(cellText(row, +idx))) hide = true;
                    });
                    row.hidden = hide;
                });
            }

            // Панель чипов-колонок.
            var chipWrap = document.createElement('div');
            chipWrap.className = 'rtt-cols';
            var chipLabel = document.createElement('span');
            chipLabel.className = 'rtt-label';
            chipLabel.textContent = 'Колонки:';
            chipWrap.appendChild(chipLabel);

            headers.forEach(function (th, index) {
                var name = (th.getAttribute('data-col-name') || th.textContent || '').trim();
                if (!name) return; // безымянные (действия) не переключаем
                var chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'rtt-col-chip active';
                chip.textContent = name;
                chip.addEventListener('click', function () {
                    var nowHidden = chip.classList.toggle('rtt-off');
                    chip.classList.toggle('active', !nowHidden);
                    setColHidden(index, nowHidden);
                });
                chipWrap.appendChild(chip);

                // Кнопка фильтра-исключения значений в заголовке колонки.
                if (th.hasAttribute('data-filterable')) {
                    var fbtn = document.createElement('button');
                    fbtn.type = 'button';
                    fbtn.className = 'rtt-filter-btn';
                    fbtn.title = 'Фильтр значений';
                    fbtn.textContent = '▾';
                    fbtn.addEventListener('click', function (e) {
                        e.stopPropagation();
                        openFilterMenu(index, fbtn, name);
                    });
                    th.appendChild(fbtn);
                }
            });
            bar.appendChild(chipWrap);

            // Меню фильтра значений (одно на таблицу, переиспользуется).
            var menu = null;
            function openFilterMenu(index, anchor, name) {
                closeFilterMenu();
                var values = {};
                dataRows().forEach(function (row) { values[cellText(row, index)] = true; });
                var uniq = Object.keys(values).sort(function (a, b) { return a.localeCompare(b, 'ru'); });
                excluded[index] = excluded[index] || new Set();

                menu = document.createElement('div');
                menu.className = 'rtt-filter-menu';
                var head = document.createElement('div');
                head.className = 'rtt-filter-head';
                head.innerHTML = '<b>' + name + '</b>';
                var actions = document.createElement('div');
                actions.className = 'rtt-filter-actions';
                var allBtn = document.createElement('button'); allBtn.type = 'button'; allBtn.textContent = 'Все';
                var noneBtn = document.createElement('button'); noneBtn.type = 'button'; noneBtn.textContent = 'Снять все';
                actions.appendChild(allBtn); actions.appendChild(noneBtn);
                head.appendChild(actions);
                menu.appendChild(head);

                var list = document.createElement('div');
                list.className = 'rtt-filter-list';
                uniq.forEach(function (val) {
                    var lab = document.createElement('label');
                    var cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.checked = !excluded[index].has(val);
                    cb.addEventListener('change', function () {
                        if (cb.checked) excluded[index].delete(val); else excluded[index].add(val);
                        applyFilters();
                    });
                    lab.appendChild(cb);
                    lab.appendChild(document.createTextNode(' ' + (val || '(пусто)')));
                    list.appendChild(lab);
                });
                menu.appendChild(list);
                allBtn.addEventListener('click', function () {
                    excluded[index].clear();
                    list.querySelectorAll('input').forEach(function (c) { c.checked = true; });
                    applyFilters();
                });
                noneBtn.addEventListener('click', function () {
                    uniq.forEach(function (v) { excluded[index].add(v); });
                    list.querySelectorAll('input').forEach(function (c) { c.checked = false; });
                    applyFilters();
                });

                document.body.appendChild(menu);
                var rect = anchor.getBoundingClientRect();
                menu.style.left = Math.min(rect.left, window.innerWidth - 260) + 'px';
                menu.style.top = (rect.bottom + window.scrollY + 4) + 'px';
                setTimeout(function () { document.addEventListener('click', outsideClose); }, 0);
            }
            function outsideClose(e) { if (menu && !menu.contains(e.target)) closeFilterMenu(); }
            function closeFilterMenu() {
                if (menu) { menu.remove(); menu = null; document.removeEventListener('click', outsideClose); }
            }
        });
    }
    initReportTableTools(document);

    // ======================================================================
    // Единый поиск: все слова в любом порядке, без регистра, ё/е и лишних пробелов.
    // GET-форма data-table-query-form отправляет q/role серверу до пагинации.
    // Остальные таблицы фильтруются локально; устаревшие ответы не подменяют поиск.
    // ======================================================================
    function initTableFilter(root) {
        root.querySelectorAll('[data-table-filter]').forEach(function (input) {
            if (input.dataset.filterInit) return;
            input.dataset.filterInit = '1';

            var table = document.querySelector(input.getAttribute('data-table-filter'));
            if (!table) return;
            // Списки позиций совмещают поиск с существующим тумблером прошедших смен.
            var passedSelector = input.getAttribute('data-table-hide-passed');
            var hidePassed = passedSelector ? document.querySelector(passedSelector) : null;
            var roleFilter = Array.from(document.querySelectorAll('[data-table-role-filter]')).find(function (select) {
                return select.getAttribute('data-table-role-filter') === input.getAttribute('data-table-filter');
            });
            var delay = parseInt(input.getAttribute('data-filter-debounce'), 10);
            if (isNaN(delay)) delay = 200;
            var debounceTimer = null;
            var serverForm = input.closest('form[data-table-query-form]');
            var emptyRow = table.querySelector('[data-table-empty]') || document.createElement('tr');
            emptyRow.setAttribute('data-table-empty', '');
            var emptyCell = emptyRow.querySelector('td') || document.createElement('td');
            emptyCell.setAttribute('role', 'status');
            emptyRow.appendChild(emptyCell);
            table.querySelector('tbody').appendChild(emptyRow);

            function normalize(value) {
                return (value || '').toLowerCase().replace(/ё/g, 'е').replace(/@/g, '').replace(/\s+/g, ' ').trim();
            }

            function apply() {
                var tokens = normalize(input.value).split(' ').filter(Boolean);
                var role = roleFilter ? roleFilter.value : '';
                var filtered = tokens.length || role || (hidePassed && hidePassed.checked);
                var pager = table._tablePager;
                if (serverForm && pager) pager.search(input.value, role).catch(function () {});
                else if ((tokens.length || role) && pager && !pager.complete && !pager.failed) pager.ensureAll().catch(function () {});
                var visible = 0;
                table.querySelectorAll('tbody tr[data-search]').forEach(function (row) {
                    var text = normalize(row.getAttribute('data-search'));
                    var matchesSearch = tokens.every(function (token) { return text.indexOf(token) !== -1; });
                    var matchesPassed = !hidePassed || !hidePassed.checked || row.getAttribute('data-passed') !== '1';
                    row.hidden = !(matchesSearch && matchesPassed && (!role || row.dataset.role === role)) || !!(serverForm && pager && pager.loading);
                    if (!row.hidden) visible++;
                });
                // Серверные сообщения «список пуст» не подменяют результат поиска.
                table.querySelectorAll('tbody tr:not([data-search]):not([data-table-empty])').forEach(function (row) {
                    row.hidden = !!filtered;
                });
                if (!emptyRow.isConnected) table.querySelector('tbody').appendChild(emptyRow);
                emptyCell.colSpan = table.querySelectorAll('thead th').length || 1;
                emptyCell.textContent = pager && !pager.complete && filtered
                    ? (pager.failed ? 'Не удалось загрузить всю таблицу. Повторите загрузку.' : 'Поиск по всей таблице…')
                    : 'Совпадений не найдено.';
                emptyRow.hidden = visible > 0 || (!filtered && table.querySelector('tbody tr:not([data-table-empty])') !== null);
            }
            input.addEventListener('input', function () {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(apply, delay);
            });
            if (hidePassed) hidePassed.addEventListener('change', apply);
            if (roleFilter) roleFilter.addEventListener('change', apply);
            if (serverForm) serverForm.addEventListener('submit', function (event) {
                if (!table._tablePager) return; // The ordinary GET form remains usable without enhancement.
                event.preventDefault();
                clearTimeout(debounceTimer);
                apply();
            });
            table.addEventListener('table:rowschanged', apply);
            apply();
        });
    }
    initTableFilter(document);

    // ======================================================================
    // Постепенная/полная загрузка — один компонент. Полный ответ хранится в обычном
    // приватном HTTP-кэше браузера с ETag. В localStorage — только выбор «всё»,
    // отдельно для аккаунта и URL; персональные строки туда не копируются.
    // ======================================================================
    function initInfiniteScroll(root) {
        root.querySelectorAll('table[data-infinite-scroll]').forEach(function (table) {
            if (table.dataset.infiniteInit) return;
            table.dataset.infiniteInit = '1';

            var baseUrl = table.getAttribute('data-infinite-scroll');
            var pageController = null;
            var fullController = null;
            var allPromise = null;
            var generation = 0;
            var owner = table.getAttribute('data-table-cache-owner') || '';
            var cacheKey = 'vc:full-table:v1:' + owner + ':' + baseUrl;
            var tools = table.parentNode.querySelector('[data-table-load-tools]') || document.createElement('div');
            tools.className = 'table-load-tools';
            var loadAll = tools.querySelector('[data-table-load-all]') || document.createElement('button');
            if (loadAll.tagName === 'BUTTON') loadAll.type = 'button';
            loadAll.className = 'btn secondary btn-sm';
            loadAll.textContent = 'Подгрузить всё';
            loadAll.setAttribute('data-table-load-all', '');
            var status = tools.querySelector('[data-table-result-count]') || document.createElement('span');
            status.setAttribute('role', 'status');
            tools.appendChild(status);
            tools.appendChild(loadAll);
            var loadMore = tools.querySelector('[data-table-next]') || document.createElement('button');
            if (loadMore.tagName === 'BUTTON') loadMore.type = 'button';
            loadMore.className = 'btn secondary btn-sm';
            loadMore.textContent = 'Показать ещё';
            tools.appendChild(loadMore);
            table.parentNode.insertBefore(tools, table);

            var sentinel = document.createElement('div');
            sentinel.className = 'infinite-scroll-sentinel';
            table.parentNode.insertBefore(sentinel, table.nextSibling);

            function currentBody() { return table.querySelector('tbody[data-rows]'); }
            function isComplete(body) {
                return body.hasAttribute('data-total')
                    ? body.querySelectorAll('tr[data-search]').length >= Number(body.getAttribute('data-total'))
                    : !body.getAttribute('data-next-page');
            }
            var pager = table._tablePager = {
                complete: isComplete(currentBody()),
                failed: false,
                loading: false,
                ensureAll: ensureAll,
                search: search,
            };
            var parameters = { q: currentBody().getAttribute('data-query') || '', role: currentBody().getAttribute('data-role-filter') || '' };

            function search(query, role) {
                query = query.trim().replace(/\s+/g, ' ').slice(0, 255);
                if (parameters.q === query && parameters.role === role) {
                    return (query || role) && !pager.complete && !pager.failed ? ensureAll() : Promise.resolve();
                }
                generation++;
                if (pageController) { pageController.abort(); pageController = null; }
                if (fullController) { fullController.abort(); fullController = null; }
                allPromise = null;
                parameters = { q: query, role: role };
                pager.complete = false;
                return ensureAll();
            }

            function update() {
                var body = currentBody();
                var count = body.querySelectorAll('tr[data-search]').length;
                var total = body.getAttribute('data-total');
                loadAll.hidden = pager.complete;
                loadAll.disabled = pager.loading;
                loadMore.hidden = !body.getAttribute('data-next-page') || pager.loading;
                status.textContent = pager.loading ? (parameters.q || parameters.role ? 'Поиск по всей базе…' : 'Загружаем всю таблицу…') :
                    (pager.failed ? 'Не удалось загрузить. Нажмите «Подгрузить всё» для повтора.' :
                    'Найдено: ' + (total || count) + ' · Показано: ' + count + (total ? ' из ' + total : ''));
                table.setAttribute('aria-busy', pager.loading ? 'true' : 'false');
                if (table._applyHiddenColumns) table._applyHiddenColumns();
                if (table._applyTableSort) table._applyTableSort();
                table.dispatchEvent(new CustomEvent('table:rowschanged'));
            }

            function request(paging, controller) {
                var url = new URL(baseUrl, location.origin);
                Object.keys(parameters).forEach(function (key) {
                    if (parameters[key]) url.searchParams.set(key, parameters[key]);
                });
                Object.keys(paging).forEach(function (key) { url.searchParams.set(key, paging[key]); });
                // Different accounts never share an HTTP-cache entry.
                if (owner) url.searchParams.set('table_owner', owner);
                return fetch(url.href, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    signal: controller ? controller.signal : undefined,
                }).then(function (response) {
                    if (!response.ok || response.redirected) throw new Error('Table request failed');
                    return response.text();
                }).then(function (html) {
                    var temp = document.createElement('table');
                    temp.innerHTML = html;
                    var body = temp.querySelector('tbody[data-rows]');
                    if (!body) throw new Error('Table rows missing');
                    return body;
                });
            }

            function ensureAll() {
                if (pager.complete) return Promise.resolve();
                if (allPromise) return allPromise;
                generation++;
                var requestGeneration = generation;
                if (pageController) { pageController.abort(); pageController = null; }
                pager.failed = false;
                pager.loading = true;
                var controller = fullController = new AbortController();
                allPromise = request({ all: '1' }, controller).then(function (body) {
                    if (requestGeneration !== generation) return;
                    if (!isComplete(body)) throw new Error('Incomplete table response');
                    body.querySelectorAll('[data-table-empty]').forEach(function (row) { row.remove(); });
                    var target = currentBody();
                    var fragment = document.createDocumentFragment();
                    while (body.firstChild) fragment.appendChild(body.firstChild);
                    target.replaceChildren(fragment);
                    target.setAttribute('data-next-page', '');
                    target.setAttribute('data-total', body.getAttribute('data-total') || '');
                    pager.complete = true;
                    if (!parameters.q && !parameters.role) {
                        try { localStorage.setItem(cacheKey, '1'); } catch (error) {}
                    }
                }).catch(function (error) {
                    if (error.name !== 'AbortError' && requestGeneration === generation) pager.failed = true;
                    throw error;
                }).finally(function () {
                    if (requestGeneration !== generation) return;
                    allPromise = null;
                    fullController = null;
                    pager.loading = false;
                    update();
                });
                update();
                return allPromise;
            }
            loadAll.addEventListener('click', function (event) {
                event.preventDefault();
                ensureAll().catch(function () {});
            });
            loadMore.addEventListener('click', function (event) { event.preventDefault(); loadNext(); });

            function loadNext() {
                var body = currentBody();
                var nextPage = body ? body.getAttribute('data-next-page') : '';
                if (!nextPage || pageController || allPromise || pager.failed || pager.complete) return;
                var requestGeneration = generation;
                var controller = pageController = new AbortController();
                request({ page: nextPage }, controller).then(function (newBody) {
                    if (requestGeneration !== generation) return;
                    var target = currentBody();
                    target.setAttribute('data-next-page', newBody.getAttribute('data-next-page') || '');
                    while (newBody.firstChild) target.appendChild(newBody.firstChild);
                    pager.complete = isComplete(target);
                }).catch(function (error) {
                    if (error.name !== 'AbortError' && requestGeneration === generation) pager.failed = true;
                }).finally(function () {
                    if (pageController === controller) pageController = null;
                    if (requestGeneration === generation) update();
                });
            }

            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) loadNext();
                });
            }, { rootMargin: '400px' });
            observer.observe(sentinel);
            update();
            try {
                if (localStorage.getItem(cacheKey) === '1') ensureAll().catch(function () {});
            } catch (error) {}
        });
    }
    initInfiniteScroll(document);

    // ======================================================================
    // Сворачивание длинных таблиц: <table data-collapse-rows="5"> показывает первые
    // 5 строк tbody, остальные прячет и добавляет кнопку «Показать все (N) / Свернуть».
    // Переиспользуется на всех страницах, где нужно показывать только первые N записей
    // (профиль: заявки/участия/опыт и т.п.). Совместимо с data-sortable/-hideable-columns.
    // ======================================================================
    function initCollapsibleTables(root) {
        root.querySelectorAll('table[data-collapse-rows]').forEach(function (table) {
            if (table.dataset.collapseInit) return;
            table.dataset.collapseInit = '1';

            var limit = parseInt(table.getAttribute('data-collapse-rows'), 10) || 5;
            var tbody = table.querySelector('tbody');
            if (!tbody) return;
            var dataRows = Array.prototype.filter.call(tbody.querySelectorAll('tr'), function (tr) {
                return tr.querySelector('td') && !tr.querySelector('td[colspan]');
            });
            if (dataRows.length <= limit) return; // сворачивать нечего

            var expanded = false;
            function apply() {
                dataRows.forEach(function (tr, i) { tr.hidden = !expanded && i >= limit; });
            }
            apply();

            // Кнопка-переключатель под таблицей.
            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'btn secondary btn-sm table-collapse-toggle';
            toggle.style.margin = '10px 20px 16px';
            function label() {
                toggle.textContent = expanded ? 'Свернуть' : ('Показать все (' + dataRows.length + ')');
            }
            label();
            toggle.addEventListener('click', function () {
                expanded = !expanded;
                apply();
                label();
            });
            table.parentNode.insertBefore(toggle, table.nextSibling);
        });
    }
    initCollapsibleTables(document);

    // ======================================================================
    // Универсальное подтверждение перед отправкой формы (защита от мисс-клика):
    // на форме указывается data-confirm="Текст вопроса"; при сабмите показываем
    // confirm() и прерываем отправку, если пользователь не подтвердил.
    // Идемпотентно (data-confirmInit) — можно вызывать на подгруженном AJAX'ом
    // контенте (напр. панели настроек), не навешивая обработчик повторно.
    // ======================================================================
