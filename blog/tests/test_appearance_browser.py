"""Опциональный браузерный прогон: VC_PLAYWRIGHT_PACKAGE указывает установленный пакет."""
import json
import os
from pathlib import Path
import subprocess
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse

from blog.tests.factories import make_manager, make_user


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
        sessions = []
        for user in (volunteer, manager):
            device = Client()
            device.force_login(user)
            sessions.append({'id': user.pk, 'cookie': device.cookies[settings.SESSION_COOKIE_NAME].value,
                             'profile': reverse('profile_detail', args=[user.pk])})
        result = subprocess.run(
            ['node', str(settings.BASE_DIR / 'blog/tests/browser/appearance.cjs')],
            input=json.dumps({'origin': self.live_server_url, 'sessions': sessions,
                              'cookieName': settings.SESSION_COOKIE_NAME}),
            text=True, encoding='utf-8', capture_output=True, timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
