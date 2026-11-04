/* Общая тема для всех оформлений. Полная форма настроек работает обычным POST. */
(function () {
    var root = document.documentElement;
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    var buttons = ['theme-toggle', 'more-theme-toggle'];
    var pending = false;

    function apply(preference) {
        root.dataset.colorTheme = preference;
        var dark = preference === 'system' ? media.matches : preference === 'dark';
        root.dataset.theme = dark ? 'dark' : 'light';
        root.style.colorScheme = root.dataset.theme;
        ['theme-icon', 'more-theme-icon'].forEach(function (id) {
            var icon = document.getElementById(id);
            if (icon) icon.textContent = dark ? '☀️' : '🌙';
        });
        ['theme-label', 'more-theme-label'].forEach(function (id) {
            var label = document.getElementById(id);
            if (label) label.textContent = dark ? 'Светлая тема' : 'Тёмная тема';
        });
        document.querySelectorAll('input[name="color_theme"]').forEach(function (input) {
            input.checked = input.value === preference;
        });
    }

    function toggle() {
        if (pending) return;
        var before = root.dataset.colorTheme;
        var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
        var notice = document.getElementById('appearance-notice');
        if (notice) notice.hidden = true;
        apply(next);
        var transport = document.getElementById('appearance-transport');
        if (!transport) {
            try { localStorage.setItem('theme', next); } catch (error) { /* Необязательный кэш гостя. */ }
            return;
        }
        var data = new FormData(transport);
        data.set('color_theme', next);
        pending = true;
        buttons.forEach(function (id) { var button = document.getElementById(id); if (button) button.disabled = true; });
        fetch(transport.action, {
            method: 'POST', body: data, credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (response) {
            if (!response.ok || response.redirected) throw new Error('save failed');
            return response.json();
        }).then(function (result) {
            apply(result.color_theme);
        }).catch(function () {
            apply(before);
            if (notice) {
                notice.textContent = 'Не удалось сохранить тему. Попробуйте ещё раз.';
                notice.hidden = false;
            }
        }).finally(function () {
            pending = false;
            buttons.forEach(function (id) { var button = document.getElementById(id); if (button) button.disabled = false; });
        });
    }
    buttons.forEach(function (id) {
        var button = document.getElementById(id);
        if (button) button.addEventListener('click', toggle);
    });
    media.addEventListener('change', function () {
        if (root.dataset.colorTheme === 'system') apply('system');
    });
    apply(root.dataset.colorTheme);
})();
