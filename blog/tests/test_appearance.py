from django.test import Client, TestCase
from django.urls import reverse

from blog.tests.factories import make_manager, make_user


class AppearanceTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user()
        self.client.force_login(self.user)
        self.url = reverse('appearance_update')

    def test_default_and_volunteer_settings(self):
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="appearance"')
        self.assertContains(response, 'data-appearance="nexus"')

    def test_selection_persists_for_account_and_other_device(self):
        response = self.client.post(self.url, {'appearance': 'minecraft', 'color_theme': 'dark'})
        self.assertRedirects(response, reverse('settings') + '?tab=appearance')
        self.user.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual((self.user.appearance, self.user.color_theme), ('minecraft', 'dark'))
        self.assertEqual(self.other.appearance, 'nexus')
        device = Client()
        device.force_login(self.user)
        page = device.get(reverse('settings'))
        self.assertContains(page, 'data-appearance="minecraft"')
        self.assertContains(page, 'data-theme="dark"')
        self.assertContains(page, '/blog/css/appearances/minecraft.')

    def test_rejects_invalid_selection_without_partial_write(self):
        response = self.client.post(self.url, {'appearance': 'minecraft', 'color_theme': 'invalid'})
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.appearance, 'nexus')
        response = self.client.post(self.url, {'appearance': '../../evil', 'color_theme': 'light'})
        self.assertEqual(response.status_code, 400)

    def test_theme_toggle_preserves_appearance_and_cannot_target_another_user(self):
        self.client.post(self.url, {'appearance': 'minecraft', 'color_theme': 'light'})
        response = self.client.post(self.url, {'color_theme': 'dark', 'user_id': self.other.pk},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['color_theme'], 'dark')
        self.user.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual((self.user.appearance, self.user.color_theme), ('minecraft', 'dark'))
        self.assertEqual(self.other.color_theme, 'system')

    def test_guest_cannot_save_and_get_cannot_mutate(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, {'appearance': 'minecraft'}).status_code, 302)

    def test_csrf_and_manager_permissions(self):
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(self.url, {'color_theme': 'dark'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('settings') + '?tab=constants').status_code, 403)
        manager = make_manager()
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse('settings')).status_code, 200)
        self.assertEqual(self.client.get(reverse('settings') + '?tab=appearance').status_code, 200)

    def test_both_themes_and_return_to_original(self):
        for appearance, theme in [('minecraft', 'light'), ('minecraft', 'dark'), ('nexus', 'system')]:
            self.client.post(self.url, {'appearance': appearance, 'color_theme': theme})
            page = self.client.get(reverse('settings'))
            self.assertContains(page, f'data-appearance="{appearance}"')
            if appearance == 'nexus':
                self.assertNotContains(page, 'href="/static/blog/css/appearances/minecraft')
