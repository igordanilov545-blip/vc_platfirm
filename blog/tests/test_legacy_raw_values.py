"""Импорт сохраняет свободный текст, пропускает строгие типы и не склеивает unnamed."""
from copy import deepcopy
from django.test import TestCase
from django.urls import reverse
from blog.forms import ProfileForm
from blog.models import User
from blog.services import legacy_migration as lm
from blog.services.legacy_workbook import read_legacy_workbook
from . import factories as f
from .test_legacy_base import HEADERS, VALUES, workbook, rows_workbook


class LegacyRawValuesTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()

    def values(self):
        values = VALUES.copy()
        values[3], values[4] = None, 'Иванова'
        values[9], values[10], values[11] = 'нет телеграма', 'спросить лично', 'javascript:alert(1)'
        return values

    def plan(self):
        return read_legacy_workbook(workbook(values=self.values()))

    def load(self, *rows):
        """Новый поток: база → люди (legacy_migration)."""
        base = lm.upload_base(self.manager, rows_workbook(HEADERS, rows), 'base.xlsx', 2026)
        lm.load_people(self.manager, base)
        return base

    def test_unrecognized_social_text_and_missing_names_are_preserved_without_warnings(self):
        plan = self.plan()
        row = plan['rows'][0]['profile']
        self.assertEqual((row['first_name'], row['last_name']), ('unnamed', 'Иванова'))
        self.assertEqual((row['telegram_username'], row['VK_username'], row['instagram_url']),
                         ('нет телеграма', 'спросить лично', 'javascript:alert(1)'))
        self.assertFalse(plan['errors'])
        self.assertFalse(plan['warnings'])

    def test_invalid_strict_fields_are_blank_and_phone_text_is_preserved(self):
        values = VALUES.copy()
        values[6], values[7], values[8] = 'неизвестно', 'без почты', 'номер у координатора'
        values[14], values[19], values[20] = 'не знаю', 'да или нет', '44'
        plan = read_legacy_workbook(workbook(values=values))
        profile = plan['rows'][0]['profile']
        self.assertIsNone(profile['birthday'])
        self.assertEqual(profile['email'], '')
        self.assertEqual(profile['phone'], 'номер у координатора')
        self.assertIsNone(profile['weekday_daytime_available'])
        self.assertIsNone(profile['wants_team_lead'])
        self.assertEqual(profile['tshirt_size'], '')
        self.assertFalse(plan['errors'])
        self.assertFalse(plan['warnings'])

    def test_import_and_profile_keep_raw_text_without_unsafe_links(self):
        self.load(self.values())
        user = User.objects.get(first_name='unnamed')
        self.assertEqual((user.telegram_username, user.VK_username, user.instagram_url),
                         ('нет телеграма', 'спросить лично', 'javascript:alert(1)'))
        self.assertEqual(user.vk_profile_url, '')
        self.assertEqual(user.instagram_profile_url, '')
        self.client.force_login(self.manager)
        response = self.client.get(reverse('profile_detail', args=[user.pk]))
        self.assertContains(response, 'спросить лично')
        self.assertContains(response, 'javascript:alert(1)')
        self.assertNotContains(response, 'href="javascript:')

    def test_unnamed_rows_without_recognizable_contacts_stay_distinct_on_retry(self):
        row = self.values()
        row[6], row[7], row[8] = None, '', ''
        base = self.load(row, row.copy())
        lm.load_people(self.manager, base)
        self.assertEqual(User.objects.filter(first_name='unnamed').count(), 2)

    def test_free_text_is_not_used_to_match_an_existing_account(self):
        existing = f.make_user(telegram_username='нет телеграма', phone='номер у координатора')
        row = self.values()
        row[7], row[8] = '', 'номер у координатора'
        self.load(row)
        self.assertEqual(User.objects.filter(first_name='unnamed').count(), 1)
        self.assertFalse(existing.legacy_base_rows.exists())

    def test_profile_form_does_not_erase_imported_free_text(self):
        user = f.make_user(VK_username='пока не знаю', instagram_url='не пользуюсь')
        form = ProfileForm(data={'first_name': 'Анна', 'telegram_username': 'anna', 'phone': '+79991112233',
                                 'VK_username': user.VK_username, 'instagram_url': user.instagram_url,
                                 'preferred_contact_methods': ['telegram']}, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual((saved.VK_username, saved.instagram_url), ('пока не знаю', 'не пользуюсь'))

    def test_punctuation_and_zero_placeholders_do_not_identify_a_person(self):
        existing = f.make_user(telegram_username='---', phone='0')
        row = self.values()
        row[9], row[8], row[7], row[6] = '---', '0', '', None
        self.load(row, row.copy())
        self.assertFalse(existing.legacy_base_rows.exists())
        self.assertEqual(User.objects.filter(first_name='unnamed').count(), 2)
