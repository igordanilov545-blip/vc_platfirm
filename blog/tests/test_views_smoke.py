"""Smoke-тесты вьюх, затрагиваемых Фазой 2 (перенос ORM в контроллер).

Проверяют наблюдаемое поведение: ключевые страницы отвечают ожидаемым кодом и
контекст содержит верные данные. Тесты чёрного ящика — переживают перенос ORM во
внутренностях и ловят регрессию (страница «упала» / потеряла данные).
"""
from django.test import TestCase
from django.urls import reverse

from . import factories as f


class ManagerPagesSmokeTests(TestCase):
    """Все менеджерские list/детальные страницы отвечают 200 для менеджера."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        # Немного данных, чтобы страницы рендерили непустые списки.
        self.event = f.make_event(title='Смоук-меро')
        self.shift = f.make_shift(self.event)
        self.volunteer = f.make_user()
        self.application = f.make_application(self.event, user=self.volunteer, shifts=[self.shift])

    def test_dashboard_manager(self):
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['is_manager'])
        # count_applications через контроллер — на дашборде 1 новая заявка.
        self.assertEqual(r.context['new_applications_count'], 1)

    def test_event_list(self):
        r = self.client.get(reverse('event_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Смоук-меро')

    def test_event_detail(self):
        r = self.client.get(reverse('event_detail', args=[self.event.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Смоук-меро')

    def test_pending_applications(self):
        r = self.client.get(reverse('pending_applications'))
        self.assertEqual(r.status_code, 200)

    def test_user_list(self):
        r = self.client.get(reverse('user_list'))
        self.assertEqual(r.status_code, 200)

    def test_profile_detail(self):
        r = self.client.get(reverse('profile_detail', args=[self.volunteer.id]))
        self.assertEqual(r.status_code, 200)

    def test_settings(self):
        r = self.client.get(reverse('settings'))
        self.assertEqual(r.status_code, 200)

    def test_reference_lists_redirect_to_settings_hub(self):
        # Справочники стали панелями хаба настроек (agent-workflow §4): прямой заход
        # редиректит в /settings, а контент отдаётся только по AJAX (X-Requested-With).
        ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        for name in ['location_list', 'organizations_list', 'organizer_list',
                     'requirement_list', 'category_list', 'perk_list']:
            direct = self.client.get(reverse(name))
            self.assertEqual(direct.status_code, 302, f'{name} прямой заход должен быть 302')
            self.assertIn('/settings', direct['Location'], f'{name} должен вести в хаб настроек')
            partial = self.client.get(reverse(name), **ajax)
            self.assertEqual(partial.status_code, 200, f'{name} AJAX-partial должен быть 200')

    def test_dobro_page_redirects_to_reports_hub(self):
        # Добро.ру переехало во вкладку ERP-хаба «Отчёты» (?view=dobro).
        r = self.client.get(reverse('dobro_page'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('view=dobro', r['Location'])

    def test_report_period(self):
        r = self.client.get(reverse('report_period'))
        self.assertEqual(r.status_code, 200)

    def test_users_picker_data_json(self):
        r = self.client.get(reverse('users_picker_data'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')


class AccessControlSmokeTests(TestCase):
    """Менеджерские страницы закрыты для волонтёра, гость — на публичный дашборд."""

    def test_manager_page_forbidden_for_volunteer(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.get(reverse('user_list'))
        self.assertEqual(r.status_code, 403)

    def test_guest_dashboard_is_public(self):
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context.get('is_public'))

    def test_login_required_redirects_guest(self):
        r = self.client.get(reverse('event_list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])


class VolunteerPagesSmokeTests(TestCase):
    def setUp(self):
        self.volunteer = f.make_user()
        self.client.force_login(self.volunteer)

    def test_own_profile(self):
        r = self.client.get(reverse('profile_detail', args=[self.volunteer.id]))
        self.assertEqual(r.status_code, 200)

    def test_event_list_for_volunteer(self):
        f.make_event(title='Открытое')
        r = self.client.get(reverse('event_list'))
        self.assertEqual(r.status_code, 200)
