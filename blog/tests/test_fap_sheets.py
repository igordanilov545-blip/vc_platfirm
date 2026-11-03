"""FaP: читаем только «Смены», сохраняем дни/нули, импортируем без дублей."""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from django.test import TestCase, SimpleTestCase
from django.core.exceptions import ValidationError
from openpyxl import Workbook, load_workbook

from . import factories as f
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from unittest.mock import patch


EXAMPLES = Path(__file__).resolve().parents[1] / 'resources' / 'fap'


class FaPWorkbookTests(SimpleTestCase):
    def test_other_sheet_xml_is_not_parsed(self):
        from zipfile import ZipFile
        from blog.services.fap_workbook import read_xlsx
        book = load_workbook(EXAMPLES / 'one-day.xlsx')
        book.create_sheet('Чужой лист')['A1'] = 'Не читать'
        stream = BytesIO()
        book.save(stream)
        broken = BytesIO()
        with ZipFile(BytesIO(stream.getvalue())) as source, ZipFile(broken, 'w') as target:
            for item in source.infolist():
                target.writestr(item, b'not xml' if item.filename == 'xl/worksheets/sheet2.xml' else source.read(item.filename))
        self.assertEqual(len(read_xlsx(broken.getvalue())['directions']), 4)
    def test_both_examples_have_variable_days_and_directions(self):
        from blog.services.fap_workbook import read_xlsx
        for name, days, positions in [('three-days.xlsx', 3, 14), ('one-day.xlsx', 1, 13)]:
            with self.subTest(name=name):
                plan = read_xlsx((EXAMPLES / name).read_bytes())
                self.assertEqual(len(plan['dates']), days)
                self.assertEqual(len(plan['directions']), 4)
                self.assertEqual(sum(len(d['positions']) for d in plan['directions']), positions)
                self.assertFalse(any('ИТОГО' in p['name'] for d in plan['directions'] for p in d['positions']))

    def test_zero_blank_and_incomplete_time_are_not_lost(self):
        from blog.services.fap_workbook import read_xlsx
        plan = read_xlsx((EXAMPLES / 'three-days.xlsx').read_bytes())
        positions = plan['directions'][0]['positions']
        self.assertEqual(positions[1]['days'][0]['shifts'][0]['count'], 0)
        self.assertIsNone(positions[4]['days'][0]['work'])
        self.assertEqual(positions[4]['days'][0]['quantities'][0]['count'], 0)
        self.assertTrue(plan['warnings'])

    def test_only_shifts_sheet_is_exported_and_styles_are_preserved(self):
        from blog.services.fap_workbook import read_xlsx, write_xlsx
        source = (EXAMPLES / 'one-day.xlsx').read_bytes()
        plan = read_xlsx(source)
        exported = write_xlsx(plan, source)
        original, result = load_workbook(BytesIO(source)), load_workbook(BytesIO(exported))
        self.assertEqual(result.sheetnames, ['Смены'])
        a, b = original['Смены'], result['Смены']
        self.assertEqual(str(a.merged_cells), str(b.merged_cells))
        for row in a:
            for cell in row:
                other = b.cell(cell.row, cell.column)
                self.assertEqual(cell._style, other._style)
        self.assertEqual(a.freeze_panes, b.freeze_panes)
        self.assertEqual(read_xlsx(exported)['dates'], plan['dates'])

    def test_missing_shifts_sheet_is_rejected(self):
        from blog.services.fap_workbook import read_xlsx
        stream = BytesIO()
        Workbook().save(stream)
        with self.assertRaises(ValidationError):
            read_xlsx(stream.getvalue())

    def test_generated_two_seven_and_thirty_one_days_round_trip(self):
        from blog.services.fap_workbook import read_xlsx, write_xlsx, new_id, day_shifts
        from copy import deepcopy
        template = (EXAMPLES / 'one-day.xlsx').read_bytes()
        for days in (2, 7, 31):
            plan = read_xlsx(template)
            plan['dates'] = [(date(2026, 11, 1) + timedelta(days=i)).isoformat() for i in range(days)]
            plan['quantity_widths'] = [3] * days
            for direction in plan['directions']:
                for position in direction['positions']:
                    original = position['days'][0]
                    position['days'] = []
                    for day in plan['dates']:
                        item = deepcopy(original)
                        item['date'] = day
                        item['shifts'] = day_shifts(day, item['work'], item['checkin_out'], item['quantities'], [])
                        position['days'].append(item)
            result = read_xlsx(write_xlsx(plan, template))
            self.assertEqual(result['dates'], plan['dates'])
            self.assertEqual(sum(len(d['positions']) for d in result['directions']), 13)

    def test_three_subshifts_keep_separate_times_and_counts(self):
        from blog.services.fap_workbook import day_shifts
        result = day_shifts('2026-11-01', 'A: 08:00-10:00\nB: 10:00-12:00\nC: 12:00-14:00', None,
            [{'label': '', 'count': 6}, {'label': 'A', 'count': 1}, {'label': 'B', 'count': 2}, {'label': 'C', 'count': 3}], [])
        self.assertEqual([r['count'] for r in result], [1, 2, 3])
        self.assertEqual([r['label'] for r in result], ['A', 'B', 'C'])

    def test_partial_vertical_staff_merges_are_inherited_only_by_their_positions(self):
        from blog.services.fap_workbook import read_xlsx
        book = load_workbook(EXAMPLES / 'one-day.xlsx')
        sheet = book['Смены']
        sheet.unmerge_cells('C3:C7')
        sheet.merge_cells('C3:C4')
        sheet['C3'] = 'Первый лидер'
        sheet.merge_cells('C5:C6')
        sheet['C5'] = 'Второй лидер'
        stream = BytesIO()
        book.save(stream)
        direction = read_xlsx(stream.getvalue())['directions'][0]
        self.assertEqual(direction['team_leaders'], [])
        self.assertEqual([p['team_leaders'] for p in direction['positions']], [['Первый лидер'], ['Первый лидер'], ['Второй лидер'], ['Второй лидер']])

    def test_google_grid_and_batch_keep_stable_ids_and_values(self):
        from blog.services.fap_workbook import read_xlsx, write_xlsx
        from blog.services.google_sheets import xlsx_update_requests, grid_to_xlsx
        from blog.services.event_sheets import fingerprint
        template = (EXAMPLES / 'one-day.xlsx').read_bytes()
        plan = read_xlsx(template)
        exported = write_xlsx(plan, template)
        batch = xlsx_update_requests(exported, 42)
        updates = next(r['updateCells'] for r in batch if r.get('updateCells', {}).get('rows'))
        metadata = [dict(r['createDeveloperMetadata']['developerMetadata'], metadataId=i) for i, r in enumerate(batch) if 'createDeveloperMetadata' in r]
        payload = {'sheets': [{'properties': {'sheetId': 42, 'title': 'Смены'}, 'data': [{'rowData': updates['rows']}],
            'merges': [r['mergeCells']['range'] for r in batch if 'mergeCells' in r], 'developerMetadata': metadata}]}
        content, gid = grid_to_xlsx(payload)
        self.assertEqual(gid, 42)
        self.assertEqual(fingerprint(read_xlsx(content)), fingerprint(plan))
        self.assertFalse(any('addSheet' in item for item in batch))

    def test_google_metadata_budget_keeps_full_ids_in_notes(self):
        from blog.services.fap_workbook import read_xlsx, write_xlsx, META_PREFIX
        from blog.services.google_sheets import xlsx_update_requests
        template = (EXAMPLES / 'one-day.xlsx').read_bytes()
        exported = write_xlsx(read_xlsx(template), template)
        original = {'sheets': [{'properties': {'sheetId': 42, 'title': 'Смены'}, 'developerMetadata': [{'metadataKey': 'other', 'metadataValue': 'x' * 29990}]}]}
        batch = xlsx_update_requests(exported, 42, original)
        self.assertFalse(any('createDeveloperMetadata' in item for item in batch))
        rows = next(item['updateCells']['rows'] for item in batch if item.get('updateCells', {}).get('rows'))
        self.assertEqual(sum(META_PREFIX in cell.get('note', '') for row in rows for cell in row['values']), 13)

    def test_named_shift_ids_follow_labels_after_reordering(self):
        from blog.services.fap_workbook import day_shifts
        quantities = [{'label': '', 'count': 3}, {'label': 'A', 'count': 1}, {'label': 'B', 'count': 2}]
        old = day_shifts('2026-11-01', 'A: 08:00-10:00\nB: 10:00-12:00', None, quantities, [])
        new = day_shifts('2026-11-01', 'B: 10:00-12:00\nA: 08:00-10:00', None, quantities, [], old)
        self.assertEqual([s['id'] for s in new], [old[1]['id'], old[0]['id']])


class FaPImportTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()

    def test_import_creates_positions_shifts_and_separate_zone_responsibles(self):
        from blog.services.event_sheets import import_workbook
        from blog.models import EventGroup, ZoneResponsible, Manager
        group = EventGroup.objects.create(title='FaP')
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes(), 'пример.xlsx')
        self.assertEqual(group.positions.count(), 13)
        self.assertEqual(sum(p.shifts.count() for p in group.positions.all()), 13)
        self.assertEqual(ZoneResponsible.objects.filter(direction__event_group=group).count(), 4)
        self.assertEqual(Manager.objects.count(), 1)
        link = group.sheet_link
        self.assertTrue(link.warnings == [] or isinstance(link.warnings, list))
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes(), 'пример.xlsx')
        self.assertEqual(group.positions.count(), 13)

    def test_non_manager_cannot_import(self):
        from blog.services.event_sheets import import_workbook
        from blog.models import EventGroup
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            import_workbook(f.make_user(), EventGroup.objects.create(title='FaP'), b'', 'file.xlsx')

    def test_current_plan_matches_import_and_round_trip_has_no_duplicates(self):
        from blog.services.event_sheets import import_workbook, export_workbook, current_plan, fingerprint
        from blog.models import EventGroup
        group = EventGroup.objects.create(title='FaP')
        link = import_workbook(self.manager, group, (EXAMPLES / 'three-days.xlsx').read_bytes())
        self.assertEqual(fingerprint(link.baseline), fingerprint(current_plan(group)))
        exported = export_workbook(self.manager, group)
        import_workbook(self.manager, group, exported)
        self.assertEqual(group.positions.count(), 14)

    def test_incoming_old_plan_does_not_erase_local_edit(self):
        from blog.services.event_sheets import import_workbook, export_workbook
        from blog.models import EventGroup
        group = EventGroup.objects.create(title='FaP')
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes())
        old = export_workbook(self.manager, group)
        event = group.positions.first()
        event.title = 'Изменено в системе'
        event.save(update_fields=['title'])
        with self.assertRaises(ValidationError):
            import_workbook(self.manager, group, old)
        event.refresh_from_db()
        self.assertEqual(event.title, 'Изменено в системе')

    def test_google_url_is_restricted_and_private_key_is_encrypted(self):
        from blog.services.google_sheets import parse_sheet_url, encrypt_key, decrypt_key
        self.assertEqual(parse_sheet_url('https://docs.google.com/spreadsheets/d/' + 'a' * 32 + '/edit#gid=123'), ('a' * 32, 123))
        with self.assertRaises(ValidationError):
            parse_sheet_url('https://127.0.0.1/private')
        data = {'private_key': 'private-secret'}
        encrypted = encrypt_key(data)
        self.assertNotIn('private-secret', encrypted)
        self.assertEqual(decrypt_key(encrypted), data)

    def test_create_event_with_workbook_via_interface(self):
        from blog.models import EventGroup
        self.client.force_login(self.manager)
        upload = SimpleUploadedFile('plan.xlsx', (EXAMPLES / 'one-day.xlsx').read_bytes())
        response = self.client.post(reverse('event_group_create'), {'title': 'Из таблицы', 'managers': [self.manager.pk], 'workbook': upload})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(EventGroup.objects.get(title='Из таблицы').positions.count(), 13)

    def test_sheet_management_is_manager_only_and_url_is_shared_by_positions(self):
        from blog.models import EventGroup, EventSheetLink
        group = EventGroup.objects.create(title='Общая таблица')
        link = EventSheetLink.objects.create(event_group=group, spreadsheet_id='a' * 32)
        self.client.force_login(f.make_user())
        self.assertEqual(self.client.get(reverse('event_sheet', args=[group.pk])).status_code, 403)
        response = self.client.get(reverse('event_group_detail', args=[group.pk]))
        self.assertContains(response, link.google_url)

    def test_binding_unknown_name_assigns_existing_leader_without_manager_role(self):
        from blog.services.event_sheets import import_workbook, bind_team_leader
        from blog.models import EventGroup, SheetTeamLeader, EventStaff, Manager
        group = EventGroup.objects.create(title='Лидеры')
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes())
        assignment = SheetTeamLeader.objects.filter(direction__event_group=group).first()
        user = f.make_team_leader()
        bind_team_leader(self.manager, assignment.pk, user)
        self.assertEqual(EventStaff.objects.filter(user=user, staff_role='team_lead').count(), 4)
        self.assertEqual(Manager.objects.count(), 1)

    def test_rebinding_removes_only_import_owned_staff(self):
        from blog.services.event_sheets import import_workbook, bind_team_leader
        from blog.models import EventGroup, SheetTeamLeader, EventStaff
        group = EventGroup.objects.create(title='Смена лидера')
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes())
        assignment = SheetTeamLeader.objects.filter(direction__event_group=group).first()
        old, new = f.make_team_leader(), f.make_team_leader()
        manual_event = assignment.direction.positions.first().event
        EventStaff.objects.create(event=manual_event, user=old, staff_role='team_lead')
        bind_team_leader(self.manager, assignment.pk, old)
        bind_team_leader(self.manager, assignment.pk, new)
        self.assertEqual(EventStaff.objects.filter(user=old, staff_role='team_lead').count(), 1)
        self.assertEqual(EventStaff.objects.filter(user=new, staff_role='team_lead').count(), 4)

    def test_google_push_preserves_local_changes_and_writes_only_on_explicit_action(self):
        from blog.services.event_sheets import import_workbook, export_workbook, push_google
        from blog.models import EventGroup
        group = EventGroup.objects.create(title='Google')
        link = import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes())
        remote = export_workbook(self.manager, group)
        link.spreadsheet_id = 'a' * 32
        link.save(update_fields=['spreadsheet_id'])
        event = group.positions.first()
        event.title = 'Локальное название'
        event.save(update_fields=['title'])
        with patch('blog.services.google_sheets.GoogleSheetClient') as factory:
            client = factory.return_value
            client.read_google.return_value = (remote, 42)
            push_google(self.manager, group)
            client.write_google.assert_called_once()
            written = client.write_google.call_args.args[2]
        from blog.services.fap_workbook import read_xlsx
        self.assertIn('Локальное название', [p['name'] for d in read_xlsx(written)['directions'] for p in d['positions']])

    def test_google_conflict_does_not_write_or_replace_local_data(self):
        from blog.services.event_sheets import import_workbook, export_workbook, push_google
        from blog.models import EventGroup
        group = EventGroup.objects.create(title='Конфликт')
        link = import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes())
        book = load_workbook(BytesIO(export_workbook(self.manager, group)))
        book['Смены']['E3'] = 'Правка Google'
        remote = BytesIO()
        book.save(remote)
        link.spreadsheet_id = 'a' * 32
        link.save(update_fields=['spreadsheet_id'])
        event = group.positions.first()
        event.title = 'Правка системы'
        event.save(update_fields=['title'])
        with patch('blog.services.google_sheets.GoogleSheetClient') as factory:
            factory.return_value.read_google.return_value = (remote.getvalue(), 42)
            with self.assertRaises(ValidationError):
                push_google(self.manager, group)
            factory.return_value.write_google.assert_not_called()
        event.refresh_from_db()
        self.assertEqual(event.title, 'Правка системы')
