/*
 * static/blog/js/misc.js
 * Прочее поведение: подтверждения, формы ролей, quick-add справочников
 * (REF_CONFIG, URL из window.VC_URLS), явка/часы, резерв, копирование/шеринг.
 *
 * Часть распила инлайнового JS base.html (см. static/blog/js/README.md).
 * Грузится обычным <script> (не модуль) — все init-функции и хелперы остаются в
 * глобальном scope, как раньше; initPageContent зовёт их через window[fn].
 */
    function bindConfirmForms(root) {
        root.querySelectorAll('form[data-confirm]').forEach(function (form) {
            if (form.dataset.confirmInit) return;
            form.dataset.confirmInit = '1';
            form.addEventListener('submit', function (event) {
                var question = form.getAttribute('data-confirm');
                if (question && !confirm(question)) {
                    event.preventDefault();
                }
            });
        });
    }
    bindConfirmForms(document);

    // ======================================================================
    // Подтверждение перед назначением/снятием роли (настройки): показывает
    // список выбранных ФИО и количество, требует явного OK. Идемпотентно
    // (data-roleFormInit) — панель ролей в настройках подгружается AJAX'ом.
    // ======================================================================
    function bindRoleForms(root) {
        root.querySelectorAll('[data-role-form]').forEach(function (form) {
            if (form.dataset.roleFormInit) return;
            form.dataset.roleFormInit = '1';
            form.addEventListener('submit', function (event) {
                // Источник выбранных пользователей — remote-виджет выбора
                // (widget._pickerSelected, Map value->label), а не серверный <select multiple>:
                // страница настроек больше не рендерит все тысячи пользователей в HTML.
                var picker = form.querySelector('[data-chip-select][data-select-remote]');
                var selected = picker && picker._pickerSelected ? picker._pickerSelected : new Map();
                if (!selected.size) {
                    event.preventDefault();
                    alert('Выберите хотя бы одного пользователя.');
                    return;
                }
                var names = Array.from(selected.values()).join(', ');
                var verb = form.getAttribute('data-confirm-verb') || 'применить действие к';
                var question = 'Вы уверены, что хотите ' + verb + ': ' + names + ' (' + selected.size + ')?';
                if (!confirm(question)) {
                    event.preventDefault();
                }
            });
        });
    }
    bindRoleForms(document);

    // ======================================================================
    // Кнопка "＋" рядом с select (организатор/локация/организация) открывает
    // вложенную модалку создания новой записи. После создания — запись
    // добавляется в select и выбирается. Данные формы меро не теряются.
    // ======================================================================
    var REF_CONFIG = {
        location: {
            title: 'Новая локация',
            createUrl: window.VC_URLS.quickCreate.location,
            fields: [
                { name: 'name', label: 'Название локации', type: 'text', required: true },
                { name: 'map_link', label: 'Ссылка на карту', type: 'text', required: false },
            ],
        },
        organization: {
            title: 'Новая организация',
            createUrl: window.VC_URLS.quickCreate.organization,
            fields: [
                { name: 'name', label: 'Название организации', type: 'text', required: true },
                { name: 'description', label: 'Описание', type: 'textarea', required: false },
            ],
        },
        organizer: {
            title: 'Новый организатор',
            createUrl: window.VC_URLS.quickCreate.organizer,
            fields: [
                { name: 'first_name', label: 'Имя', type: 'text', required: true },
                { name: 'last_name', label: 'Фамилия', type: 'text', required: false },
                { name: 'phone', label: 'Телефон', type: 'text', required: false },
                { name: 'telegram_username', label: 'Telegram', type: 'text', required: false },
            ],
        },
        category: {
            title: 'Новая категория',
            createUrl: window.VC_URLS.quickCreate.category,
            fields: [
                { name: 'name', label: 'Название категории', type: 'text', required: true },
            ],
        },
        perk: {
            title: 'Новая плюшка',
            createUrl: window.VC_URLS.quickCreate.perk,
            fields: [
                { name: 'name', label: 'Название плюшки', type: 'text', required: true },
            ],
        },
        requirement: {
            title: 'Новое требование',
            createUrl: window.VC_URLS.quickCreate.requirement,
            fields: [
                { name: 'title', label: 'Название требования', type: 'text', required: true },
                { name: 'description', label: 'Описание', type: 'textarea', required: false },
            ],
        },
        volunteer: {
            title: 'Новый волонтёр',
            createUrl: window.VC_URLS.quickCreate.volunteer,
            // Заполняется как профиль (пришёл «извне», как Excel-импорт): фамилия/имя
            // обязательны, связь — Telegram ИЛИ телефон (проверяется на сервере). В заявке
            // такого волонтёра источник = «Добавлен менеджером» (manual:* telegram_id).
            fields: [
                { name: 'last_name', label: 'Фамилия', type: 'text', required: true },
                { name: 'first_name', label: 'Имя', type: 'text', required: true },
                { name: 'phone', label: 'Телефон', type: 'text', required: false },
                { name: 'telegram_username', label: 'Telegram (@username)', type: 'text', required: false },
            ],
        },
    };

    function getCsrfToken() {
        // Токен берём из формы в основной модалке или из первой формы на странице.
        var input = (modalBody && modalBody.querySelector('[name=csrfmiddlewaretoken]'))
            || document.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    // ======================================================================
    // Явка в объединённой таблице набора (страница мероприятия) — тремя кнопками
    // «Был / Не был / Уважит.», в едином стиле с кнопками обработки заявок. Отдельного
    // поля-статуса нет: активная кнопка подсвечена, а имя волонтёра дополнительно
    // окрашивается по явке (attendance-* классы).
    //   attended         — «Был» (имя зелёное)
    //   absent_unexcused — «Не был» (имя красное)
    //   absent_excused   — «Уважит.» (имя приглушённое)
    // ======================================================================
    function applyAttendanceUI(row, status, hours) {
        // Подсветка активной кнопки в группе.
        var group = row.querySelector('[data-attendance-group]');
        if (group) {
            group.querySelectorAll('[data-attendance-set]').forEach(function (b) {
                b.classList.toggle('active', b.getAttribute('data-attendance-set') === status);
            });
        }
        // Цвет имени.
        var name = row.querySelector('[data-name-for]');
        if (name) {
            name.classList.remove('attendance-attended', 'attendance-absent_excused', 'attendance-absent_unexcused');
            name.classList.add('attendance-' + status);
        }
        // Часы: редактируются только у пришедших.
        var hoursInput = row.querySelector('[data-attendance-hours]');
        if (hoursInput) {
            if (hours !== undefined && hours !== null) hoursInput.value = hours;
            hoursInput.disabled = (status !== 'attended');
        }
        var hoursCell = row.querySelector('[data-hours-cell]');
        if (hoursCell && hours !== undefined && hours !== null) hoursCell.setAttribute('data-sort-value', hours);
        var attendanceCell = row.querySelector('td[data-label="Явка"]');
        if (attendanceCell) attendanceCell.setAttribute('data-sort-value', status);
    }

    function sendParticipationStatus(row, id, status) {
        var buttons = row.querySelectorAll('[data-attendance-set]');
        buttons.forEach(function (b) { b.disabled = true; });
        fetch('/participations/' + id + '/set-status/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: 'status=' + encodeURIComponent(status) + '&csrfmiddlewaretoken=' + encodeURIComponent(getCsrfToken()),
        })
        .then(function (r) { return r.json(); })
        .then(function (data) { applyAttendanceUI(row, data.status, data.hours); })
        .catch(function () { alert('Не удалось сохранить явку. Попробуйте ещё раз.'); })
        .finally(function () { buttons.forEach(function (b) { b.disabled = false; }); });
    }

    document.querySelectorAll('[data-attendance-set]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var id = btn.getAttribute('data-participation-id');
            var row = btn.closest('[data-participation-row]');
            sendParticipationStatus(row, id, btn.getAttribute('data-attendance-set'));
        });
    });

    // ======================================================================
    // «Показать/скрыть резерв» на смене: строки резерва (data-reserve="<shiftId>")
    // скрыты по умолчанию; кнопка [data-reserve-toggle="<shiftId>"] раскрывает их.
    // Состояние «раскрыто» ЗАПОМИНАЕТСЯ (sessionStorage) и восстанавливается после
    // перезагрузки — иначе при выводе кого-то из резерва (approve/reject → reload)
    // резерв снова схлопывался бы, хотя пользователь его открывал.
    // ======================================================================
    var RESERVE_KEY = 'reserveOpen:' + location.pathname;
    function reserveOpenSet() {
        try { return new Set(JSON.parse(sessionStorage.getItem(RESERVE_KEY) || '[]')); }
        catch (e) { return new Set(); }
    }
    function reserveSave(set) {
        try { sessionStorage.setItem(RESERVE_KEY, JSON.stringify(Array.from(set))); } catch (e) {}
    }
    function setReserveState(btn, shiftId, show, store) {
        var rows = document.querySelectorAll('tr[data-reserve="' + shiftId + '"]');
        rows.forEach(function (r) { r.hidden = !show; });
        btn.setAttribute('aria-expanded', show ? 'true' : 'false');
        btn.textContent = (show ? 'Скрыть резерв (' : 'Показать резерв (') + rows.length + ')';
        if (store) {
            var set = reserveOpenSet();
            if (show) set.add(shiftId); else set.delete(shiftId);
            reserveSave(set);
        }
    }
    (function initReserveToggles() {
        var open = reserveOpenSet();
        document.querySelectorAll('[data-reserve-toggle]').forEach(function (btn) {
            var shiftId = btn.getAttribute('data-reserve-toggle');
            if (open.has(shiftId)) setReserveState(btn, shiftId, true, false);
            btn.addEventListener('click', function () {
                var show = btn.getAttribute('aria-expanded') !== 'true';
                setReserveState(btn, shiftId, show, true);
            });
        });
    })();

    // ======================================================================
    // Блокировка кнопки формы после первого клика (защита от двойной обработки):
    // форма с data-disable-on-submit при отправке дизейблит свою submit-кнопку.
    // ======================================================================
    document.querySelectorAll('form[data-disable-on-submit]').forEach(function (form) {
        form.addEventListener('submit', function () {
            var btn = form.querySelector('button[type=submit]');
            if (btn) { btn.disabled = true; btn.dataset.submitting = '1'; }
        });
    });

    // Ручная правка часов участия тим-лидером прямо в таблице явки — сохраняется на blur
    // и по Enter (чтобы не слать запрос на каждый набранный символ).
    function sendParticipationHours(input) {
        var id = input.getAttribute('data-participation-id');
        var row = input.closest('[data-participation-row]');
        input.disabled = true;
        fetch('/participations/' + id + '/set-hours/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: 'hours=' + encodeURIComponent(input.value) + '&csrfmiddlewaretoken=' + encodeURIComponent(getCsrfToken()),
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.error) { alert(data.error); return; }
            input.value = data.hours;
            var cell = input.closest('[data-hours-cell]');
            if (cell) cell.setAttribute('data-sort-value', data.hours);
        })
        .catch(function () { alert('Не удалось сохранить часы. Попробуйте ещё раз.'); })
        .finally(function () { input.disabled = false; });
    }

    function initAttendanceHoursInputs(root) {
        (root || document).querySelectorAll('[data-attendance-hours]').forEach(function (input) {
            if (input.dataset.hoursInit) return;
            input.dataset.hoursInit = '1';
            var lastSaved = input.value;
            input.addEventListener('change', function () {
                if (input.value !== lastSaved) { lastSaved = input.value; sendParticipationHours(input); }
            });
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
            });
        });
    }
    initAttendanceHoursInputs(document);

    var quickAddBackdrop = document.getElementById('quick-add-backdrop');
    var quickAddBody = document.getElementById('quick-add-body');
    var quickAddTitle = document.getElementById('quick-add-title');
    var quickAddClose = document.getElementById('quick-add-close');

    function openQuickAddModal(kind, onCreated) {
        var config = REF_CONFIG[kind];
        if (!config || !onCreated) return;
        quickAddTitle.textContent = config.title;

        var html = '<div class="quick-add-error" data-quick-error hidden></div>';
        config.fields.forEach(function (f) {
            var widget = f.type === 'textarea'
                ? '<textarea rows="2" name="' + f.name + '"' + (f.required ? ' required' : '') + '></textarea>'
                : '<input type="text" name="' + f.name + '"' + (f.required ? ' required' : '') + '>';
            html += '<div class="field"><label>' + f.label + (f.required ? ' *' : '') + '</label>' + widget + '</div>';
        });
        html += '<div class="event-form-actions">' +
            '<button type="button" class="btn secondary" data-quick-cancel>Отмена</button>' +
            '<button type="button" class="btn" data-quick-submit>Создать</button></div>';
        quickAddBody.innerHTML = html;
        quickAddBackdrop.hidden = false;

        var firstInput = quickAddBody.querySelector('input, textarea');
        if (firstInput) firstInput.focus();

        var errorBox = quickAddBody.querySelector('[data-quick-error]');
        quickAddBody.querySelector('[data-quick-cancel]').addEventListener('click', closeQuickAddModal);
        quickAddBody.querySelector('[data-quick-submit]').addEventListener('click', function () {
            errorBox.hidden = true;
            var payload = new URLSearchParams();
            payload.append('csrfmiddlewaretoken', getCsrfToken());
            config.fields.forEach(function (f) {
                var el = quickAddBody.querySelector('[name="' + f.name + '"]');
                payload.append(f.name, el.value);
            });

            fetch(config.createUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: payload.toString(),
            })
            .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
            .then(function (result) {
                if (!result.ok) {
                    var msgs = [];
                    Object.keys(result.data.errors || {}).forEach(function (k) {
                        (result.data.errors[k] || []).forEach(function (e) { msgs.push(e.message || e); });
                    });
                    errorBox.textContent = msgs.join(' ') || 'Не удалось создать запись.';
                    errorBox.hidden = false;
                    return;
                }
                onCreated(result.data);
                closeQuickAddModal();
            });
        });
    }

    function closeQuickAddModal() {
        quickAddBackdrop.hidden = true;
        quickAddBody.innerHTML = '';
    }

    // Делегирование клика по "＋" — работает и на странице, и в динамически вставленной модалке.
    // Два варианта таргета: обычный <select> (data-add-ref + data-target) — старое
    // поведение; либо пул пикера волонтёров (data-add-ref-picker) — новая запись сразу
    // попадает в widgetState.selected того же виджета, форма не сабмитится.
    document.addEventListener('click', function (event) {
        var selectBtn = event.target.closest('[data-add-ref]');
        if (selectBtn) {
            event.preventDefault();
            var kind = selectBtn.getAttribute('data-add-ref');
            var targetSelect = document.getElementById(selectBtn.getAttribute('data-target'));
            if (!targetSelect) return;
            openQuickAddModal(kind, function (data) {
                var option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.label;
                option.selected = true;
                targetSelect.appendChild(option);
                // Если это виджет категорий с чипами — перерисовать его.
                targetSelect.dispatchEvent(new Event('chips:refresh'));
            });
            return;
        }
        var pickerBtn = event.target.closest('[data-add-ref-picker]');
        if (pickerBtn) {
            event.preventDefault();
            var pickerKind = pickerBtn.getAttribute('data-add-ref-picker');
            var pickerWidget = pickerBtn.closest('[data-chip-select][data-select-remote]');
            if (!pickerWidget || !pickerWidget._pickerSelected || !pickerWidget._pickerRenderSelected) return;
            openQuickAddModal(pickerKind, function (data) {
                // Ключи выбранного в remote-виджете — строковые id (см. initRemoteSelect).
                pickerWidget._pickerSelected.set(String(data.id), data.label);
                pickerWidget._pickerAddUser({ id: data.id, label: data.label, is_team_lead: false, is_manager: false });
                pickerWidget._pickerRenderSelected();
            });
        }
    });

    quickAddClose.addEventListener('click', closeQuickAddModal);
    quickAddBackdrop.addEventListener('click', function (event) {
        if (event.target === quickAddBackdrop) closeQuickAddModal();
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !quickAddBackdrop.hidden) closeQuickAddModal();
    });

    // ======================================================================
    // Копирование в буфер: кнопка «Поделиться» ([data-share-url]) копирует ссылку,
    // кнопка «Скопировать опыт» ([data-copy-text]) — заранее собранный текст со
    // ссылкой. Показывает короткое подтверждение прямо на кнопке.
    // ======================================================================
    function copyToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        // Фолбэк для не-HTTPS/старых браузеров.
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(ta);
        return Promise.resolve();
    }

    function flashCopied(btn) {
        var original = btn.textContent;
        btn.textContent = '✅ Скопировано';
        btn.disabled = true;
        setTimeout(function () { btn.textContent = original; btn.disabled = false; }, 1600);
    }

    document.addEventListener('click', function (event) {
        var btn = event.target.closest('[data-share-url], [data-copy-text]');
        if (!btn) return;
        event.preventDefault();
        var text = btn.getAttribute('data-share-url') || btn.getAttribute('data-copy-text') || '';
        copyToClipboard(text).then(function () { flashCopied(btn); });
    });

    // ======================================================================
    // «Скопировать опыт» с выбором топ-0..3 мероприятий и ролями.
    // Волонтёр отмечает до 3 мероприятий центра, которые хочет назвать явно; текст
    // собирается на клиенте и кладётся в data-copy-text кнопки копирования (её жмут
    // обычным обработчиком выше). Роли (тим-лидер/волонтёр) выделяются отдельно —
    // «был тим-лидером на …, волонтёром на …». Данные о меро+ролях приходят из
    // <script type="application/json" data-experience-events> (см. _experience_block.html).
    // ======================================================================
    var COPY_MAX = 3;

    function joinRu(names) {
        // «a», «a и b», «a, b и c» — человекочитаемое перечисление через запятую и «и».
        if (names.length === 0) return '';
        if (names.length === 1) return names[0];
        return names.slice(0, -1).join(', ') + ' и ' + names[names.length - 1];
    }

    function buildExperienceCopyText(cfg, selectedIds) {
        // cfg: {total, url, events:[{id,title,role}]}; selectedIds — массив id (в порядке отметки).
        var word = declMero(cfg.total);
        var text = 'Я участвовал(а) в ' + cfg.total + ' ' + word;
        var byId = {};
        cfg.events.forEach(function (e) { byId[e.id] = e; });
        var chosen = selectedIds.map(function (id) { return byId[id]; }).filter(Boolean);
        if (chosen.length) {
            text += ', включая ' + joinRu(chosen.map(function (e) { return e.title; }));
        }
        text += '.';
        // Роли — только по выбранным меро (иначе перечисление ролей по всем участиям
        // раздуло бы текст; выделяем именно то, что волонтёр решил подсветить).
        var leads = chosen.filter(function (e) { return e.role === 'team_lead'; }).map(function (e) { return e.title; });
        var vols = chosen.filter(function (e) { return e.role !== 'team_lead'; }).map(function (e) { return e.title; });
        var parts = [];
        if (leads.length) parts.push('тим-лидером на ' + joinRu(leads));
        if (vols.length) parts.push('волонтёром на ' + joinRu(vols));
        if (parts.length) text += ' Был(а) ' + parts.join(', ') + '.';
        if (cfg.url) text += ' Подробнее о всех мероприятиях: ' + cfg.url;
        return text;
    }

    function declMero(n) {
        // Склонение «мероприятие» по числу (1 мероприятии — предложный падеж «в N …»).
        var mod100 = n % 100, mod10 = n % 10;
        if (mod100 >= 11 && mod100 <= 14) return 'мероприятиях';
        if (mod10 === 1) return 'мероприятии';
        if (mod10 >= 2 && mod10 <= 4) return 'мероприятиях';
        return 'мероприятиях';
    }

    function initExperienceCopy(root) {
        root.querySelectorAll('[data-experience-copy]').forEach(function (box) {
            if (box.dataset.expCopyInit) return;
            box.dataset.expCopyInit = '1';
            var dataEl = box.querySelector('[data-experience-events]');
            var btn = box.querySelector('[data-copy-text]');
            if (!dataEl || !btn) return;
            var cfg;
            try { cfg = JSON.parse(dataEl.textContent); } catch (e) { return; }

            var selected = [];  // id в порядке отметки (чтобы порядок в тексте совпадал с кликами)
            var hint = box.querySelector('[data-experience-copy-hint]');

            function refresh() {
                btn.setAttribute('data-copy-text', buildExperienceCopyText(cfg, selected));
                box.querySelectorAll('[data-experience-pick]').forEach(function (chip) {
                    var id = parseInt(chip.getAttribute('data-experience-pick'), 10);
                    var on = selected.indexOf(id) !== -1;
                    chip.classList.toggle('active', on);
                    chip.setAttribute('aria-pressed', on ? 'true' : 'false');
                    // Достигнут лимит — неотмеченные чипы блокируем (нельзя выбрать >3).
                    chip.toggleAttribute('disabled', !on && selected.length >= COPY_MAX);
                });
                if (hint) hint.textContent = selected.length + ' из ' + COPY_MAX;
            }

            box.querySelectorAll('[data-experience-pick]').forEach(function (chip) {
                chip.addEventListener('click', function () {
                    var id = parseInt(chip.getAttribute('data-experience-pick'), 10);
                    var pos = selected.indexOf(id);
                    if (pos !== -1) {
                        selected.splice(pos, 1);
                    } else if (selected.length < COPY_MAX) {
                        selected.push(id);
                    }
                    refresh();
                });
            });
            refresh();
        });
    }
    initExperienceCopy(document);
