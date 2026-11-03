"""Легаси База: анкета, все колонки, идемпотентность и приватность комментариев."""
from datetime import date, datetime
from io import BytesIO
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook
from blog.models import EventGroup, EventShift, User, UserComment, Participation
from blog.services.legacy_workbook import read_legacy_workbook, column_day, phone_key
from blog.services.legacy_import import commit_legacy_base
from . import factories as f


HEADERS = ['Комментарий координатора', 'Комментарий тим-лидера', 'Дата заполнения анкеты',
           'Имя', 'Фамилия', 'Возраст', 'Дата рождения', 'Электронная почта', 'Мобильный телефон',
           'Ник в Telegram', 'Ссылка на вашу страницу в ВКонтакте', 'Ссылка на вашу страницу в Инстаграме',
           'Наиболее удобный способ связи', 'В каких забегах планируете принять участие',
           'Вы могли бы помогать нам в дневное время в будни?', 'Опыт волонтёрства', 'Мотивация быть волонтёром',
           'Знакомые позиции', 'Выполняемые задачи', 'Желание стать тим-лидером', 'Размер футболки', 'Число смен',
           'ММ\n24 сентября\nВыдача', 'ММ\n25 сентября\nВыдача', 'Зелёный марафон', 'VOLUNTEER_ID']
VALUES = ['Заметка координатора', 'Заметка лидера', datetime(2026, 1, 1), 'Анна', 'Иванова', 26,
          datetime(2000, 6, 1), 'anna@example.org', '8 (999) 111-22-33', '@anna', 'Vk.com/anna',
          'https://www.instagram.com/anna/', 'пишите как угодно', 'любые', 'Да, могу', 'о' * 280,
          'Мотивация', 'Позиции', 'Задачи', 'пока не решила', 'XL', 99,
          '7.2 — Ассистент выдачи', '7.2 - Ассистент выдачи', 'Волонтёр медалей', '123']


def workbook(headers=None, values=None, sheet=' б А з А '):
    wb = Workbook()
    wb.active.title = sheet
    wb.active.append(headers or HEADERS)
    wb.active.append(values or VALUES)
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


class LegacyBaseTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()

    def plan(self, headers=None, values=None):
        return read_legacy_workbook(workbook(headers, values))

    def test_parser_normalizes_profile_and_preserves_all_event_columns(self):
        plan = self.plan()
        self.assertFalse(plan['errors'])
        profile = plan['rows'][0]['profile']
        self.assertEqual((profile['telegram_username'], profile['VK_username'], profile['instagram_url']), ('anna', 'anna', 'anna'))
        self.assertEqual(profile['phone'], '+79991112233')
        self.assertEqual(phone_key(89991112233.0), '79991112233')
        self.assertEqual(profile['birthday'], '2000-06-01')
        self.assertEqual(len(profile['volunteer_experience']), 255)
        self.assertIs(profile['weekday_daytime_available'], True)
        self.assertIsNone(profile['wants_team_lead'])
        self.assertEqual(profile['preferred_contact_methods'], [])
        self.assertEqual(len(plan['columns']), 3)
        self.assertEqual(plan['columns'][0]['day'], '2026-09-24')
        self.assertIsNone(plan['columns'][2]['day'])
        self.assertEqual(plan['rows'][0]['assignments'][0]['position'], '7.2')
        self.assertEqual(plan['rows'][0]['assignments'][2]['position'], 'Волонтёр медалей')

    def test_numeric_date_after_title_ending_in_digits(self):
        self.assertEqual(column_day('ММ 2026\n24.09.2026\nВыдача'), '2026-09-24')
        self.assertEqual(column_day('ММ 2026\n25.09\nВыдача'), '2026-09-25')
        self.assertEqual(column_day('ММ\n9ОКТЯБРЯ\nВыдача'), '2026-10-09')

    def test_missing_date_blocks_whole_import_then_creates_all_and_retries_without_duplicates(self):
        plan = self.plan()
        before = User.objects.count()
        with self.assertRaises(ValidationError):
            commit_legacy_base(self.manager, plan)
        self.assertEqual(User.objects.count(), before)
        overrides = {str(plan['columns'][2]['index']): '2026-05-30'}
        commit_legacy_base(self.manager, plan, date_overrides=overrides)
        user = User.objects.get(telegram_username='anna')
        self.assertEqual(user.tshirt_size, 'XL')
        self.assertEqual(user.birthday, date(2000, 6, 1))
        self.assertEqual(user.registration_status, 'registered')
        self.assertEqual(EventGroup.objects.count(), 2)
        self.assertEqual(EventShift.objects.count(), 3)
        self.assertEqual(Participation.objects.filter(user=user, status='attended', hours=0).count(), 3)
        self.assertTrue(all(s.start_time == s.end_time for s in EventShift.objects.all()))
        self.assertEqual(UserComment.objects.filter(target_user=user).count(), 2)
        self.assertEqual(user.total_event_count, 3)
        commit_legacy_base(self.manager, plan, date_overrides=overrides)
        self.assertEqual(EventShift.objects.count(), 3)
        self.assertEqual(Participation.objects.filter(user=user).count(), 3)
        self.assertEqual(UserComment.objects.filter(target_user=user).count(), 2)
        self.assertEqual(User.objects.count(), before + 1)

    def test_existing_profile_is_not_overwritten_and_legacy_id_is_ignored(self):
        user = f.make_user(telegram_username='anna', first_name='Сохранить', motivation='Мои данные')
        commit_legacy_base(self.manager, self.plan(), date_overrides={'24': '2026-05-30'})
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.motivation), ('Сохранить', 'Мои данные'))
        self.assertFalse(User.objects.filter(telegram_id='123').exists())
        self.assertEqual(Participation.objects.filter(user=user).count(), 3)

    def test_bad_size_boolean_missing_birthdate_and_ignored_columns(self):
        values = VALUES.copy()
        values[6], values[14], values[19], values[20] = None, 'нет', 'да', '44'
        profile = self.plan(values=values)['rows'][0]['profile']
        self.assertIsNone(profile['birthday'])
        self.assertFalse(profile['weekday_daytime_available'])
        self.assertTrue(profile['wants_team_lead'])
        self.assertEqual(profile['tshirt_size'], '')

    def test_legacy_comments_visible_to_staff_but_never_owner_or_volunteer(self):
        commit_legacy_base(self.manager, self.plan(), date_overrides={'24': '2026-05-30'})
        user = User.objects.get(telegram_username='anna')
        for viewer in (self.manager, f.make_team_leader()):
            self.client.force_login(viewer)
            self.assertContains(self.client.get(reverse('profile_detail', args=[user.pk])), 'Заметка координатора')
        for viewer in (user, f.make_user()):
            self.client.force_login(viewer)
            self.assertNotContains(self.client.get(reverse('profile_detail', args=[user.pk])), 'Заметка координатора')

    def test_unauthorized_and_conflicting_accounts_leave_database_unchanged(self):
        with self.assertRaises(PermissionDenied):
            commit_legacy_base(f.make_user(), self.plan(), date_overrides={'24': '2026-05-30'})
        f.make_user(telegram_username='anna', phone='+70000000000')
        f.make_user(telegram_username='other', phone='+79991112233')
        with self.assertRaises(ValidationError):
            commit_legacy_base(self.manager, self.plan(), date_overrides={'24': '2026-05-30'})
        self.assertFalse(EventGroup.objects.exists())

    def test_two_shifts_same_day_remain_separate_and_partial_contacts_merge_rows(self):
        headers = HEADERS.copy()
        headers[22], headers[23] = 'БФБ\n23 августа\n1 смена', 'БФБ\n23 августа\n2 смена'
        plan = self.plan(headers=headers)
        second = dict(plan['rows'][0])
        second['profile'] = dict(second['profile'], telegram_username='')
        second['number'] = 3
        plan['rows'].append(second)
        commit_legacy_base(self.manager, plan, date_overrides={'24': '2026-05-30'})
        self.assertEqual(User.objects.filter(phone='+79991112233').count(), 1)
        self.assertEqual(EventShift.objects.filter(day=date(2026, 8, 23)).count(), 2)
        self.assertEqual(Participation.objects.count(), 3)
