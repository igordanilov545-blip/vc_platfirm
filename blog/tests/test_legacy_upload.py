"""Загрузка базы через UI: предпросмотр без записи, даты и явный атомарный импорт."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from blog.models import User, EventGroup
from . import factories as f
from .test_legacy_base import workbook, without_sheet_dimensions


class LegacyUploadTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.url = reverse('legacy_base_upload')

    def test_file_without_dimension_opens_preview_without_database_changes(self):
        before = User.objects.count()
        upload = SimpleUploadedFile('base.xlsx', without_sheet_dimensions(workbook()))
        response = self.client.post(self.url, {'workbook': upload})
        self.assertContains(response, 'Предпросмотр')
        self.assertContains(response, '7.2')
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(EventGroup.objects.exists())

    def test_preview_date_confirmation_and_single_commit(self):
        count = User.objects.count()
        response = self.client.post(self.url, {'workbook': SimpleUploadedFile('base.xlsx', workbook())})
        self.assertContains(response, '7.2')
        self.assertContains(response, 'Зелёный марафон')
        self.assertEqual(User.objects.count(), count)
        self.assertFalse(EventGroup.objects.exists())
        preview = self.client.session['legacy_base_preview']
        values = {'action': 'commit', 'preview_id': preview['id'],
                  'date_22': '2026-09-24', 'date_23': '2026-09-25', 'date_24': '2026-05-30'}
        response = self.client.post(self.url, values)
        self.assertContains(response, 'База загружена')
        self.assertEqual(User.objects.count(), count + 1)
        self.assertNotIn('legacy_base_preview', self.client.session)
        self.assertEqual(self.client.post(self.url, values).status_code, 400)

    def test_invalid_workbook_no_mutation_and_access_csrf(self):
        response = self.client.post(self.url, {'workbook': SimpleUploadedFile('bad.xlsx', b'broken')})
        self.assertContains(response, 'Не удалось прочитать')
        self.assertFalse(EventGroup.objects.exists())
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.manager)
        self.assertEqual(csrf.post(self.url, {}).status_code, 403)
        self.client.force_login(f.make_team_leader())
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_settings_button_next_to_invitations(self):
        response = self.client.get(reverse('settings'))
        self.assertContains(response, self.url)
        self.assertContains(response, 'Загрузка базы')
