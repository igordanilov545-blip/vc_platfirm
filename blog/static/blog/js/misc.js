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
            name.classList.remove('attendance-pending', 'attendance-attended', 'attendance-absent_excused', 'attendance-absent_unexcused');
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

    // Выдача в таблице: жетон общий во всех строках человека, обед — на смену.
    function initPositionHandouts(root) {
        (root || document).querySelectorAll('[data-handout-kind]').forEach(function (checkbox) {
            if (checkbox.dataset.handoutInit) return;
            checkbox.dataset.handoutInit = '1';
            checkbox.addEventListener('change', async function () {
                var kind = checkbox.dataset.handoutKind;
                var checked = checkbox.checked;
                var peers = Array.from(document.querySelectorAll('[data-handout-kind]')).filter(function (other) {
                    return other.dataset.handoutKind === kind && other.dataset.handoutUser === checkbox.dataset.handoutUser
                        && (kind === 'badge' ? other.dataset.handoutGroup === checkbox.dataset.handoutGroup : other.dataset.handoutShift === checkbox.dataset.handoutShift);
                });
                var disabled = peers.map(function (other) { return other.disabled; });
                peers.forEach(function (other) { other.disabled = true; other.checked = checked; });
                var error = checkbox.parentElement.querySelector('[data-handout-error]');
                if (error) error.remove();
                try {
                    var response = await fetch(checkbox.dataset.handoutUrl, {
                        method: 'POST', credentials: 'same-origin',
                        headers: {'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
                        body: new URLSearchParams({kind: kind, checked: JSON.stringify(checked)})
                    });
                    if (!response.ok) {
                        var message = 'Не удалось сохранить выдачу.';
                        if ((response.headers.get('content-type') || '').includes('application/json')) message = (await response.json()).error || message;
                        throw new Error(message);
                    }
                    var saved = await response.json();
                    if (typeof saved.checked !== 'boolean') throw new Error('Войдите в систему заново.');
                    peers.forEach(function (other) {
                        other.checked = saved.checked;
                        other.closest('td').dataset.sortValue = saved.checked ? '1' : '0';
                    });
                } catch (failure) {
                    peers.forEach(function (other) { other.checked = !checked; });
                    error = document.createElement('span');
                    error.dataset.handoutError = '';
                    error.className = 'field-error';
                    error.setAttribute('role', 'alert');
                    error.textContent = failure.message;
                    checkbox.parentElement.appendChild(error);
                } finally {
                    peers.forEach(function (other, index) { other.disabled = disabled[index]; });
                }
            });
        });
    }
    initPositionHandouts(document);

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
    // «Скопировать опыт»: кнопка «Выбрать топ» открывает привычную модалку выбора
    // «n из m» (ensureSelectModal из selects.js) со списком мероприятий центра; лимит —
    // 3 (COPY_MAX). Выбранные меро показываются чипами (снять — крестиком), их роли
    // группируются в итоговом тексте («Тим-лидер: …. Волонтёр: ….», каждое меро названо
    // один раз). Текст кладётся в data-copy-text кнопки копирования (её жмут обычным
    // обработчиком выше). Данные о меро+ролях — из <script data-experience-events>
    // (см. _experience_block.html).
    // ======================================================================
    var COPY_MAX = 3;

    function buildExperienceCopyText(cfg, selectedIds) {
        // cfg: {total, url, events:[{id,title,role}]}; selectedIds — массив id (в порядке отметки).
        var word = declMero(cfg.total);
        var text = 'Я участвовал(а) в ' + cfg.total + ' ' + word;
        var byId = {};
        cfg.events.forEach(function (e) { byId[e.id] = e; });
        text += '.';
        var chosen = selectedIds.map(function (id) { return byId[id]; }).filter(Boolean);
        // Группировка по роли с подписью-заголовком: «Тим-лидер: k1, k2. Волонтёр: k3.»
        // Каждое меро названо один раз; пустые группы не выводим.
        var leads = chosen.filter(function (e) { return e.role === 'team_lead'; }).map(function (e) { return e.title; });
        var vols = chosen.filter(function (e) { return e.role !== 'team_lead'; }).map(function (e) { return e.title; });
        if (leads.length) text += ' Тим-лидер: ' + leads.join(', ') + '.';
        if (vols.length) text += ' Волонтёр: ' + vols.join(', ') + '.';
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
            var copyBtn = box.querySelector('[data-copy-text]');
            var openBtn = box.querySelector('[data-experience-pick-open]');
            var chosenRow = box.querySelector('[data-experience-chosen]');
            if (!dataEl || !copyBtn || !openBtn || !chosenRow) return;
            var cfg;
            try { cfg = JSON.parse(dataEl.textContent); } catch (e) { return; }
            if (typeof ensureSelectModal !== 'function') return;

            var byId = {};
            cfg.events.forEach(function (e) { byId[e.id] = e; });
            var selected = [];  // id в порядке выбора (порядок в тексте совпадает с выбором)

            function refresh() {
                copyBtn.setAttribute('data-copy-text', buildExperienceCopyText(cfg, selected));
                // Выбранные меро — чипами с крестиком (общий рендер из selects.js).
                var items = selected.map(function (id) {
                    return { value: String(id), label: byId[id] ? byId[id].title : ('#' + id) };
                });
                // Чипы выбранного (с крестиком); пусто → ничего не рисуем (пустая строка),
                // чтобы блок не выделялся, пока топ не выбран — только тихая ссылка-триггер.
                renderSelectedChips(chosenRow, items, '', function (value) {
                    var pos = selected.indexOf(parseInt(value, 10));
                    if (pos !== -1) selected.splice(pos, 1);
                    refresh();
                });
                // Достигнут лимит — ссылку выбора гасим (открывать пустую модалку незачем).
                openBtn.disabled = selected.length >= COPY_MAX;
                openBtn.textContent = selected.length
                    ? 'изменить топ (' + selected.length + '/' + COPY_MAX + ')'
                    : 'выбрать топ мероприятий';
            }

            // Кандидаты для модалки: ещё не выбранные меро, отфильтрованные по подстроке.
            // При достигнутом лимите список пуст (добавлять больше нельзя).
            function candidates(query) {
                if (selected.length >= COPY_MAX) return [];
                return cfg.events
                    .filter(function (e) { return selected.indexOf(e.id) === -1; })
                    .filter(function (e) { return !query || e.title.toLowerCase().indexOf(query) !== -1; })
                    .map(function (e) {
                        // Роль-подсказку показываем прямо в подписи строки модалки.
                        var suffix = e.role === 'team_lead' ? ' — тим-лидер' : '';
                        return { value: String(e.id), label: e.title + suffix };
                    });
            }

            openBtn.addEventListener('click', function () {
                ensureSelectModal().open({
                    single: false,
                    candidates: candidates,
                    onPick: function (it) {
                        var id = parseInt(it.value, 10);
                        if (selected.indexOf(id) === -1 && selected.length < COPY_MAX) selected.push(id);
                        refresh();
                    },
                    // Полоса «Выбрано» внутри окна: те же меро, что и чипы снаружи.
                    selectedItems: function () {
                        return selected.map(function (id) {
                            return { value: String(id), label: byId[id] ? byId[id].title : ('#' + id) };
                        });
                    },
                    onUnpick: function (value) {
                        var pos = selected.indexOf(parseInt(value, 10));
                        if (pos !== -1) selected.splice(pos, 1);
                        refresh();
                    },
                });
            });

            refresh();
        });
    }
    initExperienceCopy(document);

    // ======================================================================
    // Попап достижения: клик по карточке [data-achievement] показывает окошко с
    // условием получения (описание), для series — текущую ступень и «до следующей»,
    // процент/число держателей и дату получения (незаметно, серым, в углу) —
    // achievements.md §Дополнительно. Одно окно на страницу (data-achievement-popup),
    // наполняется из data-* нажатой карточки. Открывается даже у уже полученного
    // достижения (пользователь хочет перечитать условие).
    // ======================================================================
    function initAchievementPopup(root) {
        var popup = root.querySelector('[data-achievement-popup]')
            || document.querySelector('[data-achievement-popup]');
        if (!popup) return;
        if (popup.dataset.achPopupInit) return;
        popup.dataset.achPopupInit = '1';

        var iconEl = popup.querySelector('[data-ach-popup-icon]');
        var titleEl = popup.querySelector('[data-ach-popup-title]');
        var tierEl = popup.querySelector('[data-ach-popup-tier]');
        var descEl = popup.querySelector('[data-ach-popup-desc]');
        var metaEl = popup.querySelector('[data-ach-popup-meta]');
        var dateEl = popup.querySelector('[data-ach-popup-date]');

        function open(card) {
            iconEl.textContent = card.getAttribute('data-ach-icon') || '🏅';
            titleEl.textContent = card.getAttribute('data-ach-title') || '';
            descEl.textContent = card.getAttribute('data-ach-desc') || '';

            // Уровень (tier) — подпись под названием, если задан.
            if (tierEl) {
                var tier = card.getAttribute('data-ach-tier');
                if (tier) { tierEl.textContent = tier; tierEl.style.display = ''; }
                else { tierEl.textContent = ''; tierEl.style.display = 'none'; }
            }

            var meta = [];
            var earned = card.getAttribute('data-ach-earned') === '1';
            var percent = card.getAttribute('data-ach-percent');
            var holders = card.getAttribute('data-ach-holders');
            if (percent !== null && percent !== '') meta.push('Есть у ' + percent + '% волонтёров');
            else if (holders !== null && holders !== '') meta.push('Получили: ' + holders);
            metaEl.textContent = meta.join(' · ');
            metaEl.style.display = meta.length ? '' : 'none';

            var date = card.getAttribute('data-ach-date');
            if (earned && date) { dateEl.textContent = 'Получено ' + date; dateEl.style.display = ''; }
            else { dateEl.textContent = ''; dateEl.style.display = 'none'; }

            popup.hidden = false;
            document.body.style.overflow = 'hidden';
        }
        function close() {
            popup.hidden = true;
            document.body.style.overflow = '';
        }

        root.addEventListener('click', function (e) {
            var card = e.target.closest('[data-achievement]');
            if (card) { open(card); return; }
        });
        popup.addEventListener('click', function (e) {
            if (e.target === popup || e.target.closest('[data-ach-close]')) close();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !popup.hidden) close();
        });
    }
    initAchievementPopup(document);
