"""Анкета волонтёра: типы ответов, ограничения и сохранение новых полей."""
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from blog.forms import ProfileForm
from blog.models import User
from . import factories as f


TEXT_FIELDS = ('instagram_url', 'volunteer_experience', 'motivation', 'familiar_positions', 'performed_tasks')


class VolunteerProfileTests(TestCase):
    def test_education_fields_are_removed_from_model_and_database(self):
        from django.core.exceptions import FieldDoesNotExist
        from django.db import connection
        with connection.cursor() as cursor:
            columns = {column.name for column in connection.introspection.get_table_description(cursor, User._meta.db_table)}
        for name in ('faculty', 'education_program', 'admission_year'):
            with self.assertRaises(FieldDoesNotExist):
                User._meta.get_field(name)
            self.assertNotIn(name, columns)

    def setUp(self):
        self.user = f.make_user()
        self.data = {'first_name': self.user.first_name, 'telegram_username': self.user.telegram_username,
                     'phone': self.user.phone, 'preferred_contact_methods': ['telegram', 'vk'],
                     'weekday_daytime_available': 'False', 'wants_team_lead': 'True', 'tshirt_size': 'XXXL',
                     **{name: 'Ответ волонтёра' for name in TEXT_FIELDS}}

    def test_profile_fields_and_dropdown_choices(self):
        form = ProfileForm(instance=self.user)
        for old in ('faculty', 'education_program', 'admission_year'):
            self.assertNotIn(old, form.fields)
        self.assertEqual([key for key, _ in form.fields['tshirt_size'].choices if key], ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL'])
        self.assertEqual(list(form.fields['wants_team_lead'].choices)[1:], [('True', 'Да'), ('False', 'Нет')])

    def test_answers_round_trip_without_granting_a_role(self):
        form = ProfileForm(data=self.data, instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.preferred_contact_methods, ['telegram', 'vk'])
        self.assertIs(self.user.weekday_daytime_available, False)
        self.assertIs(self.user.wants_team_lead, True)
        self.assertEqual(self.user.tshirt_size, 'XXXL')
        self.assertFalse(self.user.team_leader_roles.exists())
        for name in TEXT_FIELDS:
            self.assertEqual(getattr(self.user, name), 'Ответ волонтёра')

    def test_contact_requires_one_known_option_and_allows_multiple(self):
        for selected in ([], ['unknown']):
            form = ProfileForm(data={**self.data, 'preferred_contact_methods': selected}, instance=self.user)
            self.assertFalse(form.is_valid())
            self.assertIn('preferred_contact_methods', form.errors)
        choices = [key for key, _ in User.CONTACT_METHOD_CHOICES]
        self.assertEqual(len(choices), 9)
        form = ProfileForm(data={**self.data, 'preferred_contact_methods': choices}, instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_text_limits_accept_255_and_reject_256(self):
        for name in TEXT_FIELDS:
            with self.subTest(name=name):
                form = ProfileForm(data={**self.data, name: 'а' * 255}, instance=self.user)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.fields[name].widget.attrs['data-counter-mode'], 'limit')
                form = ProfileForm(data={**self.data, name: 'а' * 256}, instance=self.user)
                self.assertFalse(form.is_valid())
                self.assertIn(name, form.errors)

    def test_invalid_choices_and_unanswered_boolean_are_distinct_from_no(self):
        for name, value in (('wants_team_lead', 'maybe'), ('weekday_daytime_available', 'maybe'), ('tshirt_size', 'XXXXL')):
            form = ProfileForm(data={**self.data, name: value}, instance=self.user)
            self.assertFalse(form.is_valid())
            self.assertIn(name, form.errors)
        form = ProfileForm(data={**self.data, 'wants_team_lead': '', 'weekday_daytime_available': ''}, instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['wants_team_lead'])
        self.assertIsNone(form.cleaned_data['weekday_daytime_available'])

    def test_profile_ui_guide_and_owner_manager_display(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('profile_edit'))
        self.assertContains(response, 'name="preferred_contact_methods"', count=9)
        self.assertContains(response, '158–166 см')
        self.assertContains(response, '108–112 см')
        self.assertNotContains(response, 'name="faculty"')
        response = self.client.post(reverse('profile_edit'), self.data)
        self.assertEqual(response.status_code, 302)
        for viewer in (self.user, f.make_manager()):
            self.client.force_login(viewer)
            response = self.client.get(reverse('profile_detail', args=[self.user.pk]))
            self.assertContains(response, 'Ответ волонтёра')
            self.assertContains(response, 'XXXL')
            self.assertContains(response, 'Телеграм')
            self.assertNotContains(response, 'Факультет:')
        response = self.client.get(reverse('public_experience', args=[self.user.experience_token]))
        self.assertNotContains(response, 'Ответ волонтёра')

    def test_contact_model_validation_rejects_wrong_shape_and_unknown_values(self):
        field = User._meta.get_field('preferred_contact_methods')
        for value in ('telegram', ['unknown'], {'telegram': True}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                field.clean(value, self.user)
