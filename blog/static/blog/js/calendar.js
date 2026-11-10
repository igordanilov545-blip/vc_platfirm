/*
 * static/blog/js/calendar.js
 * Календари и время: единый datepicker, диапазон дат (report period), timepicker.
 * Берёт утилиты дат из window.CalendarUtils (calendar-utils.js).
 *
 * Часть распила инлайнового JS base.html (см. static/blog/js/README.md).
 * Грузится обычным <script> (не модуль) — все init-функции и хелперы остаются в
 * глобальном scope, как раньше; initPageContent зовёт их через window[fn].
 */
    var DP_MONTHS = window.CalendarUtils.MONTHS;
    var DP_DOW = window.CalendarUtils.DOW;

    var dpParseISO = window.CalendarUtils.parseISO;
    var dpToISO = window.CalendarUtils.toISO;
    var dpFmt = window.CalendarUtils.fmt;
    var dpSameDay = window.CalendarUtils.sameDay;

    function initDatepickers(root) {
        root.querySelectorAll('[data-datepicker]').forEach(function (input) {
            if (input.dataset.dpInit) return;
            input.dataset.dpInit = '1';

            // Дефолт для пустого поля — обычно сегодня, но поле даты рождения задаёт
            // свой сдвиг в годах (data-dp-default-years-ago="18"): открываем календарь
            // сразу на «сегодня минус 18 лет» — средний возраст волонтёра, а не на
            // текущую дату, откуда до нужного года нужно было бы листать вручную.
            var defaultYearsAgo = parseInt(input.getAttribute('data-dp-default-years-ago'), 10) || 0;
            var fallback = new Date();
            if (defaultYearsAgo) fallback.setFullYear(fallback.getFullYear() - defaultYearsAgo);
            var keepEmpty = input.hasAttribute('data-dp-keep-empty');
            // data-dp-popup — компактный режим для таблиц: видно текстовое поле
            // (можно ввести ДД.ММ.ГГГГ вручную), календарь выпадает при фокусе.
            var popup = input.hasAttribute('data-dp-popup');
            var selected = dpParseISO(input.value) || (keepEmpty ? null : fallback);
            var viewDate = selected || fallback;
            var viewMonth = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);

            var wrap = document.createElement('div');
            wrap.className = 'datepicker-wrap';
            input.parentNode.insertBefore(wrap, input);

            // Прошлые даты разрешены (мероприятие можно редактировать задним числом) —
            // календарь всегда виден целиком, как на странице отчётов, без popover.
            var label = document.createElement('span');
            label.className = 'pill neutral datepicker-value';
            label.innerHTML = '<span class="dot"></span><span class="mono"></span>';
            if (!popup) wrap.appendChild(label);

            var cal = document.createElement('div');
            cal.className = 'cal datepicker-inline';
            if (popup) {
                wrap.classList.add('datepicker-popup');
                cal.hidden = true;
            }
            wrap.appendChild(cal);

            // Скрытое поле — реальное значение для сабмита формы (исходное имя
            // Django-поля); видимый input больше не участвует в сабмите. Значение
            // ставим сразу в dpToISO(selected) (а не только когда input.value был
            // непустым) — календарь и так визуально показывает `selected` как текущий
            // выбор (сегодня по умолчанию), так что скрытое поле должно ему соответствовать,
            // иначе форма не отправляет дату, пока пользователь явно не кликнет по дню.
            var hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = input.name;
            hidden.value = selected ? dpToISO(selected) : '';
            input.removeAttribute('name');
            if (popup) {
                input.type = 'text';
                input.value = selected ? dpFmt(selected) : '';
                input.placeholder = input.placeholder || 'ДД.ММ.ГГГГ';
                input.setAttribute('inputmode', 'numeric');
                input.autocomplete = 'off';
                wrap.insertBefore(input, cal);
                var openCal = function () { cal.hidden = false; };
                input.addEventListener('focus', openCal);
                input.addEventListener('click', openCal);
                input.addEventListener('keydown', function (e) { if (e.key === 'Escape') cal.hidden = true; });
                document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) cal.hidden = true; });
                input.addEventListener('change', function () {
                    var raw = input.value.trim();
                    var m = raw.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
                    var parsed = m ? new Date(+m[3], +m[2] - 1, +m[1]) : dpParseISO(raw);
                    if (m && (parsed.getDate() !== +m[1] || parsed.getMonth() !== +m[2] - 1)) parsed = null;
                    if (!raw && keepEmpty) {
                        selected = null;
                    } else if (!parsed) {
                        input.setCustomValidity('Дата в формате ДД.ММ.ГГГГ');
                        input.reportValidity();
                        return;
                    } else {
                        selected = parsed;
                        viewMonth = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
                    }
                    input.setCustomValidity('');
                    hidden.value = selected ? dpToISO(selected) : '';
                    hidden.dataset.isoValue = hidden.value;
                    hidden.dispatchEvent(new Event('change', { bubbles: true }));
                    renderMonth();
                });
            } else {
                input.remove();
            }
            wrap.appendChild(hidden);
            var clearButton;
            if (keepEmpty) {
                clearButton = document.createElement('button');
                clearButton.type = 'button';
                clearButton.className = 'btn secondary small';
                clearButton.textContent = 'Очистить дату';
                clearButton.addEventListener('click', function () {
                    selected = null;
                    hidden.value = '';
                    hidden.dataset.isoValue = '';
                    hidden.dispatchEvent(new Event('change', { bubbles: true }));
                    renderMonth();
                });
                wrap.appendChild(clearButton);
            }

            function renderMonth() {
                var year = viewMonth.getFullYear(), month = viewMonth.getMonth();
                var firstDay = new Date(year, month, 1);
                var startOffset = (firstDay.getDay() + 6) % 7;
                var daysInMonth = new Date(year, month + 1, 0).getDate();
                var today = new Date();

                var html = '<div class="cal-head">'
                    + '<button type="button" data-dp-nav="-1" title="Предыдущий месяц">‹</button>'
                    + '<span class="cal-head-title">' + DP_MONTHS[month]
                    + ' <button type="button" class="cal-year-btn" data-dp-year-toggle>' + year + '</button></span>'
                    + '<button type="button" data-dp-nav="1" title="Следующий месяц">›</button>'
                    + '</div>';
                // Список годов для быстрого перехода (не листать месяцы сотни раз, чтобы
                // дойти до даты рождения) — раскрывается по клику на год в шапке, диапазон
                // с запасом в обе стороны от текущего года.
                var yearListOpen = cal.querySelector('.cal-year-list') && !cal.querySelector('.cal-year-list').hidden;
                html += '<div class="cal-year-list"' + (yearListOpen ? '' : ' hidden') + '>';
                var todayYear = new Date().getFullYear();
                for (var y = todayYear + 5; y >= todayYear - 100; y--) {
                    html += '<div class="cal-year-option' + (y === year ? ' selected' : '') + '" data-dp-year="' + y + '">' + y + '</div>';
                }
                html += '</div>';
                html += '<div class="cal-grid">';
                DP_DOW.forEach(function (d) { html += '<div class="dow">' + d + '</div>'; });
                for (var i = 0; i < startOffset; i++) html += '<div class="day empty"></div>';
                for (var day = 1; day <= daysInMonth; day++) {
                    var d = new Date(year, month, day);
                    var classes = ['day'];
                    if (selected && dpSameDay(d, selected)) classes.push('selected');
                    if (dpSameDay(d, today)) classes.push('today');
                    html += '<div class="' + classes.join(' ') + '" data-dp-date="' + dpToISO(d) + '">' + day + '</div>';
                }
                html += '</div>';
                cal.innerHTML = html;
                label.querySelector('.mono').textContent = selected ? dpFmt(selected) : 'Дата не указана';
                if (popup && document.activeElement !== input) input.value = selected ? dpFmt(selected) : '';
                if (clearButton) clearButton.disabled = !selected;

                cal.querySelectorAll('[data-dp-nav]').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        viewMonth = new Date(viewMonth.getFullYear(), viewMonth.getMonth() + parseInt(btn.getAttribute('data-dp-nav'), 10), 1);
                        renderMonth();
                    });
                });
                var yearList = cal.querySelector('.cal-year-list');
                var yearToggle = cal.querySelector('[data-dp-year-toggle]');
                if (yearToggle && yearList) {
                    yearToggle.addEventListener('click', function (e) {
                        e.stopPropagation();
                        yearList.hidden = !yearList.hidden;
                        if (!yearList.hidden) {
                            var sel = yearList.querySelector('.selected');
                            if (sel) sel.scrollIntoView({ block: 'center' });
                        }
                    });
                    yearList.querySelectorAll('[data-dp-year]').forEach(function (opt) {
                        opt.addEventListener('click', function (e) {
                            e.stopPropagation();
                            viewMonth = new Date(parseInt(opt.getAttribute('data-dp-year'), 10), viewMonth.getMonth(), 1);
                            renderMonth();
                        });
                    });
                }
                cal.querySelectorAll('.day:not(.empty)').forEach(function (cell) {
                    cell.addEventListener('click', function () {
                        selected = dpParseISO(cell.getAttribute('data-dp-date'));
                        hidden.dataset.isoValue = dpToISO(selected);
                        hidden.value = dpToISO(selected);
                        hidden.dispatchEvent(new Event('change', { bubbles: true }));
                        if (popup) {
                            input.value = dpFmt(selected);
                            input.setCustomValidity('');
                            cal.hidden = true;
                        }
                        renderMonth();
                    });
                });
            }

            renderMonth();
        });
    }

    // ======================================================================
    // Пара календарей выбора диапазона (data-range-pair) — «С» / «По» рядом,
    // с Airbnb-подсветкой: концы диапазона залиты акцентом, дни между ними —
    // тем же цветом приглушённо (.range-start/.range-end/.in-range, nexus.css).
    // В отличие от initDatepickers (одиночный выбор на инпут, независимые
    // календари) — здесь оба календаря синхронно знают про обе даты диапазона
    // и перерисовываются вместе при любом клике в любом из них.
    // ======================================================================
    function initDateRangePair(root) {
        root.querySelectorAll('[data-range-pair]').forEach(function (pairEl) {
            if (pairEl.dataset.rangeInit) return;
            pairEl.dataset.rangeInit = '1';

            var startInput = pairEl.querySelector('[data-range-start]');
            var endInput = pairEl.querySelector('[data-range-end]');
            if (!startInput || !endInput) return;

            var rangeStart = dpParseISO(startInput.value) || new Date();
            var rangeEnd = dpParseISO(endInput.value) || rangeStart;
            if (rangeEnd < rangeStart) { var t = rangeStart; rangeStart = rangeEnd; rangeEnd = t; }

            // Два месяца видны сразу — «С» показывает месяц начала диапазона,
            // «По» месяц конца (или следующий, если это тот же месяц — иначе
            // сетки дублировались бы и было бы нечего листать по «По»).
            var viewStart = new Date(rangeStart.getFullYear(), rangeStart.getMonth(), 1);
            var viewEnd = new Date(rangeEnd.getFullYear(), rangeEnd.getMonth(), 1);
            if (viewEnd.getTime() === viewStart.getTime()) {
                viewEnd = new Date(viewStart.getFullYear(), viewStart.getMonth() + 1, 1);
            }

            function buildCalBlock(labelText) {
                var wrap = document.createElement('div');
                wrap.className = 'datepicker-wrap range-pair-cal';
                var label = document.createElement('div');
                label.className = 'range-pair-label';
                label.textContent = labelText;
                wrap.appendChild(label);
                var cal = document.createElement('div');
                cal.className = 'cal datepicker-inline';
                wrap.appendChild(cal);
                return { wrap: wrap, cal: cal };
            }

            var startBlock = buildCalBlock('С');
            var endBlock = buildCalBlock('По');
            pairEl.insertBefore(startBlock.wrap, startInput);
            pairEl.insertBefore(endBlock.wrap, endInput);
            startInput.hidden = true;
            endInput.hidden = true;

            function dayClasses(d) {
                var classes = ['day'];
                var isStart = dpSameDay(d, rangeStart);
                var isEnd = dpSameDay(d, rangeEnd);
                if (isStart) classes.push('range-start');
                if (isEnd) classes.push('range-end');
                if (!isStart && !isEnd && d > rangeStart && d < rangeEnd) classes.push('in-range');
                if (dpSameDay(d, new Date())) classes.push('today');
                return classes;
            }

            function renderCal(block, viewMonth, onNav) {
                var year = viewMonth.getFullYear(), month = viewMonth.getMonth();
                var firstDay = new Date(year, month, 1);
                var startOffset = (firstDay.getDay() + 6) % 7;
                var daysInMonth = new Date(year, month + 1, 0).getDate();

                var html = '<div class="cal-head">'
                    + '<button type="button" data-nav="-1" title="Предыдущий месяц">‹</button>'
                    + '<span class="cal-head-title">' + DP_MONTHS[month] + ' ' + year + '</span>'
                    + '<button type="button" data-nav="1" title="Следующий месяц">›</button>'
                    + '</div>';
                html += '<div class="cal-grid">';
                DP_DOW.forEach(function (d) { html += '<div class="dow">' + d + '</div>'; });
                for (var i = 0; i < startOffset; i++) html += '<div class="day empty"></div>';
                for (var day = 1; day <= daysInMonth; day++) {
                    var d = new Date(year, month, day);
                    html += '<div class="' + dayClasses(d).join(' ') + '" data-date="' + dpToISO(d) + '">' + day + '</div>';
                }
                html += '</div>';
                block.cal.innerHTML = html;

                block.cal.querySelector('[data-nav="-1"]').addEventListener('click', function () { onNav(-1); });
                block.cal.querySelector('[data-nav="1"]').addEventListener('click', function () { onNav(1); });
                block.cal.querySelectorAll('.day:not(.empty)').forEach(function (cell) {
                    cell.addEventListener('click', function () {
                        onDayClick(dpParseISO(cell.getAttribute('data-date')));
                    });
                });
            }

            // Клик по дню — обычная схема двух кликов (Airbnb): диапазон стартует
            // "закрытым" (pickingEnd=false), первый клик всегда начинает НОВЫЙ диапазон
            // (start=end=дата клика); второй клик завершает его (меняет местами, если
            // кликнули раньше начала); третий клик снова начинает новый — и так по кругу.
            var pickingEnd = false;
            function onDayClick(date) {
                var rangeComplete;
                if (!pickingEnd) {
                    // Первый клик — начало НОВОГО диапазона (start=end), ждём второй клик.
                    rangeStart = date;
                    rangeEnd = date;
                    pickingEnd = true;
                    rangeComplete = false;
                } else if (date < rangeStart) {
                    rangeEnd = rangeStart;
                    rangeStart = date;
                    pickingEnd = false;
                    rangeComplete = true;
                } else {
                    rangeEnd = date;
                    pickingEnd = false;
                    rangeComplete = true;
                }
                startInput.value = dpToISO(rangeStart);
                endInput.value = dpToISO(rangeEnd);
                // change диспатчим ТОЛЬКО когда диапазон закрыт (после второго клика) —
                // иначе потребитель (страница отчётов) применил бы охват уже на первом
                // клике (диапазон из одного дня) и перерисовал бы календарь, не дав
                // выбрать конец. Промежуточное состояние идёт в input (для повторного
                // рендера подсветки), но без события применения.
                if (rangeComplete) {
                    startInput.dispatchEvent(new Event('change', { bubbles: true }));
                }
                rerenderBoth();
            }

            function rerenderBoth() {
                renderCal(startBlock, viewStart, function (dir) {
                    viewStart = new Date(viewStart.getFullYear(), viewStart.getMonth() + dir, 1);
                    rerenderBoth();
                });
                renderCal(endBlock, viewEnd, function (dir) {
                    viewEnd = new Date(viewEnd.getFullYear(), viewEnd.getMonth() + dir, 1);
                    rerenderBoth();
                });
            }

            startInput.value = dpToISO(rangeStart);
            endInput.value = dpToISO(rangeEnd);
            rerenderBoth();
        });
    }

    // ======================================================================
    // Time-picker (стиль Яндекс.Календаря): текстовое поле-триггер (только для
    // чтения) + выпадающий список времени с шагом 30 минут, всплывающий поверх
    // остальных полей формы (не раздвигает их). Список рендерится в <body> с
    // position:fixed и координатами от input.getBoundingClientRect() — так он
    // не обрезается overflow модалки/скролла (в отличие от position:absolute
    // относительно обёртки поля).
    // ======================================================================
    function tpPad(n) { return String(n).padStart(2, '0'); }

    function initTimepickers(root) {
        root.querySelectorAll('[data-timepicker]').forEach(function (input) {
            if (input.dataset.tpInit) return;
            input.dataset.tpInit = '1';

            var wrap = document.createElement('div');
            wrap.className = 'timepicker-wrap';
            input.parentNode.insertBefore(wrap, input);
            wrap.appendChild(input);
            input.classList.add('timepicker-input');
            input.readOnly = true;

            var list = document.createElement('div');
            list.className = 'timepicker-list';
            list.hidden = true;
            document.body.appendChild(list);

            var options = [];
            for (var h = 0; h < 24; h++) {
                options.push(tpPad(h) + ':00');
                options.push(tpPad(h) + ':30');
            }

            function positionList() {
                var rect = input.getBoundingClientRect();
                list.style.left = rect.left + 'px';
                list.style.top = (rect.bottom + 6) + 'px';
                list.style.width = rect.width + 'px';
            }

            function renderList() {
                list.innerHTML = '';
                options.forEach(function (value) {
                    var item = document.createElement('div');
                    item.className = 'timepicker-option' + (value === input.value ? ' selected' : '');
                    item.textContent = value;
                    item.addEventListener('click', function () {
                        input.value = value;
                        closeList();
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    });
                    list.appendChild(item);
                });
            }

            function openList() {
                renderList();
                positionList();
                list.hidden = false;
                var selectedEl = list.querySelector('.selected');
                if (selectedEl) selectedEl.scrollIntoView({ block: 'center' });
            }
            function closeList() { list.hidden = true; }

            input.addEventListener('click', function () {
                list.hidden ? openList() : closeList();
            });
            document.addEventListener('click', function (event) {
                if (event.target !== input && event.target !== list && !list.contains(event.target)) closeList();
            });
            window.addEventListener('scroll', function () { if (!list.hidden) positionList(); }, true);
            window.addEventListener('resize', function () { if (!list.hidden) positionList(); });
        });
    }

    // ======================================================================
    // ЕДИНЫЙ ВИДЖЕТ ВЫБОРА «n из m» (data-chip-select).
    //
    // Одна точка входа решает, КАК показать выбор, по числу вариантов:
    //   • вариантов ≤ SELECT_INLINE_MAX  → чипы прямо на форме (выбранные сверху с
    //     крестиком, доступные снизу — клик добавляет). Как выбор тим-лидеров/категорий.
    //   • вариантов >  SELECT_INLINE_MAX → компактное поле-триггер; по клику открывается
    //     ОДНА НА СТРАНИЦУ прокручиваемая модалка со строкой поиска (фильтр по подстроке)
    //     и списком всех вариантов подряд. Выбранные всё равно рендерятся чипами под полем.
    //
    // Источник вариантов:
    //   • по умолчанию — скрытый <select multiple> (id = значение data-chip-select).
    //     Значения известны на клиенте сразу, число считаем по <option>.
    //   • data-select-remote="users" — варианты грузятся с сервера (тысячи людей нельзя
    //     рендерить в <select>): всегда модалка, с ранжированием (недавние/по имени),
    //     лимитом и кнопкой «показать всех». <select> для таких виджетов не нужен —
    //     значения уходят скрытыми <input name=data-field-name> перед сабмитом формы.
    //
    // data-chip-single — одиночный выбор (напр. ответственный менеджер): новый выбор
    //   снимает предыдущий, для remote — модалка закрывается сразу.
    // ======================================================================
