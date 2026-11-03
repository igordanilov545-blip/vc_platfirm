"""Search is applied to the database before pagination, never just to loaded rows."""
import re
from django.test import TestCase
from django.urls import reverse
from blog.models import User
from blog.services.user_table import user_table_context
from . import factories as f


class UserSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = f.make_manager()
        cls.anna_ids = []
        for i in range(145):
            cls.anna_ids.append(f.make_user(first_name='Анна', last_name=f'Поискова{i}',
                                           telegram_username=f'fixture_anna_{i}').pk)
        cls.target = f.make_user(first_name='Алёна', last_name='Данилова', middle_name='Ивановна',
                                 telegram_username='literal[a].+')
        cls.leader = f.make_team_leader(first_name='Анна')
        for _ in range(65):
            f.make_user(first_name='Другой')

    def setUp(self):
        self.client.force_login(self.manager)
        self.url = reverse('user_list')

    def test_search_reaches_every_old_record_before_pagination(self):
        default = self.client.get(self.url)
        self.assertFalse(set(u.pk for u in default.context['page_obj']) & set(self.anna_ids))
        response = self.client.get(self.url, {'q': 'анна'})
        self.assertEqual(response.context['page_obj'].paginator.count, 146)
        self.assertEqual(len(response.context['page_obj']), 40)
        self.assertTrue(all('анна' in u.first_name.casefold() for u in response.context['page_obj']))
        full = self.client.get(self.url, {'q': 'анна', 'all': '1'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(len(full.context['page_obj']), 146)
        self.assertContains(full, 'data-total="146"')
        self.assertContains(full, 'data-next-page=""')

    def test_unicode_name_tokens_and_literal_social_handle(self):
        for query in ('   ДАНИЛОВА   АЛЕНА ', 'ивановна данил', '@literal[a].+'):
            with self.subTest(query=query):
                context = user_table_context(query=query, full=True, owner_id=self.manager.pk)
                self.assertEqual([u.pk for u in context['page_obj']], [self.target.pk])

    def test_role_and_query_apply_together_to_primary_active_role(self):
        for role, expected in [('volunteer', 145), ('team_lead', 1), ('manager', 0)]:
            context = user_table_context(query='анна', role=role, full=True, owner_id=self.manager.pk)
            self.assertEqual(len(context['page_obj']), expected)

    def test_ajax_pages_never_append_unrelated_people(self):
        seen = set()
        for page in (1, 2, 3, 4):
            response = self.client.get(self.url, {'q': 'анна', 'role': 'volunteer', 'page': page},
                                       HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            users = list(response.context['page_obj'])
            self.assertTrue(all(u.pk in self.anna_ids for u in users))
            self.assertFalse(seen & {u.pk for u in users})
            seen.update(u.pk for u in users)
        self.assertEqual(seen, set(self.anna_ids))

    def test_empty_results_and_form_work_without_javascript(self):
        response = self.client.get(self.url, {'q': 'не существует', 'role': 'volunteer'})
        self.assertEqual(response.context['page_obj'].paginator.count, 0)
        self.assertContains(response, 'Совпадений не найдено')
        self.assertContains(response, 'method="get"')
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'data-table-query-form="#users-table"')
        self.assertContains(response, 'Найдено: 0')

    def test_matching_count_and_native_load_all_are_visible_without_scripts(self):
        response = self.client.get(self.url, {'q': 'анна'})
        self.assertContains(response, 'Найдено: 146')
        self.assertContains(response, 'data-table-load-all')

    def test_last_page_can_still_show_all_matches(self):
        response = self.client.get(self.url, {'q': 'анна', 'page': 4})
        self.assertEqual(len(response.context['page_obj']), 26)
        link = re.search(r'<a[^>]*data-table-load-all[^>]*>', response.content.decode()).group(0)
        self.assertNotIn('hidden', link)
        full = self.client.get(self.url, {'q': 'анна', 'page': 4, 'all': 1})
        self.assertEqual(len(full.context['page_obj']), 146)

    def test_query_cache_is_separate_and_revalidates_changed_matches(self):
        ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        first = self.client.get(self.url, {'q': 'анна', 'all': '1'}, **ajax)
        self.assertEqual(self.client.get(self.url, {'q': 'анна', 'all': '1'},
                         HTTP_IF_NONE_MATCH=first['ETag'], **ajax).status_code, 304)
        other = self.client.get(self.url, {'q': 'данил', 'all': '1'},
                                HTTP_IF_NONE_MATCH=first['ETag'], **ajax)
        self.assertEqual(other.status_code, 200)
        User.objects.filter(pk=self.anna_ids[0]).update(first_name='Изменено', telegram_username='changed')
        changed = self.client.get(self.url, {'q': 'анна', 'all': '1'},
                                  HTTP_IF_NONE_MATCH=first['ETag'], **ajax)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(len(changed.context['page_obj']), 145)
