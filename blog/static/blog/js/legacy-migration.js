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

    /**
     * Форма позиции: выбранная функция задаёт подсказки названия (datalist
     * position-pool-<id>, позиции этой функции из пула); «＋ Новая функция»
     * показывает поле её названия.
     */
    function initFunctionPoolSelect(root) {
        root.querySelectorAll('[data-function-pool-select]').forEach(function (select) {
            if (select.dataset.poolInit) return;
            select.dataset.poolInit = '1';
            var form = select.closest('form') || document;
            var title = form.querySelector('#' + select.getAttribute('data-title-input'));
            var newField = form.querySelector('[data-new-function-field]');
            var lastName = select.value && select.value !== 'new' ? select.options[select.selectedIndex].text : '';
            var categories = form.querySelector('#' + select.getAttribute('data-categories-select'));
            // Категории по умолчанию функции: при СМЕНЕ функции снимаем прежние
            // автоматические и ставим новые; выбранные руками остаются.
            var autoIds = [];
            function applyDefaults() {
                if (!categories) return;
                var opt = select.options[select.selectedIndex];
                var ids = ((opt && opt.getAttribute('data-default-categories')) || '').split(',').filter(Boolean);
                Array.prototype.forEach.call(categories.options, function (o) {
                    if (autoIds.indexOf(o.value) !== -1 && ids.indexOf(o.value) === -1) o.selected = false;
                    if (ids.indexOf(o.value) !== -1) o.selected = true;
                });
                autoIds = ids;
                categories.dispatchEvent(new Event('chips:refresh'));
            }
            select.addEventListener('change', applyDefaults);
            function sync() {
                var name = select.value && select.value !== 'new' ? select.options[select.selectedIndex].text : '';
                // Название позиции по умолчанию — название функции (пока его не меняли руками).
                if (title && name && (!title.value || title.value === lastName)) title.value = name;
                lastName = name;
                if (title) {
                    var own = select.value && form.querySelector('#position-pool-' + select.value);
                    if (own) title.setAttribute('list', own.id); else title.removeAttribute('list');
                }
                if (newField) newField.hidden = select.value !== 'new';
                // Подсказки ролей в плане смены — роли выбранной функции.
                var pool = select.value && form.querySelector('#position-pool-' + select.value);
                form.querySelectorAll('[data-role-plan]').forEach(function (box) {
                    if (box.rolePlan) box.rolePlan.setPool(pool ? pool.id : 'role-pool-default');
                    else box.setAttribute('data-role-pool', pool ? pool.id : 'role-pool-default');
                });
            }
            select.addEventListener('change', sync);
            sync();
        });
    }
    initFunctionPoolSelect(document);


    /** Роль человека в таблице набора смены: select из ролей плана, сохраняется сразу. */
    function initShiftRoles(root) {
        root.querySelectorAll('[data-role-form]').forEach(function (form) {
            if (form.dataset.roleInit) return;
            form.dataset.roleInit = '1';
            var input = form.querySelector('[name=role]');
            form.addEventListener('submit', function (e) { e.preventDefault(); });
            input.addEventListener('change', function () {
                input.classList.remove('saved', 'failed');
                fetch(form.action, {method: 'POST', body: new FormData(form), headers: {'X-Requested-With': 'XMLHttpRequest'}})
                    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
                    .then(function () { input.classList.add('saved'); })
                    .catch(function () { input.classList.add('failed'); input.title = 'Не сохранилось — обновите страницу'; });
            });
        });
    }
    initShiftRoles(document);

    /**
     * План ролей смены [data-role-plan]: строки «роль — сколько», итог против «нужно».
     * Пустой план = 1 тим-лидер, остальные волонтёры (та же нормализация, что
     * shift_roles.normalize_role_plan на сервере). box.rolePlan — read/reset/setPool
     * для чипов смен формы функции (forms.js initShiftChips).
     */
    var TEAM_LEAD_ROLE = 'Тим-лидер', VOLUNTEER_ROLE = 'Волонтёр';
    function roleKey(name) { return String(name || '').trim().toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' '); }
    function rolePlanNormalize(plan, needed) {
        var out = [], seen = {};
        (plan || []).forEach(function (item) {
            var role = String(item[0] || '').trim().replace(/\s+/g, ' '), n = parseInt(item[1], 10) || 0;
            if (!role || n <= 0) return;
            var key = roleKey(role);
            if (key in seen) out[seen[key]][1] += n; else { seen[key] = out.length; out.push([role, n]); }
        });
        needed = parseInt(needed, 10) || 0;
        if (!out.length && needed) out.push([TEAM_LEAD_ROLE, 1]);
        var rest = needed - out.reduce(function (a, r) { return a + r[1]; }, 0);
        if (rest > 0) {
            var vol = out.filter(function (r) { return roleKey(r[0]) === roleKey(VOLUNTEER_ROLE); })[0];
            if (vol) vol[1] += rest; else out.push([VOLUNTEER_ROLE, rest]);
        }
        return out;
    }
    function rolePlanLabel(plan) { return plan.map(function (r) { return r[0] + ' ' + r[1]; }).join(', '); }
    window.rolePlanNormalize = rolePlanNormalize;
    window.rolePlanLabel = rolePlanLabel;

    function initRolePlans(root) {
        root.querySelectorAll('[data-role-plan]').forEach(function (box) {
            if (box.rolePlan) return;
            var form = box.closest('form') || document;
            var rows = box.querySelector('[data-role-plan-rows]');
            var sumEl = box.querySelector('[data-role-plan-sum]');
            var json = box.querySelector('[data-role-plan-json]');
            var neededSel = box.getAttribute('data-role-plan-needed');
            function neededInput() { return neededSel ? form.querySelector(neededSel) : null; }
            function addRow(role, count) {
                var row = document.createElement('div');
                row.className = 'role-plan-row';
                row.innerHTML = '<input type="text" class="role-plan-name" placeholder="Роль" autocomplete="off">' +
                    '<input type="number" class="role-plan-count" min="0" placeholder="0">' +
                    '<button type="button" class="cat-chip-x" aria-label="Убрать роль">×</button>';
                var name = row.querySelector('.role-plan-name');
                name.setAttribute('list', box.getAttribute('data-role-pool'));
                name.value = role || '';
                row.querySelector('.role-plan-count').value = count || '';
                row.querySelector('button').addEventListener('click', function () { row.remove(); update(); });
                rows.appendChild(row);
                return row;
            }
            function read() {
                var plan = [];
                rows.querySelectorAll('.role-plan-row').forEach(function (row) {
                    var role = row.querySelector('.role-plan-name').value.trim();
                    var n = parseInt(row.querySelector('.role-plan-count').value, 10) || 0;
                    if (role && n > 0) plan.push([role, n]);
                });
                return plan;
            }
            function update() {
                var plan = read();
                var input = neededInput();
                var need = input ? (parseInt(input.value, 10) || 0) : 0;
                var sum = plan.reduce(function (a, r) { return a + r[1]; }, 0);
                var text, warn = false;
                if (!plan.length) text = need ? 'Будет: ' + rolePlanLabel(rolePlanNormalize([], need)) : '';
                else if (sum < need) text = 'Расписано ' + sum + ' из ' + need + ' — остальные (' + (need - sum) + ') станут волонтёрами';
                else if (sum > need) { text = '⚠ Расписано ' + sum + ' — больше, чем нужно на смену (' + need + ')'; warn = true; }
                else text = 'Расписано ' + sum + ' из ' + need + ' ✓';
                sumEl.textContent = text;
                sumEl.classList.toggle('mismatch', warn);
                if (json) json.value = JSON.stringify(plan);
            }
            box.querySelector('[data-role-plan-add]').addEventListener('click', function () {
                if (!rows.children.length) addRow(TEAM_LEAD_ROLE, 1);
                addRow('', '').querySelector('input').focus();
                update();
            });
            box.addEventListener('input', update);
            var input = neededInput();
            if (input) input.addEventListener('input', update);
            if (json && json.value) {
                try { JSON.parse(json.value).forEach(function (r) { addRow(r[0], r[1]); }); } catch (e) { /* пустой план */ }
            }
            box.rolePlan = {
                read: read,
                reset: function () { rows.innerHTML = ''; update(); },
                setPool: function (id) {
                    box.setAttribute('data-role-pool', id);
                    rows.querySelectorAll('.role-plan-name').forEach(function (n) { n.setAttribute('list', id); });
                },
            };
            update();
        });
    }
    initRolePlans(document);
