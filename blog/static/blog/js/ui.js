/*
 * static/blog/js/ui.js
 * Интерфейс оболочки: dblclick-строки, сайдбар, тема, лист «Ещё», счётчики
 * символов, показ/скрытие пароля, тосты.
 *
 * Часть распила инлайнового JS base.html (см. static/blog/js/README.md).
 * Грузится обычным <script> (не модуль) — все init-функции и хелперы остаются в
 * глобальном scope, как раньше; initPageContent зовёт их через window[fn].
 */
    // Double-click по строке таблицы с data-href → переход на страницу деталей/профиля.
    document.addEventListener('dblclick', function (event) {
        var row = event.target.closest('tr[data-href]');
        if (row) {
            window.location.href = row.getAttribute('data-href');
        }
    });

    // Сворачивание сайдбара — состояние в cookie (переживает переход между страницами).
    var sidebarToggle = document.getElementById('sidebar-toggle');
    if (sidebarToggle) {
        var collapsed = document.body.classList.contains('sidebar-collapsed');
        var updateToggleLabel = function () {
            var icon = document.getElementById('sidebar-toggle-icon');
            var label = document.getElementById('sidebar-toggle-label');
            icon.textContent = collapsed ? '➡️' : '⬅️';
            label.textContent = collapsed ? ' Развернуть' : ' Свернуть';
        };
        updateToggleLabel();
        sidebarToggle.addEventListener('click', function () {
            collapsed = !collapsed;
            document.body.classList.toggle('sidebar-collapsed', collapsed);
            document.cookie = 'sidebar_collapsed=' + (collapsed ? '1' : '0') + ';path=/;max-age=31536000';
            updateToggleLabel();
        });
    }

    // Переключатель светлой/тёмной темы — состояние в localStorage.
    // Два триггера: кнопка в сайдбаре (десктоп) и пункт в листе «Ещё» (мобайл) —
    // делят одно состояние, поэтому подписи обновляются у обоих.
    var themeToggle = document.getElementById('theme-toggle');
    var moreThemeToggle = document.getElementById('more-theme-toggle');
    if (themeToggle || moreThemeToggle) {
        var systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        var currentTheme = localStorage.getItem('theme') || (systemPrefersDark ? 'dark' : 'light');
        var setText = function (id, text) {
            var el = document.getElementById(id);
            if (el) el.textContent = text;
        };
        var updateThemeLabel = function () {
            var dark = currentTheme === 'dark';
            setText('theme-icon', dark ? '☀️' : '🌙');
            setText('theme-label', dark ? ' Светлая тема' : ' Тёмная тема');
            setText('more-theme-icon', dark ? '☀️' : '🌙');
            setText('more-theme-label', dark ? 'Светлая тема' : 'Тёмная тема');
        };
        document.documentElement.setAttribute('data-theme', currentTheme);
        updateThemeLabel();
        var toggleTheme = function () {
            currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', currentTheme);
            localStorage.setItem('theme', currentTheme);
            updateThemeLabel();
        };
        if (themeToggle) themeToggle.addEventListener('click', toggleTheme);
        if (moreThemeToggle) moreThemeToggle.addEventListener('click', toggleTheme);
    }

    // Мобильный лист «Ещё»: открытие/закрытие. Закрывается по клику вне листа,
    // по Esc и по выбору пункта-действия (кнопки внутри — тема/гид).
    (function () {
        var moreBtn = document.getElementById('more-tab-btn');
        var backdrop = document.getElementById('more-sheet-backdrop');
        var sheet = document.getElementById('more-sheet');
        if (!moreBtn || !backdrop || !sheet) return;
        var openMore = function () {
            backdrop.hidden = false;
            document.body.classList.add('more-sheet-open');
            moreBtn.setAttribute('aria-expanded', 'true');
        };
        var closeMore = function () {
            backdrop.hidden = true;
            document.body.classList.remove('more-sheet-open');
            moreBtn.setAttribute('aria-expanded', 'false');
        };
        moreBtn.addEventListener('click', openMore);
        backdrop.addEventListener('click', function (e) {
            if (e.target === backdrop) closeMore();
        });
        // Клик по кнопкам-действиям (тема/гид) не уводит со страницы — закрываем лист вручную.
        sheet.querySelectorAll('button.more-item').forEach(function (b) {
            b.addEventListener('click', closeMore);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !backdrop.hidden) closeMore();
        });
    })();

    // Счётчик символов для полей с maxlength (brandbook §6.2) — навешивается на любой
    // input/textarea с атрибутом maxlength в переданном контейнере (страница или модалка).
    function initCharCounters(root) {
        root.querySelectorAll('textarea[maxlength], input[maxlength]').forEach(function (field) {
            if (field.dataset.counterInit) return;
            field.dataset.counterInit = '1';
            var counter = document.createElement('div');
            counter.className = 'char-counter';
            field.insertAdjacentElement('afterend', counter);
            var max = parseInt(field.getAttribute('maxlength'), 10);
            var update = function () {
                var len = field.value.length;
                counter.textContent = len + ' / ' + max;
                counter.classList.toggle('warn', len / max > 0.9);
            };
            field.addEventListener('input', update);
            update();
        });
    }
    initCharCounters(document);

    // ======================================================================
    // Кнопка «показать/скрыть пароль» (глазик) — оборачивает каждое поле
    // type=password в контейнер с абсолютно спозиционированной кнопкой-иконкой,
    // переключающей type между password/text.
    // ======================================================================
    function initPasswordToggle(root) {
        root.querySelectorAll('input[type="password"]').forEach(function (input) {
            if (input.dataset.pwToggleInit) return;
            input.dataset.pwToggleInit = '1';

            var wrap = document.createElement('div');
            wrap.style.position = 'relative';
            wrap.style.display = 'flex';
            input.parentNode.insertBefore(wrap, input);
            wrap.appendChild(input);
            input.style.paddingRight = '38px';

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.setAttribute('aria-label', 'Показать пароль');
            btn.title = 'Показать/скрыть пароль';
            btn.textContent = '👁';
            btn.style.cssText = 'position:absolute; right:6px; top:50%; transform:translateY(-50%); ' +
                'background:none; border:none; cursor:pointer; font-size:16px; line-height:1; padding:4px;';
            btn.addEventListener('click', function () {
                var shown = input.type === 'text';
                input.type = shown ? 'password' : 'text';
                btn.textContent = shown ? '👁' : '🙈';
            });
            wrap.appendChild(btn);
        });
    }
    initPasswordToggle(document);

    // ======================================================================
    // Toast-уведомления — плавающий контейнер поверх контента (fixed, верхний
    // правый угол), не привязан к прокрутке страницы, поэтому заметен даже если
    // #page-main был подменён soft-nav'ом и пользователь не наверху страницы.
    // Django messages при первой загрузке страницы переносятся сюда же (initToasts),
    // а showToast(text, kind) можно вызывать и из любого другого JS-кода на странице
    // (напр. после успешной AJAX-модалки или клиентского действия вроде «Смена добавлена»).
    // ======================================================================
    var toastHost = document.getElementById('toast-host');
    if (!toastHost) {
        toastHost = document.createElement('div');
        toastHost.id = 'toast-host';
        toastHost.style.cssText = 'position:fixed; top:16px; right:16px; z-index:9999; ' +
            'display:flex; flex-direction:column; gap:8px; max-width:360px;';
        document.body.appendChild(toastHost);
    }

    function showToast(text, kind) {
        var el = document.createElement('div');
        el.className = 'messages-toast ' + (kind || 'success');
        el.style.cssText = 'padding:12px 16px; border-radius:var(--radius-lg, 10px); ' +
            'box-shadow:0 4px 16px rgba(0,0,0,0.18); font-size:0.9rem; opacity:0; ' +
            'transition:opacity 0.3s ease, transform 0.3s ease; transform:translateY(-8px);';
        if (kind === 'error' || kind === 'danger') {
            el.style.background = 'var(--danger, #d33)'; el.style.color = '#fff';
        } else if (kind === 'warning') {
            el.style.background = 'var(--warning, #e0a800)'; el.style.color = '#fff';
        } else {
            el.style.background = 'var(--success, #2a9d5c)'; el.style.color = '#fff';
        }
        el.textContent = text;
        toastHost.appendChild(el);
        requestAnimationFrame(function () {
            el.style.opacity = '1';
            el.style.transform = 'translateY(0)';
        });
        setTimeout(function () {
            el.style.opacity = '0';
            el.style.transform = 'translateY(-8px)';
            setTimeout(function () { el.remove(); }, 350);
        }, 6000);
    }
    window.showToast = showToast;

    // Django messages, отрендеренные сервером (полная загрузка страницы ИЛИ
    // подмена #page-main через soft-nav) — переносим в тот же toast-контейнер и
    // убираем исходный статичный блок, чтобы не дублировать текст на странице.
    function initToasts(root) {
        (root || document).querySelectorAll('.messages li').forEach(function (li) {
            if (li.dataset.toastInit) return;
            li.dataset.toastInit = '1';
            showToast(li.textContent.trim(), li.className);
            li.remove();
        });
    }
    initToasts(document);

    // ======================================================================
    // Модалка (десктоп) / bottom sheet (мобайл) для форм создания/редактирования.
    // Ссылки с `data-modal` и заголовком в `data-modal-title` открывают форму по
    // своему href через AJAX внутрь оверлея вместо перехода на отдельную страницу
    // (brandbook §6.2). Сервер отличает AJAX по заголовку X-Requested-With и
    // возвращает либо partial формы, либо {"redirect": url} при успехе.
    // ======================================================================
    var modalBackdrop = document.getElementById('modal-backdrop');
    var modalBody = document.getElementById('modal-body');
    var modalTitle = document.getElementById('modal-title');
    var modalClose = document.getElementById('modal-close');
