"""Users table: full dataset, separate identity columns, roles and private cache."""
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import Manager, TeamLeader
from . import factories as f


class UserTableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = f.make_manager()
        cls.target = f.make_user(first_name='Алёна', last_name='Данилова',
                                 middle_name='Ивановна', birthday=date(2000, 11, 4))
        for _ in range(45):
            f.make_user()
        cls.leader = f.make_team_leader()
        cls.revoked = f.make_user()
        Manager.objects.create(user=cls.revoked, revoked_at=timezone.now())
        TeamLeader.objects.create(user=cls.revoked, revoked_at=timezone.now())

    def setUp(self):
        self.client.force_login(self.manager)
        self.url = reverse('user_list')

    def full(self, **headers):
        return self.client.get(self.url, {'all': '1', 'table_owner': self.manager.pk},
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest', **headers)

    def test_default_page_remains_small_but_full_load_reaches_oldest_user(self):
        first = self.client.get(self.url)
        self.assertEqual(len(first.context['page_obj']), 40)
        self.assertNotContains(first, 'Данилова')
        full = self.full()
        self.assertEqual(len(full.context['page_obj']), 50)
        self.assertContains(full, 'Данилова')
        self.assertContains(full, 'data-next-page=""')
        self.assertNotContains(full, '<html')
        self.assertContains(first, 'data-table-cache-owner=')

    def test_name_surname_and_age_are_separate_and_use_moscow_date(self):
        with patch('blog.services.user_table.timezone.localdate', return_value=date(2026, 11, 3)):
            response = self.full()
        target = next(u for u in response.context['page_obj'] if u.pk == self.target.pk)
        self.assertEqual(target.table_age, 25)
        self.assertContains(response, 'data-label="Фамилия"')
        self.assertContains(response, 'data-label="Имя"')
        self.assertContains(response, 'data-label="Возраст"')
        self.assertContains(response, 'Ивановна')  # remains searchable
        with patch('blog.services.user_table.timezone.localdate', return_value=date(2026, 11, 4)):
            response = self.full()
        target = next(u for u in response.context['page_obj'] if u.pk == self.target.pk)
        self.assertEqual(target.table_age, 26)

    def test_role_filter_uses_active_primary_role_and_ignores_revoked_roles(self):
        users = {u.pk: u for u in self.full().context['page_obj']}
        self.assertEqual(users[self.manager.pk].table_role, 'manager')
        self.assertEqual(users[self.leader.pk].table_role, 'team_lead')
        self.assertEqual(users[self.revoked.pk].table_role, 'volunteer')
        page = self.client.get(self.url)
        self.assertContains(page, 'data-table-role-filter="#users-table"')

    def test_browser_cache_revalidates_and_changes_when_displayed_data_changes(self):
        first = self.full()
        self.assertIn('private', first['Cache-Control'])
        self.assertIn('no-cache', first['Cache-Control'])
        self.assertIn('Cookie', first['Vary'])
        unchanged = self.full(HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual(unchanged.status_code, 304)
        self.assertEqual(self.full(HTTP_IF_NONE_MATCH='W/' + first['ETag']).status_code, 304)
        self.target.first_name = 'Новое имя'
        self.target.save(update_fields=['first_name'])
        changed = self.full(HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(first['ETag'], changed['ETag'])
        self.assertContains(changed, 'Новое имя')
        TeamLeader.objects.create(user=self.target)
        role_changed = self.full(HTTP_IF_NONE_MATCH=changed['ETag'])
        self.assertEqual(role_changed.status_code, 200)

    def test_full_table_has_no_query_per_user(self):
        from blog.services.user_table import user_table_context
        with self.assertNumQueries(3):
            context = user_table_context(full=True, owner_id=self.manager.pk)
            list(context['page_obj'])

    def test_cached_endpoint_still_checks_permissions_and_owner(self):
        etag = self.full()['ETag']
        self.client.force_login(self.target)
        self.assertEqual(self.full(HTTP_IF_NONE_MATCH=etag).status_code, 403)
        self.client.force_login(self.leader)
        self.assertEqual(self.full().status_code, 403)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.url, {'all': '1', 'table_owner': self.target.pk},
                                        HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)
