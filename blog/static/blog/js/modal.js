/*
 * static/blog/js/modal.js
 * AJAX-модалки/bottom-sheet: openModal/closeModal, мягкая навигация, loadModal,
 * bindModalForm, initPageContent (навешивает все init* по data-атрибутам).
 *
 * Часть распила инлайнового JS base.html (см. static/blog/js/README.md).
 * Грузится обычным <script> (не модуль) — все init-функции и хелперы остаются в
 * глобальном scope, как раньше; initPageContent зовёт их через window[fn].
 */
    function openModal(title) {
        modalTitle.textContent = title || '';
        modalBackdrop.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        modalBackdrop.hidden = true;
        modalBody.innerHTML = '';
        document.body.style.overflow = '';
        // Time-picker списки рендерятся напрямую в <body> (position:fixed, чтобы не
        // обрезаться overflow модалки) — их нужно убрать вручную, иначе останутся сиротами.
        document.querySelectorAll('.timepicker-list').forEach(function (el) { el.remove(); });
    }

    // ======================================================================
    // «Мягкая» навигация после успешной модалки — вместо window.location.href
    // (полная перезагрузка страницы, роняющая scroll и любое клиентское
    // состояние вроде развёрнутых таблиц). Модалка просто закрывается, а целевая
    // страница (success_redirect формы) подгружается AJAX'ом и подменяет только
    // #page-main — заголовок/сайдбар/подвал не перерисовываются, но данные внутри
    // страницы полностью свежие (это обычный GET той же вьюхи, не частичный патч).
    // Если целевой URL — текущая страница (та же модалка на месте) — скролл и хэш
    // сохраняются; если другая страница — history.pushState и скролл наверх.
    // ======================================================================
    function navigateSoft(url) {
        var target = new URL(url, window.location.origin);
        var samePage = target.pathname === window.location.pathname && target.search === window.location.search;

        // Без X-Requested-With намеренно: многие вьюхи по этому заголовку отдают
        // partial вместо полной страницы (is_ajax()) — soft-nav должен получить
        // ровно то же самое, что обычный переход по ссылке (полный HTML, из
        // которого мы вырезаем #page-main сами на клиенте).
        return fetch(target.pathname + target.search, { headers: { 'X-Soft-Nav': '1' } })
            .then(function (r) { return r.text().then(function (html) { return { ok: r.ok, html: html }; }); })
            .then(function (result) {
                if (!result.ok) { window.location.href = url; return; }
                var doc = new DOMParser().parseFromString(result.html, 'text/html');
                var newMain = doc.getElementById('page-main');
                var curMain = document.getElementById('page-main');
                if (!newMain || !curMain) { window.location.href = url; return; }
                curMain.innerHTML = newMain.innerHTML;
                var newTitle = doc.querySelector('title');
                if (newTitle) document.title = newTitle.textContent;
                if (!samePage) {
                    history.pushState(null, '', target.pathname + target.search + target.hash);
                }
                initPageContent(curMain);
                if (target.hash) {
                    var anchor = document.getElementById(target.hash.slice(1));
                    if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
                } else if (!samePage) {
                    window.scrollTo(0, 0);
                }
            })
            .catch(function () { window.location.href = url; });
    }

    // Переинициализация интерактивных компонентов внутри свежеподменённого блока
    // страницы (то же самое, что делается один раз при обычной загрузке страницы).
    function initPageContent(root) {
        ['initSortableTables', 'initHideableColumns', 'initTableFilter', 'initCharCounters',
         'bindConfirmForms', 'initCategoryChips', 'initShiftChips', 'initDatepickers',
         'initDateRangePair', 'initTimepickers', 'initInfiniteScroll',
         'bindRoleForms', 'initAttendanceHoursInputs', 'initLetterEditor',
         'initPasswordToggle', 'initToasts', 'initExperienceCopy',
         'initAchievementPopup', 'initQrScanner', 'initProfileCompletion'].forEach(function (fn) {
            if (typeof window[fn] === 'function') window[fn](root);
        });
    }

    function bindModalForm(formUrl) {
        var form = modalBody.querySelector('[data-modal-form], form');
        if (!form) return;
        form.addEventListener('submit', function (event) {
            event.preventDefault();
            var submitBtn = form.querySelector('button[type=submit]');
            if (submitBtn) submitBtn.disabled = true;

            fetch(form.getAttribute('action') || formUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                body: new FormData(form),
            })
            .then(function (r) {
                var contentType = r.headers.get('content-type') || '';
                if (contentType.indexOf('application/json') !== -1) {
                    return r.json().then(function (data) { return { redirect: data.redirect }; });
                }
                return r.text().then(function (html) { return { html: html }; });
            })
            .then(function (result) {
                if (result.redirect) {
                    closeModal();
                    navigateSoft(result.redirect);
                    return;
                }
                document.querySelectorAll('.timepicker-list').forEach(function (el) { el.remove(); });
                modalBody.innerHTML = result.html;
                initCharCounters(modalBody);
                initEventForm(modalBody);
                bindModalForm(formUrl);
                if (submitBtn) submitBtn.disabled = false;
            })
            .catch(function () {
                if (submitBtn) submitBtn.disabled = false;
            });
        });
    }

    // Запомненные URL профиля для «повторного клика»: если сервер ответил
    // profile_incomplete, первый клик показывает плашку, второй — ведёт на заполнение.
    var pendingProfileRedirect = {};

    function loadModal(url, title) {
        openModal(title);
        modalBody.innerHTML = '<p style="color:var(--text-secondary);">Загрузка…</p>';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) {
                var ct = r.headers.get('content-type') || '';
                if (ct.indexOf('application/json') !== -1) {
                    return r.json().then(function (data) { return { json: data }; });
                }
                return r.text().then(function (html) { return { html: html }; });
            })
            .then(function (result) {
                // Профиль не заполнен: не показываем форму — показываем плашку с призывом
                // заполнить ФИО/ТГ/телефон и кнопку перехода в личный кабинет. Если по этой
                // же кнопке кликнули повторно — сразу переносим на заполнение профиля.
                if (result.json && result.json.profile_incomplete) {
                    if (pendingProfileRedirect[url]) {
                        window.location.href = result.json.profile_url;
                        return;
                    }
                    pendingProfileRedirect[url] = result.json.profile_url;
                    modalBody.innerHTML =
                        '<p style="margin-top:0;">' + (result.json.message || 'Заполните профиль, чтобы подать заявку.') + '</p>' +
                        '<a href="' + result.json.profile_url + '" class="btn">Перейти в личный кабинет</a>';
                    return;
                }
                document.querySelectorAll('.timepicker-list').forEach(function (el) { el.remove(); });
                modalBody.innerHTML = result.html;
                initCharCounters(modalBody);
                initEventForm(modalBody);
                bindModalForm(url);
            });
    }

    document.addEventListener('click', function (event) {
        var trigger = event.target.closest('[data-modal]');
        if (!trigger) return;
        event.preventDefault();
        loadModal(trigger.getAttribute('href'), trigger.getAttribute('data-modal-title') || trigger.textContent.trim());
    });

    modalClose.addEventListener('click', closeModal);
    modalBackdrop.addEventListener('click', function (event) {
        if (event.target === modalBackdrop) closeModal();
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !modalBackdrop.hidden) closeModal();
    });

    // ======================================================================
    // Форма мероприятия: инициализация чип-виджетов (категории/тим-лидеры) и
    // date-picker'ов. Вызывается при загрузке формы в модалку и на обычной странице.
    // ======================================================================
