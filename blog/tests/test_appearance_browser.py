"""Опциональный браузерный прогон: VC_PLAYWRIGHT_PACKAGE указывает установленный пакет."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse

from blog.tests.factories import make_manager, make_user, make_event, make_shift, make_application
from blog.models import ChurnLog


# Живой браузер одновременно загружает вкладки и пишет настройки. Именованная
# in-memory SQLite выдаёт SQLITE_LOCKED без ожидания и может обнулить чтение сессии.
# Отдельный временный файл использует штатный WAL/timeout и удаляется test runner.
if os.environ.get('VC_PLAYWRIGHT_PACKAGE') and settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
    settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = str(
        Path(tempfile.gettempdir()) / f'vc-appearance-browser-{os.getpid()}.sqlite3'
    )


@skipUnless(os.environ.get('VC_PLAYWRIGHT_PACKAGE'), 'Нужен установленный Playwright')
@override_settings(
    DEBUG=True, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    # Телеметрия покрыта test_analytics_smoke. Её фоновые записи конкурируют с
    # чтением сессии в общей in-memory SQLite StaticLiveServerTestCase.
    MIDDLEWARE=[item for item in settings.MIDDLEWARE if item != 'blog.middleware.ActivityTrackingMiddleware'],
)
class AppearanceBrowserTests(StaticLiveServerTestCase):
    def test_appearance_workflows(self):
        """Выбор вручную, перезагрузка, темы, общий браузер, мобильное меню и модалка."""
        volunteer = make_user(first_name='Анна', last_name='Волкова', total_hours=128,
                              season_hours=24, total_event_count=18)
        manager = make_manager(first_name='Михаил', last_name='Орлов', total_hours=256)
        event = make_event(title='Городской полумарафон')
        shift = make_shift(event)
        for index in range(4):
            participant = volunteer if index == 0 else make_user()
            make_application(event, user=participant, shifts=[shift])
        ChurnLog.objects.create(user=volunteer, reason='activity_decay', delta=-.5, new_value=1, actor=manager)
        sessions = []
        for user in (volunteer, manager):
            device = Client()
            device.force_login(user)
            sessions.append({'id': user.pk, 'cookie': device.cookies[settings.SESSION_COOKIE_NAME].value,
                             'profile': reverse('profile_detail', args=[user.pk])})
        result = subprocess.run(
            ['node', str(settings.BASE_DIR / 'blog/tests/browser/appearance.cjs')],
            input=json.dumps({'origin': self.live_server_url, 'sessions': sessions,
                              'cookieName': settings.SESSION_COOKIE_NAME,
                              'pending': reverse('pending_applications'),
                              'managedProfile': reverse('profile_detail', args=[volunteer.pk])}),
            text=True, encoding='utf-8', capture_output=True, timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
