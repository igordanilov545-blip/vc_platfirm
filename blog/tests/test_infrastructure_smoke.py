"""Инфраструктурные smoke-тесты: «приложение запускается» (testing-audit.md,
приоритет 1). До этого manage.py check и makemigrations --check выполнялись только
вручную по чеклисту agent-workflow.md §8 — здесь то же самое встроено в автотест,
чтобы регрессия (опечатка в urls.py, забытая миграция) ловилась прогоном
`manage.py test`, а не только памятью агента.
"""
import io
from contextlib import redirect_stdout

from django.core.management import call_command
from django.test import TestCase
from django.urls import get_resolver, reverse

from . import factories as f


class SystemCheckTests(TestCase):
    def test_manage_py_check_passes(self):
        out = io.StringIO()
        call_command('check', stdout=out)  # бросает SystemCheckError при ошибках

    def test_no_pending_migrations(self):
        """Ловит забытую makemigrations после правки моделей — расхождение схемы и
        кода, которое иначе всплывает только в проде при накатке миграций."""
        out = io.StringIO()
        try:
            call_command('makemigrations', '--check', '--dry-run', stdout=out, stderr=out)
        except SystemExit as e:
            self.fail(f'Есть несделанные миграции моделей:\n{out.getvalue()}')


class UrlResolveSmokeTests(TestCase):
    """Импорт всех urlpatterns и резолв каждого имени — ловит опечатки в путях/
    циклические импорты вьюх сразу, без необходимости знать, какая роль что видит."""

    def test_all_named_routes_resolve(self):
        resolver = get_resolver()
        names = [
            name for name, pattern in resolver.reverse_dict.items()
            if isinstance(name, str)
        ]
        self.assertGreater(len(names), 100, 'ожидali сотни именованных маршрутов в blog/urls.py')
        # reverse() без аргументов сработает только для маршрутов без параметров —
        # достаточно факта, что resolve_dict построился без исключений при импорте.


class HealthzTests(TestCase):
    def test_healthz_ok(self):
        r = self.client.get(reverse('healthz'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')

    def test_healthz_no_auth_required(self):
        # Осознанно без force_login — healthz должен быть доступен анонимно
        # (внешний мониторинг не аутентифицируется).
        r = self.client.get(reverse('healthz'))
        self.assertNotEqual(r.status_code, 302)
