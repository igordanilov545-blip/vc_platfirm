/* Общие переключатели и автосохранение внутри существующей модалки проекта. */
(function () {
    var root = document.documentElement;
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    var buttons = ['theme-toggle', 'more-theme-toggle'];
    var pending = false;
    window.setAppearanceIcon = function (element, name, fallback) {
        if (!element) return;
        if (root.dataset.appearance !== 'minecraft') { element.textContent = fallback; return; }
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'mc-icon'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
        var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        use.setAttribute('href', '#mc-icon-' + name); svg.appendChild(use); element.replaceChildren(svg);
    };

    function syncAppearance() {
        document.querySelectorAll('[data-appearance-form] input[name="appearance"]').forEach(function (input) {
            input.checked = input.value === root.dataset.appearance;
        });
    }

    function apply(preference) {
        root.dataset.colorTheme = preference;
        var dark = preference === 'system' ? media.matches : preference === 'dark';
        root.dataset.theme = dark ? 'dark' : 'light';
        root.style.colorScheme = root.dataset.theme;
        ['theme-icon', 'more-theme-icon'].forEach(function (id) {
            var icon = document.getElementById(id);
            window.setAppearanceIcon(icon, dark ? 'sun' : 'moon', dark ? '☀️' : '🌙');
        });
        ['theme-label', 'more-theme-label'].forEach(function (id) {
            var label = document.getElementById(id);
            if (label) label.textContent = dark ? 'Светлая тема' : 'Тёмная тема';
        });
        document.querySelectorAll('input[name="color_theme"]').forEach(function (input) {
            input.checked = input.value === preference;
        });
    }

    function save(fields, form) {
        if (pending) return;
        var before = root.dataset.colorTheme;
        var notice = document.getElementById('appearance-notice');
        if (notice) notice.hidden = true;
        if (fields.color_theme) apply(fields.color_theme);
        var transport = document.getElementById('appearance-transport');
        if (!transport) {
            try { localStorage.setItem('theme', fields.color_theme); } catch (error) { /* Необязательный кэш гостя. */ }
            return;
        }
        var data = new FormData(transport);
        Object.keys(fields).forEach(function (key) { data.set(key, fields[key]); });
        pending = true;
        var status = form && form.querySelector('[data-appearance-status]');
        if (form) form.dataset.saving = 'true';
        if (status) { status.textContent = 'Сохранение…'; status.removeAttribute('data-error'); }
        document.querySelectorAll('[data-appearance-form] input[type="radio"]').forEach(function (input) { input.disabled = true; });
        buttons.forEach(function (id) { var button = document.getElementById(id); if (button) button.disabled = true; });
        fetch(transport.action, {
            method: 'POST', body: data, credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (response) {
            if (!response.ok || response.redirected) throw new Error('save failed');
            return response.json();
        }).then(function (result) {
            apply(result.color_theme);
            if (result.appearance !== root.dataset.appearance) {
                // Полная загрузка обновляет CSS, декор и навигацию согласованно.
                // Параметр открывает ту же модалку после загрузки, без localStorage.
                var url = new URL(window.location.href);
                url.searchParams.set('appearance', 'open');
                window.location.replace(url.href);
                return;
            }
            if (status) status.textContent = 'Сохранено';
        }).catch(function () {
            apply(before);
            syncAppearance();
            if (status) { status.textContent = 'Не удалось сохранить. Попробуйте ещё раз.'; status.dataset.error = 'true'; }
            if (notice) {
                notice.textContent = 'Не удалось сохранить оформление. Попробуйте ещё раз.';
                notice.hidden = false;
            }
        }).finally(function () {
            pending = false;
            if (form) delete form.dataset.saving;
            document.querySelectorAll('[data-appearance-form] input[type="radio"]').forEach(function (input) { input.disabled = false; });
            buttons.forEach(function (id) { var button = document.getElementById(id); if (button) button.disabled = false; });
        });
    }
    function toggle() {
        save({color_theme: root.dataset.theme === 'dark' ? 'light' : 'dark'}, document.querySelector('[data-appearance-form]'));
    }
    document.addEventListener('change', function (event) {
        var input = event.target;
        var form = input.closest('[data-appearance-form]');
        if (!form || !input.checked || !['appearance', 'color_theme'].includes(input.name)) return;
        var fields = {};
        fields[input.name] = input.value;
        save(fields, form);
    });
    document.addEventListener('submit', function (event) {
        if (event.target.matches('[data-appearance-form]')) event.preventDefault();
    });
    buttons.forEach(function (id) {
        var button = document.getElementById(id);
        if (button) button.addEventListener('click', toggle);
    });
    media.addEventListener('change', function () {
        if (root.dataset.colorTheme === 'system') apply('system');
    });
    apply(root.dataset.colorTheme);
    document.addEventListener('DOMContentLoaded', function () {
        var url = new URL(window.location.href);
        if (url.searchParams.get('appearance') !== 'open') return;
        var transport = document.getElementById('appearance-transport');
        if (!transport || typeof window.loadModal !== 'function') return;
        url.searchParams.delete('appearance');
        history.replaceState(null, '', url.pathname + url.search + url.hash);
        window.loadModal(transport.dataset.dialogUrl, 'Оформление и тема');
    });
})();
