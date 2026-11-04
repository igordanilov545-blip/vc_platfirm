/* До загрузки CSS: предпочтения вошедшего пользователя всегда берём из аккаунта. */
(function () {
    var root = document.documentElement;
    var preference = root.dataset.colorTheme || 'system';
    if (!root.dataset.appearanceOwner) {
        try {
            var legacy = localStorage.getItem('theme');
            if (legacy === 'light' || legacy === 'dark') preference = legacy;
        } catch (error) { /* Закрытое хранилище не мешает настройкам аккаунта. */ }
    }
    root.dataset.colorTheme = preference;
    root.dataset.theme = preference === 'system'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : preference;
    root.style.colorScheme = root.dataset.theme;
})();
