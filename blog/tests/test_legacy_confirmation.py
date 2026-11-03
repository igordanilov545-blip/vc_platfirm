"""Большой предпросмотр подтверждается; пустое ФИО исключено, неизвестные даты временные."""
from copy import deepcopy
from datetime import date
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from blog.models import User, EventShift, Participation
from blog.services.legacy_import import commit_legacy_base, preview_context
from blog.services.legacy_workbook import read_legacy_workbook
from . import factories as f
from .test_legacy_base import workbook, VALUES


class LegacyConfirmationTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.url = reverse('legacy_base_upload')

    def test_missing_both_names_skips_whole_row_and_its_assignments(self):
        values = VALUES.copy()
        values[3], values[4] = None, ' '
        plan = read_legacy_workbook(workbook(values=values))
        self.assertEqual(plan['rows'], [])
        self.assertEqual(plan['skipped_rows'], 1)
        self.assertTrue(all(column['used'] == 0 for column in plan['columns']))

    def test_one_missing_name_still_imports_with_unnamed(self):
        for name_index in (3, 4):
            values = VALUES.copy()
            values[name_index] = None
            plan = read_legacy_workbook(workbook(values=values))
            self.assertEqual(len(plan['rows']), 1)
            field = 'first_name' if name_index == 3 else 'last_name'
            self.assertEqual(plan['rows'][0]['profile'][field], 'unnamed')

    def test_existing_preview_filters_double_unnamed_and_defaults_dates(self):
        plan = read_legacy_workbook(workbook())
        empty = deepcopy(plan['rows'][0])
        empty['number'] += 1
        empty['profile'].update(first_name='unnamed', last_name='unnamed')
        plan['rows'].append(empty)
        context = preview_context(self.manager, plan)
        self.assertEqual(len(context['people']), 1)
        self.assertEqual(context['plan']['skipped_rows'], 1)
        unknown = context['columns'][2]
        self.assertEqual(unknown['day'], '2026-01-01')
        self.assertTrue(unknown['date_placeholder'])
        self.assertTrue(context['can_commit'])

    def test_confirmation_with_no_date_overrides_imports_and_preserves_manual_date(self):
        self.client.post(self.url, {'workbook': SimpleUploadedFile('base.xlsx', workbook())})
        preview = self.client.session['legacy_base_preview']
        response = self.client.post(self.url, {'action': 'commit', 'preview_id': preview['id']})
        self.assertContains(response, 'База загружена')
        self.assertEqual(Participation.objects.count(), 3)
        shift = EventShift.objects.get(day=date(2026, 1, 1))
        self.assertTrue(shift.date_unknown)
        shift.day = date(2026, 5, 30)
        shift.save(update_fields=['day'])
        commit_legacy_base(self.manager, read_legacy_workbook(workbook()))
        shift.refresh_from_db()
        self.assertEqual(shift.day, date(2026, 5, 30))
        self.assertEqual(Participation.objects.count(), 3)

    def test_date_errors_are_visible_above_people_and_keep_correct_dates(self):
        self.client.post(self.url, {'workbook': SimpleUploadedFile('base.xlsx', workbook())})
        preview = self.client.session['legacy_base_preview']
        before = User.objects.count()
        response = self.client.post(self.url, {'action': 'commit', 'preview_id': preview['id'],
                                               'date_22': 'bad-date', 'date_23': '2026-09-26'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Загрузка не началась')
        self.assertContains(response, '#legacy-date-22')
        self.assertEqual(response.context['columns'][1]['day'], '2026-09-26')
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(Participation.objects.exists())

    def test_large_preview_is_compact_but_retains_all_rows(self):
        plan = read_legacy_workbook(workbook())
        plan['rows'] = [dict(deepcopy(plan['rows'][0]), number=index + 2) for index in range(3484)]
        context = preview_context(self.manager, plan)
        self.assertEqual(len(context['people']), 3484)
        self.assertLessEqual(len(context['preview_people']), 50)
