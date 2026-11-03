"""Импорт сохраняет свободный текст, пропускает строгие типы и не склеивает unnamed."""
from copy import deepcopy
from django.test import TestCase
from django.urls import reverse
from blog.forms import ProfileForm
from blog.models import User, Participation
from blog.services.legacy_import import commit_legacy_base
from blog.services.legacy_workbook import read_legacy_workbook
from blog.services.roster_exports import build_roster_workbook
from . import factories as f
from .test_legacy_base import VALUES, workbook


class LegacyRawValuesTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()

    def plan(self):
        values = VALUES.copy()
        values[3], values[4] = None, 'Иванова'
        values[9], values[10], values[11] = 'нет телеграма', 'спросить лично', 'javascript:alert(1)'
        return read_legacy_workbook(workbook(values=values))

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

    def test_import_and_profile_and_excel_keep_raw_text_without_unsafe_links(self):
        plan = self.plan()
        commit_legacy_base(self.manager, plan, date_overrides={'24': '2026-05-30'})
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
        group = user.participations.first().event_day.event.event_group
        wb = build_roster_workbook(self.manager, group=group)
        self.assertEqual(wb['Участники'].cell(2, 8).value, 'спросить лично')
        self.assertEqual(wb['Участники'].cell(2, 9).value, 'javascript:alert(1)')

    def test_unnamed_rows_without_recognizable_contacts_stay_distinct_on_retry(self):
        plan = self.plan()
        row = plan['rows'][0]
        row['profile']['phone'] = ''
        row['profile']['email'] = ''
        row['profile']['birthday'] = None
        other = deepcopy(row)
        other['number'] = row['number'] + 1
        plan['rows'].append(other)
        for _ in range(2):
            commit_legacy_base(self.manager, plan, date_overrides={'24': '2026-05-30'})
        self.assertEqual(User.objects.filter(first_name='unnamed').count(), 2)
        self.assertEqual(Participation.objects.count(), 6)

    def test_free_text_is_not_used_to_match_an_existing_account(self):
        existing = f.make_user(telegram_username='нет телеграма', phone='номер у координатора')
        plan = self.plan()
        plan['rows'][0]['profile'].update(phone='номер у координатора', email='')
        commit_legacy_base(self.manager, plan, date_overrides={'24': '2026-05-30'})
        self.assertFalse(Participation.objects.filter(user=existing).exists())
        self.assertEqual(User.objects.filter(first_name='unnamed').count(), 1)

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
        plan = self.plan()
        row = plan['rows'][0]
        row['profile'].update(telegram_username='---', phone='0', email='', birthday=None)
        other = deepcopy(row)
        other['number'] += 1
        plan['rows'].append(other)
        commit_legacy_base(self.manager, plan, date_overrides={'24': '2026-05-30'})
        self.assertFalse(Participation.objects.filter(user=existing).exists())
        self.assertEqual(User.objects.filter(first_name='unnamed').count(), 2)
