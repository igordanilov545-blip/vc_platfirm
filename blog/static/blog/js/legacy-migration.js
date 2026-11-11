/**
 * Миграция старых баз (documentation/legacy-migration.md):
 * - initMigrationJobs: [data-migration-job] — опрос фоновой загрузки (процент, полоса),
 *   кнопка «Отменить загрузку» раскрывает подтверждение «Да, отменить» (без confirm());
 * - initMappingRows: [data-mapping-row] — поле «Новая позиция» показывается только
 *   при выборе «＋ Новая позиция»; ввод в нём сам выбирает этот вариант;
 *   [data-mapping-filter] — «только несопоставленные».
 * Обычный <script>, функции глобальные; initPageContent вызывает их после мягкой навигации.
 */
    function initMigrationJobs(root) {
        root.querySelectorAll('[data-migration-job]').forEach(function (box) {
            if (box.dataset.jobInit) return;
            box.dataset.jobInit = '1';
            var url = box.getAttribute('data-status-url');
            var label = box.querySelector('[data-job-label]');
            var bar = box.querySelector('[data-job-bar]');
            var cancel = box.querySelector('[data-job-cancel]');
            var confirmBox = box.querySelector('[data-job-confirm]');
            var message = box.querySelector('[data-job-message]');
            if (cancel && confirmBox) {
                cancel.addEventListener('click', function () {
                    confirmBox.hidden = false;
                    cancel.hidden = true;
                });
                var no = confirmBox.querySelector('[data-job-confirm-no]');
                if (no) no.addEventListener('click', function () {
                    confirmBox.hidden = true;
                    cancel.hidden = false;
                });
            }
            function render(data) {
                if (label) label.textContent = data.cancel_requested && data.status === 'running' ? 'Отменяем загрузку…' : data.label;
                if (bar) bar.style.width = data.percent + '%';
                if (message) {
                    message.textContent = data.message || '';
                    message.hidden = !data.message;
                }
                var finished = data.status !== 'running';
                box.classList.toggle('is-finished', finished);
                box.dataset.jobStatus = data.status;
                if (finished) {
                    if (cancel) cancel.hidden = true;
                    if (confirmBox) confirmBox.hidden = true;
                }
                return finished;
            }
            function poll() {
                if (!document.body.contains(box)) return;
                fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
                    .then(function (response) { return response.json(); })
                    .then(function (data) {
                        var finished = render(data);
                        if (!finished) {
                            setTimeout(poll, 1500);
                        } else if (box.hasAttribute('data-reload-on-finish') && data.status !== 'stale') {
                            setTimeout(function () { window.location.reload(); }, 1200);
                        }
                    })
                    .catch(function () { setTimeout(poll, 4000); });
            }
            poll();
        });
    }
    initMigrationJobs(document);

    function initMappingRows(root) {
        root.querySelectorAll('[data-mapping-row]').forEach(function (row) {
            if (row.dataset.mappingInit) return;
            row.dataset.mappingInit = '1';
            var select = row.querySelector('[data-target-select]');
            var wrap = row.querySelector('[data-new-title-wrap]');
            var input = row.querySelector('[data-new-title]');
            if (!select || !wrap || !input) return;
            function sync() {
                var isNew = select.value === 'new';
                wrap.classList.toggle('is-hidden', !isNew);
                row.classList.toggle('is-unmapped', !select.value);
            }
            select.addEventListener('change', function () {
                sync();
                if (select.value === 'new') input.focus();
            });
            // Функция → позиции только этой функции; «＋ Новая функция» — поле названия.
            var functionSelect = row.querySelector('[data-function-select]');
            var functionWrap = row.querySelector('[data-new-function-wrap]');
            function filterPositions() {
                if (!functionSelect) return;
                var chosen = functionSelect.value;
                if (functionWrap) functionWrap.classList.toggle('is-hidden', chosen !== 'new');
                Array.prototype.forEach.call(select.options, function (option) {
                    var own = option.getAttribute('data-function');
                    if (own === null) return;  // «не выбрано», «пропустить», «новая»
                    option.hidden = !!chosen && chosen !== 'new' && own !== chosen;
                });
                if (select.selectedOptions[0] && select.selectedOptions[0].hidden) {
                    select.value = 'new';
                    sync();
                }
                if (chosen === 'new' && select.value !== 'skip') {
                    select.value = 'new';
                    sync();
                }
            }
            if (functionSelect) {
                functionSelect.addEventListener('change', filterPositions);
                select.addEventListener('change', function () {
                    var own = select.selectedOptions[0] && select.selectedOptions[0].getAttribute('data-function');
                    if (own) functionSelect.value = own;
                    filterPositions();
                });
                filterPositions();
            }
            input.addEventListener('input', function () {
                if (select.value !== 'new') {
                    select.value = 'new';
                    sync();
                }
            });
            sync();
        });
        root.querySelectorAll('[data-mapping-filter]').forEach(function (toggle) {
            if (toggle.dataset.filterInit) return;
            toggle.dataset.filterInit = '1';
            var table = document.querySelector(toggle.getAttribute('data-mapping-filter'));
            if (!table) return;
            toggle.addEventListener('change', function () {
                table.querySelectorAll('[data-mapping-row]').forEach(function (row) {
                    row.hidden = toggle.checked && !row.classList.contains('is-unmapped');
                });
            });
        });
        // «Показать места»: подсказка состояния колонки с несопоставленными значениями
        // раскрывает фильтр и прокручивает к таблице сопоставления.
        root.querySelectorAll('[data-show-unmapped]').forEach(function (link) {
            if (link.dataset.showInit) return;
            link.dataset.showInit = '1';
            link.addEventListener('click', function () {
                var toggle = document.querySelector('[data-mapping-filter]');
                if (toggle && !toggle.checked) {
                    toggle.checked = true;
                    toggle.dispatchEvent(new Event('change'));
                }
            });
        });
    }
    initMappingRows(document);

    /**
     * Таблица «Колонки базы ↔ ФиП»: день ФиП, выбранный в одной строке, пропадает
     * из выбора других строк (кроме колонок той же даты); [data-hide-fap-chosen]
     * скрывает строки, где ФиП уже выбран.
     */
    function initFapColumns(root) {
        root.querySelectorAll('[data-hide-fap-chosen]').forEach(function (toggle) {
            if (toggle.dataset.fapInit) return;
            toggle.dataset.fapInit = '1';
            var table = document.querySelector(toggle.getAttribute('data-hide-fap-chosen'));
            if (!table) return;
            var selects = table.querySelectorAll('[data-fap-select]');
            function chosen(row) {
                var select = row.querySelector('[data-fap-select]');
                return select ? !!select.value : row.hasAttribute('data-fap-chosen');
            }
            function refresh() {
                var used = {};
                selects.forEach(function (select) { if (select.value) used[select.value] = select; });
                selects.forEach(function (select) {
                    var day = select.closest('[data-fap-row]').getAttribute('data-column-day');
                    Array.prototype.forEach.call(select.options, function (option) {
                        var owner = used[option.value];
                        var sameDay = option.value.split('|')[1] === day;
                        option.hidden = !!(owner && owner !== select && !sameDay);
                    });
                });
                table.querySelectorAll('[data-fap-row]').forEach(function (row) {
                    row.hidden = toggle.checked && chosen(row);
                });
            }
            selects.forEach(function (select) { select.addEventListener('change', refresh); });
            toggle.addEventListener('change', refresh);
            refresh();
        });
    }
    initFapColumns(document);
