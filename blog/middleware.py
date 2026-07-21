"""Middleware специфичные для TG Mini App (architecture.md §2.1, §3) и для
трекинга активности (аналитика/дашборд логов)."""
import time

from django.utils import timezone

ANALYTICS_EXCLUDED_PREFIXES = ('/static/', '/analytics/', '/admin/')


class TelegramWebAppFrameMiddleware:
    """Разрешает встраивание сайта в `<iframe>` только для сессий, вошедших через
    Mini App (`views.webapp_auth` ставит `request.session['is_webapp_session'] = True`).
    Обычный веб-вход по логину/паролю по-прежнему защищён `XFrameOptionsMiddleware`
    (DENY) — этот middleware должен идти позже него в `MIDDLEWARE`, чтобы иметь
    возможность переопределить уже выставленный заголовок.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, 'session', None) and request.session.get('is_webapp_session'):
            response['X-Frame-Options'] = 'ALLOWALL'
        return response


class ActivityTrackingMiddleware:
    """Пишет структурированные события активности (analytics_web_sessions/
    analytics_web_page_views) для дашборда аналитики. Должен идти после
    `AuthenticationMiddleware` в MIDDLEWARE, чтобы иметь `request.user`.

    `WebPageView` создаётся в `process_view` (после разрешения URL, но до вызова
    самого view) — так его id доступен уже во время рендера шаблона через
    `request.analytics_page_view_id` (подставляется в `<body data-page-view-id>`,
    `base.html`, для heartbeat из `analytics.js`). `load_ms` дозаписывается после
    ответа. Сбой аналитики никогда не должен ронять ответ пользователю — вся
    запись обёрнута в try/except с логированием в веб-канал.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        try:
            self._finalize(request, time.monotonic() - started)
        except Exception:
            from blog.logging_utils import get_web_logger
            get_web_logger(__name__).exception('Сбой ActivityTrackingMiddleware (finalize)')
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        try:
            self._start(request)
        except Exception:
            from blog.logging_utils import get_web_logger
            get_web_logger(__name__).exception('Сбой ActivityTrackingMiddleware (start)')
        return None

    def _trackable(self, request):
        path = request.path
        if path.startswith(ANALYTICS_EXCLUDED_PREFIXES):
            return False
        if request.method != 'GET':
            return False
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return False
        session = getattr(request, 'session', None)
        if session is None:
            return False
        return True

    def _start(self, request):
        if not self._trackable(request):
            return
        session = request.session
        if not session.session_key:
            session.save()  # форсируем создание session_key для гостей без куки-сессии

        from data_base import data_controller as dc
        from blog.services.roles import role_slug

        user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        now = timezone.now()

        web_session = dc.get_or_create_web_session(
            session.session_key,
            user=user,
            role_snapshot=role_slug(user) if user else 'guest',
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            seen_at=now,
        )

        view_name = request.resolver_match.url_name if request.resolver_match else ''
        page_view = dc.create_web_page_view(web_session, request.path, view_name)
        request.analytics_page_view_id = page_view.id

    def _finalize(self, request, elapsed_seconds):
        page_view_id = getattr(request, 'analytics_page_view_id', None)
        if page_view_id is None:
            return
        from data_base import data_controller as dc
        dc.set_page_view_load_ms(page_view_id, int(elapsed_seconds * 1000))
