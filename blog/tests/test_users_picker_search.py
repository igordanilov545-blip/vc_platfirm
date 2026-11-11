"""Выбор людей (data-select-remote="users") ищет по всей базе, а не по подгруженным.

Пикер отдаёт только первые `users_picker_limit` людей (свежие по последнему меро),
чтобы не грузить десятки тысяч строк. Раньше поиск и фильтр ролей («снять роль ТЛ» —
только действующие ТЛ) выполнялись в браузере по этой порции: человек за её пределами
не находился вовсе (жалоба со страницы настроек). Теперь `q` и `filter` применяются на
сервере ДО лимита — те же правила, что у списка пользователей (все слова в любом
порядке, без регистра, ё/е, @, ФИО и Telegram)."""
from django.test import TestCase
from django.urls import reverse

from . import factories as f


class UsersPickerSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = f.make_manager(first_name='Мария', last_name='Менеджерова')
        f.make_const('users_picker_limit', 3)
        for i in range(10):
            f.make_user(first_name='Обычный', last_name=f'Человек{i}', telegram_username=f'plain_{i}')
        # Самые «старые» — не попадают в первую порцию ни по недавности, ни по алфавиту.
        cls.target = f.make_user(first_name='Алёна', last_name='Яковлева', telegram_username='Far_Away')
        cls.leader = f.make_team_leader(first_name='Тимофей', last_name='Ячменев')

    def setUp(self):
        self.client.force_login(self.manager)
        self.url = reverse('users_picker_data')

    def ids(self, **params):
        data = self.client.get(self.url, params).json()
        return {row['id'] for row in data['users']}, data

    def test_default_portion_is_limited(self):
        ids, data = self.ids(order='name')
        self.assertEqual(len(ids), 3)
        self.assertTrue(data['truncated'])
        self.assertNotIn(self.target.pk, ids)

    def test_query_searches_whole_base_before_limit(self):
        for query in ('Яковлева', 'алена яковлева', 'Яковлева Алена', '@far_away', 'ЯКОВ'):
            ids, data = self.ids(order='name', q=query)
            self.assertEqual(ids, {self.target.pk}, query)
            self.assertFalse(data['truncated'])
            self.assertEqual(data['total'], 1)

    def test_role_filter_applies_before_limit(self):
        ids, data = self.ids(order='name', filter='team_lead')
        self.assertIn(self.leader.pk, ids)
        self.assertTrue(all(row['is_team_lead'] for row in data['users']))
        ids, _ = self.ids(order='name', filter='not_team_lead', q='Яковлева')
        self.assertEqual(ids, {self.target.pk})
        ids, _ = self.ids(order='name', filter='manager', q='Ячменев')
        self.assertEqual(ids, set())

    def test_query_results_also_respect_show_all(self):
        ids, data = self.ids(order='name', q='Человек', all='1')
        self.assertEqual(len(ids), 10)
        self.assertFalse(data['truncated'])
        ids, data = self.ids(order='name', q='Человек')
        self.assertEqual(len(ids), 3)
        self.assertTrue(data['truncated'])
        self.assertEqual(data['total'], 10)

    def test_report_people_search_uses_same_rules(self):
        """Поиск человека для отчёта — те же правила: слова в любом порядке, ё/е, Telegram."""
        url = reverse('report_people_search')
        for query in ('Алена Яковлева', 'far_away'):
            data = self.client.get(url, {'q': query}).json()
            self.assertEqual([row['id'] for row in data['users']], [self.target.pk], query)
