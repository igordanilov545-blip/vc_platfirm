/* Трекер активности: heartbeat страницы, финальная длительность просмотра при уходе,
 * клики по элементам с [data-track]. Пишет события через blog/views.py analytics_*
 * эндпоинты (blog/urls.py, блок "Аналитика"). Не должен ничего ломать при сбое сети —
 * все отправки best-effort, без ретраев и без блокировки основного UI.
 */
(function () {
    'use strict';

    function getCookie(name) {
        var match = document.cookie.match('(^|;\\s*)' + name + '=([^;]*)');
        return match ? decodeURIComponent(match[2]) : '';
    }

    var CSRF_TOKEN = getCookie('csrftoken');
    var PAGE_VIEW_ID = document.body.getAttribute('data-page-view-id');
    var pageEnteredAt = Date.now();

    function post(url, params) {
        params.csrfmiddlewaretoken = CSRF_TOKEN;
        var body = Object.keys(params)
            .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); })
            .join('&');
        if (navigator.sendBeacon) {
            var blob = new Blob([body], { type: 'application/x-www-form-urlencoded' });
            navigator.sendBeacon(url, blob);
        } else {
            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: body,
                keepalive: true,
            }).catch(function () {});
        }
    }

    function currentDuration() {
        return Date.now() - pageEnteredAt;
    }

    // Heartbeat — только пока PAGE_VIEW_ID известен (middleware создал WebPageView для
    // этого запроса) и вкладка видима.
    if (PAGE_VIEW_ID) {
        setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            post('/analytics/ping/', { page_view_id: PAGE_VIEW_ID, duration_ms: currentDuration() });
        }, 5000);

        window.addEventListener('pagehide', function () {
            post('/analytics/leave/', { page_view_id: PAGE_VIEW_ID, duration_ms: currentDuration() });
        });
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'hidden') {
                post('/analytics/leave/', { page_view_id: PAGE_VIEW_ID, duration_ms: currentDuration() });
            }
        });
    }

    // Клики — делегированный обработчик, не мешает основной логике клика (не вызывает
    // preventDefault/stopPropagation).
    document.addEventListener('click', function (event) {
        var el = event.target.closest('[data-track], button, a.btn, .nav-link, .tab-item');
        if (!el) return;
        var actionKey = el.getAttribute('data-track')
            || el.id
            || (el.tagName === 'A' ? 'link:' + (el.getAttribute('href') || '') : 'btn:' + (el.textContent || '').trim().slice(0, 60));
        if (!actionKey) return;
        var label = (el.getAttribute('data-track-label') || el.textContent || '').trim().slice(0, 200);
        post('/analytics/click/', { action_key: actionKey.slice(0, 150), label: label });
    }, true);
})();
