"""Заполненность всей анкеты и отсутствие обращений к удалённым колонкам."""
from datetime import date
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from blog.forms import ProfileForm
from . import factories as f


class ProfileCompletionTests(TestCase):
    def test_empty_and_complete_profile_and_no_answer(self):
        from blog.services.profile_completion import profile_completion, PROFILE_SECTIONS
        fields = [name for _, _, names in PROFILE_SECTIONS for name in names]
        self.assertEqual(len(fields), 20)
        self.assertEqual(profile_completion({})['percent'], 0)
        self.assertEqual(profile_completion({name: 'ответ' for name in fields})['percent'], 100)
        result = profile_completion({'wants_team_lead': False, 'weekday_daytime_available': False})
        self.assertEqual(result['filled'], 2)
        self.assertEqual(result['percent'], 10)
        self.assertEqual(profile_completion({'about': '  ', 'wants_team_lead': None})['filled'], 0)

    def test_multiple_contacts_count_as_one_field_without_database_queries(self):
        from blog.services.profile_completion import profile_completion
        with self.assertNumQueries(0):
            result = profile_completion({'preferred_contact_methods': ['telegram', 'vk']})
        self.assertEqual(result['filled'], 1)
        self.assertEqual(result['total'], 20)

    def test_sections_cover_each_form_field_once(self):
        form = ProfileForm()
        names = [field.name for section in form.sections for field in section['fields']]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(form.fields))
        self.assertEqual(len(form.sections), 3)

    def test_bound_form_does_not_count_invalid_answers(self):
        form = ProfileForm(data={'first_name': 'Имя', 'wants_team_lead': 'False',
                                 'weekday_daytime_available': 'maybe', 'motivation': 'а' * 256})
        self.assertEqual(form.completion['filled'], 2)

    def test_profile_pages_use_current_schema_and_show_progress(self):
        user = f.make_user()
        self.client.force_login(user)
        with CaptureQueriesContext(connection) as queries:
            edit = self.client.get(reverse('profile_edit'))
            own = self.client.get(reverse('profile_detail', args=[user.pk]))
            self.client.force_login(f.make_manager())
            managed = self.client.get(reverse('profile_detail', args=[user.pk]))
        self.assertEqual([r.status_code for r in (edit, own, managed)], [200, 200, 200])
        for old in ('faculty', 'education_program', 'admission_year'):
            self.assertFalse(any(f'"users"."{old}"' in q['sql'] for q in queries))
        self.assertContains(edit, 'data-profile-form')
        self.assertContains(edit, 'role="progressbar"')
        self.assertContains(own, 'Заполненность профиля')
        self.assertNotContains(edit, 'data-dp-default-years-ago')
        self.assertContains(edit, 'data-dp-keep-empty')

    def test_old_word_placeholders_are_empty_without_removed_fields(self):
        from blog.services.pgas_certificate import build_replacements
        replacements = build_replacements(f.make_user(), period_label='Период', issue_date=date(2026, 11, 3))
        for key in ('faculty', 'education_program', 'admission_year', 'course', 'graduation_year'):
            self.assertEqual(replacements['{' + key + '}'], '')
