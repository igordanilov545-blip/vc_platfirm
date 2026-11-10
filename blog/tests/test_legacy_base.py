"""Легаси База: анкета, все колонки, идемпотентность и приватность комментариев."""
from datetime import date, datetime
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook
from blog.models import EventGroup, User, UserComment
from blog.services.legacy_workbook import read_legacy_workbook, column_day, phone_key
from blog.services import legacy_migration as lm
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


def without_sheet_dimensions(content):
    """XLSX, у которого экспортёр не записал необязательный XML dimension."""
    output = BytesIO()
    with ZipFile(BytesIO(content)) as original, ZipFile(output, 'w') as changed:
        for entry in original.infolist():
            data = original.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                sheet = ET.fromstring(data)
                dimension = sheet.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}dimension')
                if dimension is not None:
                    sheet.remove(dimension)
                data = ET.tostring(sheet, encoding='utf-8')
            changed.writestr(entry, data)
    return output.getvalue()


class LegacyBaseTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()

    def plan(self, headers=None, values=None):
        return read_legacy_workbook(workbook(headers, values))

    def test_workbook_without_dimensions_reads_all_profile_and_event_cells(self):
        normal = self.plan()
        unsized = read_legacy_workbook(without_sheet_dimensions(workbook()))
        self.assertEqual(unsized, normal)

    def test_unsized_sheet_keeps_column_limit_for_header_and_data(self):
        for wide_header in (True, False):
            with self.subTest(wide_header=wide_header):
                headers = HEADERS + ['Лишняя'] * (513 - len(HEADERS)) if wide_header else HEADERS
                values = VALUES + ['Значение'] * (513 - len(VALUES))
                content = without_sheet_dimensions(workbook(headers, values))
                with self.assertRaisesMessage(ValidationError, '512'):
                    read_legacy_workbook(content)

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

    def load(self, *value_rows, headers=None):
        """Новый поток (legacy_migration): база → люди. Мероприятия грузятся отдельно."""
        content = rows_workbook(headers or HEADERS, value_rows or [VALUES])
        base = lm.upload_base(self.manager, content, 'base.xlsx', 2026)
        lm.load_people(self.manager, base)
        return base

    def test_people_stage_creates_profile_comments_and_retries_without_duplicates(self):
        before = User.objects.count()
        base = self.load(VALUES)
        user = User.objects.get(telegram_username='anna')
        self.assertEqual(user.tshirt_size, 'XL')
        self.assertEqual(user.birthday, date(2000, 6, 1))
        self.assertEqual(user.registration_status, 'registered')
        self.assertEqual(UserComment.objects.filter(target_user=user).count(), 2)
        self.assertFalse(EventGroup.objects.exists())
        self.assertEqual(base.columns.count(), 3)
        lm.load_people(self.manager, base)
        self.assertEqual(UserComment.objects.filter(target_user=user).count(), 2)
        self.assertEqual(User.objects.count(), before + 1)

    def test_existing_profile_is_not_overwritten_and_legacy_id_is_ignored(self):
        user = f.make_user(telegram_username='anna', first_name='Сохранить', motivation='Мои данные')
        self.load(VALUES)
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.motivation), ('Сохранить', 'Мои данные'))
        self.assertFalse(User.objects.filter(telegram_id='123').exists())

    def test_bad_size_boolean_missing_birthdate_and_ignored_columns(self):
        values = VALUES.copy()
        values[6], values[14], values[19], values[20] = None, 'нет', 'да', '44'
        profile = self.plan(values=values)['rows'][0]['profile']
        self.assertIsNone(profile['birthday'])
        self.assertFalse(profile['weekday_daytime_available'])
        self.assertTrue(profile['wants_team_lead'])
        self.assertEqual(profile['tshirt_size'], '')

    def test_legacy_comments_visible_to_staff_but_never_owner_or_volunteer(self):
        self.load(VALUES)
        user = User.objects.get(telegram_username='anna')
        for viewer in (self.manager, f.make_team_leader()):
            self.client.force_login(viewer)
            self.assertContains(self.client.get(reverse('profile_detail', args=[user.pk])), 'Заметка координатора')
        for viewer in (user, f.make_user()):
            self.client.force_login(viewer)
            self.assertNotContains(self.client.get(reverse('profile_detail', args=[user.pk])), 'Заметка координатора')

    def test_unauthorized_and_conflicting_accounts_leave_database_unchanged(self):
        with self.assertRaises(PermissionDenied):
            lm.upload_base(f.make_user(), workbook(), 'base.xlsx', 2026)
        f.make_user(telegram_username='anna', phone='+70000000000')
        f.make_user(telegram_username='other', phone='+79991112233')
        base = lm.upload_base(self.manager, workbook(), 'base.xlsx', 2026)
        before = User.objects.count()
        with self.assertRaises(ValidationError):
            lm.load_people(self.manager, base)
        self.assertEqual(User.objects.count(), before)

    def test_partial_contacts_merge_rows_into_one_person(self):
        second = VALUES.copy()
        second[9] = ''
        self.load(VALUES, second)
        self.assertEqual(User.objects.filter(phone='+79991112233').count(), 1)


def rows_workbook(headers, rows, sheet='База'):
    wb = Workbook()
    wb.active.title = sheet
    wb.active.append(headers)
    for row in rows:
        wb.active.append(row)
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
