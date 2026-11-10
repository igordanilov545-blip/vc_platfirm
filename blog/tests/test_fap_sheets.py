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
from copy import copy


EXAMPLES = Path(__file__).resolve().parents[1] / 'resources' / 'fap'


class FaPWorkbookTests(SimpleTestCase):
    def test_vip_zone_has_one_shift_per_day_with_subtotal_and_check_bounds(self):
        from blog.services.fap_workbook import read_xlsx
        plan = read_xlsx((EXAMPLES / 'marathon.xlsx').read_bytes())
        days = plan['directions'][0]['positions'][0]['days']
        shifts = [s for day in days for s in day['shifts']]
        self.assertEqual([(s['start'], s['end'], s['count']) for s in shifts], [
            ('2026-09-26T07:00:00+03:00', '2026-09-26T13:00:00+03:00', 12),
            ('2026-09-27T06:00:00+03:00', '2026-09-27T17:00:00+03:00', 14),
        ])
        self.assertTrue(all(s['start'] == s['checkin'] and s['end'] == s['checkout'] for s in shifts))

    def test_zone_capacity_comes_only_from_subtotal_not_inner_rows(self):
        from blog.services.fap_workbook import read_xlsx
        book = load_workbook(EXAMPLES / 'marathon.xlsx')
        sheet = book.active
        sheet['R3'], sheet['R4'], sheet['R8'] = 999, 999, 20
        sheet['H3'] = '00:00-23:59'
        stream = BytesIO()
        book.save(stream)
        day = read_xlsx(stream.getvalue())['directions'][0]['positions'][0]['days'][2]
        self.assertEqual(len(day['shifts']), 1)
        self.assertEqual(day['shifts'][0]['count'], 20)
        self.assertEqual(day['shifts'][0]['start'], '2026-09-26T07:00:00+03:00')
        self.assertEqual(day['shifts'][0]['end'], '2026-09-26T13:00:00+03:00')

    def test_invalid_zone_subtotal_is_not_replaced_by_inner_row_counts(self):
        from blog.services.fap_workbook import read_xlsx
        book = load_workbook(EXAMPLES / 'marathon.xlsx')
        book.active['R8'] = '12?'
        stream = BytesIO()
        book.save(stream)
        with self.assertRaisesMessage(ValidationError, 'R8'):
            read_xlsx(stream.getvalue())

    def test_marathon_short_dates_use_year_from_count_headers_and_keep_all_zone_blocks(self):
        from blog.services.fap_workbook import read_xlsx, write_xlsx
        source = (EXAMPLES / 'marathon.xlsx').read_bytes()
        plan = read_xlsx(source)
        self.assertEqual(plan['dates'], ['2026-09-24', '2026-09-25', '2026-09-26', '2026-09-27'])
        self.assertEqual(len(plan['directions']), 24)
        first, second = plan['directions'][:2]
        # Два блока одной функции — разные позиции; общий префикс функции, а
        # подпись группы различает их для тим-лидеров и менеджера.
        function = 'Организация сервисов для отдельных клиентских групп — '
        self.assertTrue(first['name'].startswith(function) and second['name'].startswith(function))
        self.assertNotEqual(first['name'], second['name'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['positions'][0]['days'][2]['quantities'][0]['count'], 12)
        self.assertEqual(second['positions'][0]['days'][2]['quantities'][0]['count'], 9)
        self.assertEqual(plan['directions'][-1]['positions'][0]['days'][2]['quantities'][0]['count'], 16)
        self.assertTrue(any(d['name'] == 'Волонтёры-медики' for d in plan['directions']))
        restored = read_xlsx(write_xlsx(plan, source))
        self.assertEqual([d['id'] for d in restored['directions']], [d['id'] for d in plan['directions']])
        self.assertEqual(restored['dates'], plan['dates'])

    def test_names_headers_and_subtotals_ignore_case_and_whitespace(self):
        from blog.services.fap_workbook import read_xlsx
        book = load_workbook(EXAMPLES / 'marathon.xlsx')
        sheet = book.active
        sheet.title = '  с М е Н ы  '
        sheet['J1'] = ' CHECK - IN / check - OUT '
        for col in (14, 16, 18, 20):
            sheet.cell(1, col, ' КОЛ - ВО / СМЕНА ')
        sheet['E8'] = ' и т О Г о\u00a0в\tз О н е : '
        sheet['E12'] = 'ИтОгО В зОнЕ:'
        sheet['C3'] = ' ТИМ  ЛИДЕРЫ '
        stream = BytesIO()
        book.save(stream)
        plan = read_xlsx(stream.getvalue())
        self.assertEqual(len(plan['directions']), 24)
        self.assertEqual(plan['directions'][0]['team_leaders'], [])
        self.assertEqual(plan['dates'][0], '2026-09-24')

    def test_date_formats_and_missing_or_conflicting_year(self):
        from blog.services.fap_workbook import read_xlsx
        def content(work, check, count):
            book = load_workbook(EXAMPLES / 'one-day.xlsx')
            sheet = book.active
            sheet['F2'], sheet['G2'], sheet['I1'] = work, check, count
            stream = BytesIO()
            book.save(stream)
            return stream.getvalue()
        for text in (' 10 . 10 . 2026 ', 'Race day 10/10/26', '2026 - 10 - 10', '10 ОКТЯБРЯ 2026', '10 october 2026'):
            with self.subTest(text=text):
                self.assertEqual(read_xlsx(content(text, text, None))['dates'], ['2026-10-10'])
        with self.assertRaises(ValidationError):
            read_xlsx(content('Race day 10.10', '10.10', None))
        with self.assertRaises(ValidationError):
            read_xlsx(content('Race day 10.10', '11.10.2026', '10.10.2026'))

    def test_google_selects_normalized_tab_name_before_reading_its_cells(self):
        from unittest.mock import Mock
        from blog.services.google_sheets import GoogleSheetClient
        client = GoogleSheetClient.__new__(GoogleSheetClient)
        client.session = object()
        metadata = {'sheets': [{'properties': {'title': '  с М е Н ы  ', 'sheetId': 42}}, {'properties': {'title': 'Другой лист', 'sheetId': 99}}]}
        client._request = Mock(side_effect=[Mock(json=lambda: metadata), Mock(json=lambda: {'sheets': [metadata['sheets'][0]]})])
        with patch('blog.services.google_sheets.grid_to_xlsx', return_value=(b'xlsx', 42)):
            self.assertEqual(client.read_google('spreadsheet', 99), (b'xlsx', 42))
        self.assertEqual(client._request.call_args_list[1].kwargs['params']['ranges'], "'  с М е Н ы  '")
        self.assertNotIn('ranges', client._request.call_args_list[0].kwargs['params'])

    def test_shift_labels_ignore_case_and_whitespace_when_matching_counts(self):
        from blog.services.fap_workbook import day_shifts
        shifts = day_shifts('2026-09-24', ' b : 10:00-12:00\n a : 08:00-10:00', None,
                            [{'label': '', 'count': 7}, {'label': 'A', 'count': 2}, {'label': 'B', 'count': 5}], [])
        self.assertEqual([s['count'] for s in shifts], [5, 2])

    def test_position_column_names_do_not_affect_direction_or_shift_counts(self):
        from blog.services.fap_workbook import read_xlsx
        from blog.services.event_sheets import content_signature
        source = (EXAMPLES / 'one-day.xlsx').read_bytes()
        expected = read_xlsx(source)
        book = load_workbook(BytesIO(source))
        for row in (3, 4, 5, 6):
            book['Смены'].cell(row, 5).value = None
        output = BytesIO()
        book.save(output)
        result = read_xlsx(output.getvalue())
        self.assertEqual(content_signature(expected), content_signature(result))
        first = result['directions'][0]
        self.assertEqual(first['positions'][0]['name'], first['name'])
        self.assertEqual([s['count'] for s in first['positions'][0]['days'][0]['shifts']], [15])
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
        for name, days, positions in [('three-days.xlsx', 3, 4), ('one-day.xlsx', 1, 4)]:
            with self.subTest(name=name):
                plan = read_xlsx((EXAMPLES / name).read_bytes())
                self.assertEqual(len(plan['dates']), days)
                self.assertEqual(len(plan['directions']), 4)
                self.assertEqual(sum(len(d['positions']) for d in plan['directions']), positions)
                self.assertFalse(any('ИТОГО' in p['name'] for d in plan['directions'] for p in d['positions']))

    def test_zero_blank_and_incomplete_time_are_not_lost(self):
        from blog.services.fap_workbook import read_xlsx
        plan = read_xlsx((EXAMPLES / 'three-days.xlsx').read_bytes())
        position = plan['directions'][0]['positions'][0]
        self.assertEqual(position['days'][0]['shifts'][0]['count'], 9)
        unknown = plan['directions'][3]['positions'][0]['days'][2]['quantities']
        self.assertEqual(next(q['count'] for q in unknown if q['label'] == 'Без времени'), 5)
        self.assertTrue(plan['warnings'])

    def test_only_shifts_sheet_is_exported_and_styles_are_preserved(self):
        from blog.services.fap_workbook import read_xlsx, write_xlsx
        source = (EXAMPLES / 'one-day.xlsx').read_bytes()
        plan = read_xlsx(source)
        exported = write_xlsx(plan, source)
        original, result = load_workbook(BytesIO(source)), load_workbook(BytesIO(exported))
        self.assertEqual(result.sheetnames, ['Смены'])
        a, b = original['Смены'], result['Смены']
        self.assertEqual(copy(a['A1'].font), copy(b['A1'].font))
        self.assertEqual(a['F2'].number_format, b['F2'].number_format)
        self.assertEqual(copy(a['A1'].fill), copy(b['A1'].fill))
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
            self.assertEqual(sum(len(d['positions']) for d in result['directions']), 4)

    def test_three_subshifts_keep_separate_times_and_counts(self):
        from blog.services.fap_workbook import day_shifts
        result = day_shifts('2026-11-01', 'A: 08:00-10:00\nB: 10:00-12:00\nC: 12:00-14:00', None,
            [{'label': '', 'count': 6}, {'label': 'A', 'count': 1}, {'label': 'B', 'count': 2}, {'label': 'C', 'count': 3}], [])
        self.assertEqual([r['count'] for r in result], [1, 2, 3])
        self.assertEqual([r['label'] for r in result], ['A', 'B', 'C'])

    def test_each_team_leader_set_inside_zone_is_a_separate_position(self):
        """Решение пользователя (2026-11-11): позиция = набор одного тим-лидера внутри
        блока «ИТОГО В ЗОНЕ». Тим-лидер видит только свой набор, менеджер — разрез
        «по точкам». Количество группы — сумма её строк, а не общий итог зоны."""
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
        plan = read_xlsx(stream.getvalue())
        first, second = plan['directions'][:2]
        self.assertEqual(first['team_leaders'], ['Первый лидер'])
        self.assertEqual(second['team_leaders'], ['Второй лидер'])
        self.assertNotEqual(first['name'], second['name'])
        self.assertEqual(len(plan['directions']), 5)

    def test_real_marathon_with_mentor_column_splits_distance_by_team_leaders(self):
        """Реальный ФиП ММ 2026: лишняя колонка «Наставник» сдвигает дни; «Дистанция»
        — один блок итогов, но 12 тим-лидерских наборов. Код группы совпадает с
        нумерацией в старой базе (10.1 ПО1 … 10.11 ПП5)."""
        from blog.services.fap_workbook import read_xlsx
        plan = read_xlsx((EXAMPLES / 'marathon-2026-mentors.xlsx').read_bytes())
        self.assertEqual(plan['dates'], ['2026-09-24', '2026-09-25', '2026-09-26', '2026-09-27'])
        by_code = {d['code']: d for d in plan['directions'] if d['code']}
        distance = [d for d in plan['directions'] if d['code'].startswith('10.')]
        self.assertEqual(len(distance), 12)
        first = by_code['10.1']
        self.assertEqual(first['name'], 'Волонтёры дистанции — Пункт освежения (ПО1)')
        self.assertIn('Волонтер пункта освежения (ПО1)', first['source_rows'])
        self.assertEqual(first['positions'][0]['days'][3]['shifts'][0]['count'], 77)
        self.assertEqual(by_code['10.4']['name'], 'Волонтёры дистанции — Пункт питания на дистанции (ПП2)')
        zone = by_code['7.2']
        self.assertEqual(zone['name'], 'Организация выдачи пакетов участников — Зона выдачи номеров и пакетов участника')
        self.assertEqual(zone['positions'][0]['days'][0]['shifts'][0]['count'], 157)
        self.assertEqual(zone['team_leaders'][:2], ['Анна Баринова', 'Марина Бабич'])

    def test_team_lead_text_detection_ignores_case_spacing_and_yo(self):
        from blog.services.fap_workbook import is_team_lead_text
        for text in ('Тим-лидер зоны', 'тим лидер', 'ТИМЛИДЕР ПО1', 'Тим‑лидёр', '7.2 - Тим-лидер волонтёров'):
            self.assertTrue(is_team_lead_text(text), text)
        for text in ('Помощник тим-лидера организации', 'Ассистент выдачи', 'Волонтёр-тимбилдинг'):
            self.assertFalse(is_team_lead_text(text), text)

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
        payload['sheets'][0]['properties']['title'] = ' с М Е н ы '
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
        self.assertEqual(sum(META_PREFIX in cell.get('note', '') for row in rows for cell in row['values']), 4)

    def test_named_shift_ids_follow_labels_after_reordering(self):
        from blog.services.fap_workbook import day_shifts
        quantities = [{'label': '', 'count': 3}, {'label': 'A', 'count': 1}, {'label': 'B', 'count': 2}]
        old = day_shifts('2026-11-01', 'A: 08:00-10:00\nB: 10:00-12:00', None, quantities, [])
        new = day_shifts('2026-11-01', 'B: 10:00-12:00\nA: 08:00-10:00', None, quantities, [], old)
        self.assertEqual([s['id'] for s in new], [old[1]['id'], old[0]['id']])


class FaPImportTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()

    def test_same_file_reimport_corrects_previous_multiple_shifts_per_day(self):
        from copy import deepcopy
        from uuid import uuid4
        from blog.models import EventGroup
        from blog.services.event_sheets import import_plan, import_workbook
        from blog.services.fap_workbook import read_xlsx, group_directions
        source = (EXAMPLES / 'marathon.xlsx').read_bytes()
        legacy = read_xlsx(source)
        legacy.pop('daily_zone_shifts')
        day = legacy['directions'][0]['positions'][0]['days'][2]
        day['shifts'][0]['count'] = 1
        extra = deepcopy(day['shifts'][0])
        extra['id'], extra['count'] = str(uuid4()), 2
        extra['start'] = extra['checkin'] = '2026-09-26T08:00:00+03:00'
        day['shifts'].append(extra)
        legacy = group_directions(legacy)
        group = EventGroup.objects.create(title='Прежний импорт')
        import_plan(self.manager, group, legacy, source, 'мм.xlsx')
        event = group.positions.order_by('pk').first()
        retained_id = event.shifts.order_by('day', 'pk').first().pk
        self.assertEqual(event.shifts.count(), 3)
        application = f.make_application(event)
        with self.assertRaises(ValidationError):
            import_workbook(self.manager, group, source)
        self.assertEqual(event.shifts.count(), 3)
        application.delete()
        import_workbook(self.manager, group, source)
        self.assertEqual(group.positions.count(), 24)
        self.assertEqual(list(event.shifts.order_by('day').values_list('volunteer_needed', flat=True)), [12, 14])
        self.assertEqual(event.shifts.order_by('day').first().pk, retained_id)

    def test_marathon_upload_creates_each_zone_as_a_separate_position(self):
        from blog.models import EventGroup
        from blog.services.event_sheets import import_workbook, export_workbook
        group = EventGroup.objects.create(title='Марафон')
        source = (EXAMPLES / 'marathon.xlsx').read_bytes()
        import_workbook(self.manager, group, source)
        self.assertEqual(group.positions.count(), 24)
        first = group.positions.order_by('pk').first()
        self.assertEqual(list(first.shifts.order_by('day').values_list('day', 'volunteer_needed')), [(date(2026, 9, 26), 12), (date(2026, 9, 27), 14)])
        ids = list(group.positions.order_by('pk').values_list('pk', flat=True))
        exported = export_workbook(self.manager, group)
        import_workbook(self.manager, group, exported)
        self.assertEqual(list(group.positions.order_by('pk').values_list('pk', flat=True)), ids)

    def test_legacy_import_repair_preserves_first_event_and_shift_ids(self):
        import hashlib, uuid
        from datetime import datetime
        from django.utils import timezone
        from blog.models import EventGroup, EventDirection, SheetPosition, SheetPositionDay, SheetShift, EventSheetLink
        from blog.services.event_sheets import repair_direction_import
        group = EventGroup.objects.create(title='Старый импорт')
        direction = EventDirection.objects.create(event_group=group, name='Направление', sort_order=0)
        rows, events, shifts = [], [], []
        for i, count in enumerate((2, 3)):
            event = f.make_event(event_group=group)
            position = SheetPosition.objects.create(event=event, direction=direction, sort_order=i)
            start = timezone.make_aware(datetime(2026, 11, 3, 9))
            end = timezone.make_aware(datetime(2026, 11, 3, 12))
            shift = f.make_shift(event, day=start.date(), start_time=start, end_time=end, volunteer_needed=count)
            quantities = [{'label': '', 'count': count}, {'label': 'A', 'count': None}, {'label': 'B', 'count': None}]
            day = SheetPositionDay.objects.create(position=position, day=start.date(), raw_work_time='09:00-12:00', quantities=quantities)
            source = SheetShift.objects.create(shift=shift, position_day=day, planned_count=count)
            rows.append({'id': str(position.source_key), 'name': event.title, 'order': i, 'row': 3+i, 'team_leaders': [], 'responsibles': [], 'is_team_lead_role': False,
                'days': [{'date': start.date().isoformat(), 'work': '09:00-12:00', 'checkin_out': None, 'quantities': quantities,
                    'shifts': [{'id': str(source.source_key), 'label': '', 'start': start.isoformat(), 'end': end.isoformat(), 'checkin': None, 'checkout': None, 'count': count}]}]})
            events.append(event)
            shifts.append(shift)
        baseline = {'dates': ['2026-11-03'], 'quantity_widths': [3], 'warnings': [], 'directions': [{'id': str(direction.source_key), 'name': 'Направление', 'order': 0, 'team_leaders': [], 'responsibles': [], 'positions': rows}]}
        EventSheetLink.objects.create(event_group=group, baseline=baseline, template=(EXAMPLES/'one-day.xlsx').read_bytes())
        repair_direction_import(self.manager, group)
        self.assertEqual(list(group.positions.values_list('pk', 'title')), [(events[0].pk, 'Направление')])
        shifts[0].refresh_from_db()
        self.assertEqual(shifts[0].volunteer_needed, 5)
        self.assertEqual(events[0].shifts.count(), 1)

    def test_import_creates_positions_shifts_and_separate_zone_responsibles(self):
        from blog.services.event_sheets import import_workbook
        from blog.models import EventGroup, ZoneResponsible, Manager
        group = EventGroup.objects.create(title='FaP')
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes(), 'пример.xlsx')
        self.assertEqual(group.positions.count(), 4)
        self.assertEqual(sum(p.shifts.count() for p in group.positions.all()), 4)
        self.assertEqual(ZoneResponsible.objects.filter(direction__event_group=group).count(), 4)
        self.assertEqual(Manager.objects.count(), 1)
        link = group.sheet_link
        self.assertTrue(link.warnings == [] or isinstance(link.warnings, list))
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes(), 'пример.xlsx')
        self.assertEqual(group.positions.count(), 4)

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
        self.assertEqual(group.positions.count(), 4)

    def test_manually_added_positions_stay_separate_directions_on_round_trip(self):
        from blog.services.event_sheets import import_workbook, export_workbook
        from blog.services.fap_workbook import read_xlsx
        from blog.models import EventGroup
        group = EventGroup.objects.create(title='Ручные направления')
        import_workbook(self.manager, group, (EXAMPLES / 'one-day.xlsx').read_bytes())
        events = [f.make_event(title=name, event_group=group) for name in ('Новое направление', 'Ещё направление')]
        for event in events:
            shift = f.make_shift(event)
            shift.start_time = shift.start_time.replace(second=0, microsecond=0)
            shift.end_time = shift.end_time.replace(second=0, microsecond=0)
            shift.save(update_fields=['start_time', 'end_time'])
        exported = export_workbook(self.manager, group)
        self.assertEqual(len(read_xlsx(exported)['directions']), 6)
        # У ручных смен нет плановых check-in/out: импорт не должен молча
        # подменять их рабочим временем и удалять исходные смены.
        with self.assertRaises(ValidationError):
            import_workbook(self.manager, group, exported)
        self.assertEqual(group.positions.count(), 6)
        for event in events:
            event.refresh_from_db()
            self.assertEqual(event.shifts.count(), 1)

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
        self.assertEqual(EventGroup.objects.get(title='Из таблицы').positions.count(), 4)

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
        self.assertEqual(EventStaff.objects.filter(user=user, staff_role='team_lead').count(), 1)
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
        self.assertEqual(EventStaff.objects.filter(user=new, staff_role='team_lead').count(), 1)

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
        book['Смены']['B3'] = 'Правка Google'
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
