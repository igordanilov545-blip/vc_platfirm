"""Чистое чтение/запись единственного листа FaP «Смены», без доступа к БД."""
from copy import copy, deepcopy
from datetime import date, datetime, time, timedelta
from io import BytesIO
import json
from pathlib import Path
import re
import unicodedata
import uuid
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel, CALENDAR_WINDOWS_1900


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / 'resources' / 'fap'
MSK = ZoneInfo('Europe/Moscow')
META_PREFIX = 'vc_fap:'


def normalized_name(value):
    """Ключ распознавания; исходное написание названий/имён не меняем."""
    text = unicodedata.normalize('NFKC', str(value) if value is not None else '')
    return re.sub(r'\s+', '', text.casefold()).replace('ё', 'е')


def only_shifts_content(content):
    """Убирает ссылки на чужие листы ДО openpyxl: их XML вообще не разбирается."""
    with ZipFile(BytesIO(content)) as source:
        if sum(item.file_size for item in source.infolist()) > 50 * 1024 * 1024:
            raise ValidationError('Таблица слишком большая после распаковки.')
        ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        rel_attr = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
        book = ET.fromstring(source.read('xl/workbook.xml'))
        sheets = book.find('m:sheets', ns)
        matching = [s for s in sheets if normalized_name(s.attrib['name']) == normalized_name('Смены')]
        if len(matching) != 1:
            raise ValidationError('В таблице нужна одна вкладка «Смены» (регистр и пробелы не учитываются).')
        target = matching[0]
        target.set('name', 'Смены')
        index = list(sheets).index(target)
        removed_ids = {s.attrib[rel_attr] for s in sheets if s is not target}
        for child in list(sheets):
            if child is not target:
                sheets.remove(child)
        names = book.find('m:definedNames', ns)
        if names is not None:
            for name in list(names):
                if 'localSheetId' in name.attrib:
                    if int(name.attrib['localSheetId']) == index:
                        name.set('localSheetId', '0')
                    else:
                        names.remove(name)
        for view in book.findall('m:bookViews/m:workbookView', ns):
            view.set('activeTab', '0')
            view.set('firstSheet', '0')
        rels = ET.fromstring(source.read('xl/_rels/workbook.xml.rels'))
        excluded = set()
        for rel in list(rels):
            if rel.attrib['Id'] in removed_ids:
                path = rel.attrib['Target']
                excluded.add(posixpath.normpath(path.lstrip('/') if path.startswith('/') else 'xl/' + path))
                rels.remove(rel)
        output = BytesIO()
        with ZipFile(output, 'w') as destination:
            for item in source.infolist():
                if item.filename in excluded:
                    continue
                raw = ET.tostring(book, encoding='utf-8', xml_declaration=True) if item.filename == 'xl/workbook.xml' else ET.tostring(rels, encoding='utf-8', xml_declaration=True) if item.filename == 'xl/_rels/workbook.xml.rels' else source.read(item.filename)
                destination.writestr(item, raw)
        return output.getvalue()


def new_id():
    return str(uuid.uuid4())


def _text(value):
    return str(value).strip() if value is not None else ''


def _date(value, reference=None, epoch=CALENDAR_WINDOWS_1900):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = from_excel(value, epoch)
            return converted.date().isoformat() if isinstance(converted, datetime) else None
        except (ValueError, OverflowError):
            return None
    text = normalized_name(value)
    match = re.search(r'(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)', text)
    if match:
        year, month, day = map(int, match.groups())
    else:
        match = re.search(r'(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}|\d{2}))?(?!\d)', text)
        if match:
            day, month = map(int, match.groups()[:2])
            year = int(match[3]) if match[3] else date.fromisoformat(reference).year if reference else None
            if year is not None and year < 100:
                year += 2000 if year < 69 else 1900
        else:
            months = (
                ('январь', 'января', 'янв', 'january', 'jan'), ('февраль', 'февраля', 'фев', 'february', 'feb'),
                ('март', 'марта', 'мар', 'march', 'mar'), ('апрель', 'апреля', 'апр', 'april', 'apr'),
                ('май', 'мая', 'may'), ('июнь', 'июня', 'июн', 'june', 'jun'),
                ('июль', 'июля', 'июл', 'july', 'jul'), ('август', 'августа', 'авг', 'august', 'aug'),
                ('сентябрь', 'сентября', 'сен', 'сент', 'september', 'sep', 'sept'),
                ('октябрь', 'октября', 'окт', 'october', 'oct'), ('ноябрь', 'ноября', 'ноя', 'november', 'nov'),
                ('декабрь', 'декабря', 'дек', 'december', 'dec'),
            )
            match = re.search(r'(?<!\d)(\d{1,2})([а-яa-z]+)\.?(\d{4})?(?!\d)', text)
            if not match:
                return None
            day = int(match[1])
            month = next((i for i, names in enumerate(months, 1) if match[2] in names), 0)
            year = int(match[3]) if match[3] else date.fromisoformat(reference).year if reference else None
    if year is not None:
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    return None


def _names(value):
    ignored = {normalized_name(name) for name in ('тим лидеры', 'тим-лидеры', 'тим-лидер', 'менеджеры', 'менеджер бс', 'ответственные за зону')}
    return [name.strip() for name in _text(value).splitlines() if name.strip() and normalized_name(name.strip()) not in ignored]


def _intervals(value, day, warnings):
    result = []
    for line in re.split(r'[\n;]+', _text(value)):
        if not line.strip():
            continue
        matches = list(re.finditer(r'(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})', line))
        if not matches:
            warnings.append(f'{day}: не распознан интервал «{line}», исходный текст сохранён.')
        for match in matches:
            try:
                sh, sm, eh, em = map(int, match.groups())
                start = datetime.combine(date.fromisoformat(day), time(sh, sm), MSK)
                end = datetime.combine(date.fromisoformat(day), time(eh % 24, em), MSK)
                if eh > 24 or eh == 24 and em:
                    raise ValueError
                if end == start:
                    raise ValueError
                if end < start or eh == 24:
                    end += timedelta(days=1)
                label = line[:match.start()].strip(' :—–-')
                label = re.sub(r'^смена\s*', '', label, flags=re.I)
                result.append({'label': label, 'start': start.isoformat(), 'end': end.isoformat()})
            except ValueError:
                warnings.append(f'{day}: некорректный интервал «{line}», исходный текст сохранён.')
    return result


def day_shifts(day, work, checkin_out, quantities, warnings, ids=None):
    """0…M подсмен, включая общий интервал с раздельными количествами A/B/C."""
    intervals = _intervals(work, day, warnings)
    checks = _intervals(checkin_out, day, warnings)
    split = [item for item in quantities[1:] if item['count'] is not None and normalized_name(item['label']) != normalized_name('Без времени')]
    if len(intervals) == 1 and len(split) > 1:
        intervals = [{**intervals[0], 'label': item['label']} for item in split]
    result = []
    for index, interval in enumerate(intervals):
        label = interval['label'] or (split[index]['label'] if index < len(split) else '')
        quantity = next((item for item in split if normalized_name(item['label']) == normalized_name(label)), None)
        if quantity is None:
            quantity = split[index] if index < len(split) else quantities[0] if len(intervals) == 1 else {'count': None}
        check = next((item for item in checks if item['label'] and normalized_name(item['label']) == normalized_name(label)), None)
        if check is None and checks:
            check = checks[min(index, len(checks) - 1)]
        known = ids or []
        if known and isinstance(known[0], str):
            # Первый формат метаданных, до появления именованных подсмен.
            source_id = known[index] if index < len(known) else new_id()
        else:
            matches = [old for old in known if label and normalized_name(old.get('label')) == normalized_name(label)]
            if not matches and len(intervals) == 1 and len(known) == 1:
                matches = known
            if not matches:
                matches = [old for old in known if old.get('start') == interval['start'] and old.get('end') == interval['end']]
            if len(matches) > 1:
                raise ValidationError(f'{day}: задайте разные ярлыки подсмен, чтобы сохранить их ID.')
            source_id = matches[0]['id'] if matches else new_id()
        result.append({'id': source_id, 'label': label, 'start': interval['start'], 'end': interval['end'],
                       'count': quantity['count'], 'checkin': check['start'] if check else None,
                       'checkout': check['end'] if check else None})
    if not intervals and any(item['count'] is not None for item in quantities):
        warnings.append(f'{day}: количество задано без рабочего времени; план сохранён, рабочая смена пока не создана.')
    elif len(intervals) > 1 and not split and quantities[0]['count'] is not None:
        warnings.append(f'{day}: несколько рабочих интервалов без распределения количества; общий план сохранён без выдуманного распределения.')
    return result


def _metadata(cell):
    if cell.comment and META_PREFIX in cell.comment.text:
        try:
            raw = cell.comment.text.split(META_PREFIX, 1)[1].splitlines()[0]
            value = json.loads(raw)
            for key in ('position', 'direction'):
                uuid.UUID(value[key])
            for ids in value.get('days', {}).values():
                for item in ids:
                    uuid.UUID(item['id'] if isinstance(item, dict) else item)
            return value
        except (ValueError, KeyError, TypeError):
            raise ValidationError('Повреждены служебные идентификаторы FaP.')
    return {}


def group_directions(plan):
    """Направление = позиция платформы; строки E — только исходные строки файла."""
    grouped = deepcopy(plan)
    grouped['grouped_directions'] = True
    grouped['input_rows'] = sum(len(d['positions']) for d in plan['directions'])
    for direction in grouped['directions']:
        rows = direction['positions']
        for field in ('team_leaders', 'responsibles'):
            direction[field] = list(dict.fromkeys(direction[field] + [name for row in rows for name in row[field]]))
        position = {'id': direction['id'], 'name': direction['name'], 'order': 0, 'row': rows[0].get('row'),
                    'is_team_lead_role': False, 'team_leaders': [], 'responsibles': [], 'days': []}
        for day_index, day in enumerate(grouped['dates']):
            intervals = {}
            incomplete = []
            for row in rows:
                source = row['days'][day_index]
                if not source['shifts'] or all(s['count'] is None for s in source['shifts']):
                    quantities = source['quantities']
                    counts = [q['count'] for q in quantities[1:] if q['count'] is not None]
                    count = sum(counts) if counts else quantities[0]['count']
                    if count is not None:
                        incomplete.append(count)
                else:
                    incomplete.extend(q['count'] for q in source['quantities'] if q['label'] == 'Без времени' and q['count'] is not None)
                for shift in source['shifts']:
                    key = (shift['start'], shift['end'], shift['checkin'], shift['checkout'])
                    if key not in intervals:
                        intervals[key] = deepcopy(shift)
                    else:
                        before = intervals[key]['count']
                        intervals[key]['count'] = (before or 0) + (shift['count'] or 0) if before is not None or shift['count'] is not None else None
            shifts = sorted(intervals.values(), key=lambda s: (s['start'], s['end'], s['checkin'] or '', s['checkout'] or ''))
            for i, shift in enumerate(shifts):
                shift['label'] = chr(65 + i)
            def display(start, end):
                return '\n'.join(f"{s['label']}: {datetime.fromisoformat(s[start]).strftime('%H:%M')}-{datetime.fromisoformat(s[end]).strftime('%H:%M')}" for s in shifts if s[start] and s[end]) or None
            quantities = [{'label': '', 'count': sum(s['count'] or 0 for s in shifts) + sum(incomplete) if shifts or incomplete else None}]
            quantities += [{'label': s['label'], 'count': s['count']} for s in shifts]
            if incomplete:
                quantities.append({'label': 'Без времени', 'count': sum(incomplete)})
            position['days'].append({'date': day, 'work': display('start', 'end'), 'checkin_out': display('checkin', 'checkout'),
                                     'quantities': quantities, 'shifts': shifts})
        direction['positions'] = [position]
    grouped['quantity_widths'], grouped['quantity_labels'] = [], []
    for i, day in enumerate(grouped['dates']):
        max_shifts = max((len(d['positions'][0]['days'][i]['shifts']) for d in grouped['directions']), default=0)
        has_unknown = any(any(q['label'] == 'Без времени' for q in d['positions'][0]['days'][i]['quantities']) for d in grouped['directions'])
        labels = [''] + [chr(65 + j) for j in range(max(2, max_shifts))] + (['Без времени'] if has_unknown else [])
        grouped['quantity_widths'].append(len(labels))
        grouped['quantity_labels'].append(labels)
        for direction in grouped['directions']:
            item = direction['positions'][0]['days'][i]
            values = {q['label']: q['count'] for q in item['quantities']}
            item['quantities'] = [{'label': label, 'count': values.get(label)} for label in labels]
    return grouped


def _header_layout(sheet, value, epoch):
    """Дни работы, check-in/out и количества — независимые блоки заголовка."""
    def header(col):
        return re.sub(r'[-/–—]', '', normalized_name(sheet.cell(1, col).value))

    check_start = next((col for col in range(7, sheet.max_column + 1)
                        if 'checkin' in header(col) and 'checkout' in header(col)), None)
    if check_start is None:
        raise ValidationError('В первой строке не найден блок Check-in / Check-out.')
    days_count = check_start - 6
    count_start = check_start + days_count
    starts = [col for col in range(count_start, sheet.max_column + 1)
              if 'кол' in header(col) and 'смен' in header(col)]
    if len(starts) != days_count:
        raise ValidationError('Количество блоков «Кол-во / смена» должно совпадать с количеством рабочих дней.')
    widths = []
    for i, start in enumerate(starts):
        if i + 1 < len(starts):
            widths.append(starts[i + 1] - start)
            continue
        merged = next((area for area in sheet.merged_cells.ranges
                       if area.min_row <= 2 <= area.max_row and area.min_col == start), None)
        end = merged.max_col if merged else start + 2
        for area in sheet.merged_cells.ranges:
            if area.min_row == 1 and start <= area.min_col <= start + 1:
                end = max(end, area.max_col)
        while re.fullmatch(r'[a-zа-я]', normalized_name(sheet.cell(2, end + 1).value)):
            end += 1
        widths.append(end - start + 1)
    dates = []
    for i, start in enumerate(starts):
        headers = [value(2, 6 + i), value(2, check_start + i)]
        headers += [value(row, col) for row in (1, 2) for col in range(start, start + widths[i])]
        complete = [_date(item, epoch=epoch) for item in headers]
        complete = [day for day in complete if day]
        if not complete:
            raise ValidationError(f'Не удалось определить год дня в колонке {get_column_letter(6 + i)}. Укажите полную дату в заголовке работы, check-in/out или количества.')
        day = complete[0]
        recognized = [_date(item, reference=day, epoch=epoch) for item in headers]
        if any(item and item != day for item in recognized):
            raise ValidationError(f'Даты рабочего дня, check-in/out и количества не совпадают в колонке {get_column_letter(6 + i)}.')
        if not recognized[0]:
            raise ValidationError(f'Не распознана дата рабочего дня в колонке {get_column_letter(6 + i)}.')
        dates.append(day)
    if len(set(dates)) != len(dates):
        raise ValidationError('Рабочие дни должны иметь разные даты.')
    return dates, starts, widths


def read_xlsx(content):
    """Значения merged-ячеек наследуются логически; другие вкладки не используются."""
    try:
        content = only_shifts_content(content)
        workbook = load_workbook(BytesIO(content), data_only=False)
        cached = load_workbook(BytesIO(content), data_only=True)
    except (BadZipFile, ValueError, KeyError, OSError, ET.ParseError) as error:
        raise ValidationError('Не удалось прочитать XLSX. Загрузите обычную книгу Excel.') from error
    if 'Смены' not in workbook.sheetnames:
        raise ValidationError('В таблице нужна вкладка с точным названием «Смены».')
    sheet, values = workbook['Смены'], cached['Смены']
    if sheet.max_row * sheet.max_column > 250000:
        raise ValidationError('Слишком большой лист «Смены».')
    merged = {}
    for area in sheet.merged_cells.ranges:
        for row in range(area.min_row, area.max_row + 1):
            for col in range(area.min_col, area.max_col + 1):
                merged[row, col] = (area.min_row, area.min_col, area.max_row)

    def value(row, col):
        anchor = merged.get((row, col), (row, col, row))
        return values.cell(anchor[0], anchor[1]).value

    dates, starts, widths = _header_layout(sheet, value, workbook.epoch)
    plan = {'dates': dates, 'directions': [], 'warnings': [], 'quantity_widths': widths}
    direction = None
    for row in range(3, sheet.max_row + 1):
        name = _text(value(row, 5))
        if normalized_name(value(row, 2)).startswith('итоги'):
            break
        if normalized_name(name).startswith('итого'):
            direction = None
            continue
        if not _text(value(row, 2)) or not name and not any(value(row, c) is not None for c in range(6, sheet.max_column + 1)):
            continue
        metadata = _metadata(sheet.cell(row, 5))
        if direction is None:
            end_row = next((r for r in range(row + 1, sheet.max_row + 1) if normalized_name(value(r, 5)).startswith('итого')), row)
            direction = {'id': metadata.get('direction', new_id()), 'name': _text(value(row, 2)),
                         'order': len(plan['directions']), 'team_leaders': [], 'responsibles': [], 'positions': [], '_inherited': set()}
            for c, key in ((3, 'team_leaders'), (4, 'responsibles')):
                if merged.get((row, c), (row, c, row))[2] >= end_row - 1 and end_row > row:
                    direction[key] = _names(value(row, c))
                    direction['_inherited'].add(key)
            plan['directions'].append(direction)
        position = {'id': metadata.get('position', new_id()), 'name': name, 'order': len(direction['positions']),
                    'row': row, 'is_team_lead_role': bool(re.match(r'^тим[\s-]*лидер', name, re.I)),
                    'team_leaders': [], 'responsibles': [], 'days': []}
        for c, key in ((3, 'team_leaders'), (4, 'responsibles')):
            if key not in direction['_inherited']:
                position[key] = _names(value(row, c))
        for i, day in enumerate(dates):
            quantities = []
            for offset in range(widths[i]):
                cell = sheet.cell(row, starts[i] + offset)
                # Горизонтальный merge количества означает одно общее число.
                raw = None if isinstance(cell, MergedCell) else value(row, starts[i] + offset)
                count = None
                if raw is not None and raw != '':
                    try:
                        number = float(raw)
                        if not number.is_integer() or number < 0:
                            raise ValueError
                        count = int(number)
                    except (ValueError, TypeError):
                        plan['warnings'].append(f'Строка {row}, {day}: количество «{raw}» не распознано.')
                label = '' if offset == 0 else _text(value(2, starts[i] + offset)) or chr(64 + offset)
                quantity = {'label': label, 'count': count}
                if raw not in (None, '') and count is None:
                    quantity['raw'] = str(raw)
                quantities.append(quantity)
            split_counts = [q['count'] for q in quantities[1:] if q['count'] is not None]
            if split_counts and quantities[0]['count'] is not None and sum(split_counts) != quantities[0]['count']:
                plan['warnings'].append(f'Строка {row}, {day}: общий итог не совпадает с подсменами; для расчёта используются подсмены, исходные числа сохранены.')
            work, checks = value(row, 6 + i), value(row, 6 + len(dates) + i)
            item = {'date': day, 'work': str(work) if work is not None else None,
                    'checkin_out': str(checks) if checks is not None else None, 'quantities': quantities}
            item['shifts'] = day_shifts(day, item['work'], item['checkin_out'], quantities, plan['warnings'], metadata.get('days', {}).get(day))
            position['days'].append(item)
        direction['positions'].append(position)
    if not plan['directions']:
        raise ValidationError('На вкладке «Смены» не найдены направления и позиции.')
    for direction in plan['directions']:
        direction.pop('_inherited', None)
    return group_directions(plan)


def _copy_style(source, target):
    target.font = copy(source.font)
    target.fill = copy(source.fill)
    target.border = copy(source.border)
    target.alignment = copy(source.alignment)
    target.number_format = source.number_format
    target.protection = copy(source.protection)


def _build_layout(plan, template):
    """Произвольные N дней и направлений, стили берутся из исходного XLSX."""
    reference = load_workbook(BytesIO(template))['Смены']
    wb = Workbook()
    sheet = wb.active
    sheet.title = 'Смены'
    n = len(plan['dates'])
    widths = plan.get('quantity_widths', [3] * n)
    if len(widths) != n:
        widths = [3] * n
    starts, cursor = [], 6 + 2 * n
    for width in widths:
        starts.append(cursor)
        cursor += width
    for row in (1, 2):
        sheet.row_dimensions[row].height = reference.row_dimensions[row].height
        _copy_style(reference.row_dimensions[row], sheet.row_dimensions[row])
        for col in range(1, cursor):
            _copy_style(reference.cell(row, min(col, 10)), sheet.cell(row, col))
    for col in range(1, cursor):
        src = col if col < 6 else 6 if col < 6 + n else 7 if col < 6 + 2 * n else 8
        sheet.column_dimensions[get_column_letter(col)].width = reference.column_dimensions[get_column_letter(src)].width
    for col, text in ((1, 'Направление'), (3, 'Тим-лидер'), (4, 'Ответственные за зону'), (5, 'Позиция'), (6, 'Время работы зоны'), (6 + n, 'Check-in / Check-out')):
        sheet.cell(1, col, text)
    sheet.merge_cells('A1:B1')
    sheet.merge_cells('A2:E2')
    if n > 1:
        sheet.merge_cells(start_row=1, start_column=6, end_row=1, end_column=5 + n)
        sheet.merge_cells(start_row=1, start_column=6 + n, end_row=1, end_column=5 + 2 * n)
    for i, day in enumerate(plan['dates']):
        for col in (6 + i, 6 + n + i):
            sheet.cell(2, col, datetime.fromisoformat(day)).number_format = reference['F2'].number_format
        sheet.cell(1, starts[i], 'Кол-во / смена')
        sheet.cell(1, starts[i] + 1, datetime.fromisoformat(day)).number_format = reference['I1'].number_format
        if widths[i] > 2:
            sheet.merge_cells(start_row=1, start_column=starts[i] + 1, end_row=1, end_column=starts[i] + widths[i] - 1)
        for j in range(widths[i]):
            labels = plan.get('quantity_labels', [])
            sheet.cell(2, starts[i] + j, 'всего' if j == 0 else labels[i][j] if i < len(labels) and j < len(labels[i]) else chr(64 + j))
    row = 3
    for index, direction in enumerate(plan['directions']):
        start = row
        ref_row = (3, 8, 13, 17)[index % 4]
        for position in direction['positions']:
            position['row'] = row
            sheet.row_dimensions[row].height = reference.row_dimensions[ref_row].height
            for col in range(1, cursor):
                src = col if col < 6 else 6 if col < 6 + n else 7 if col < 6 + 2 * n else 8
                _copy_style(reference.cell(ref_row, src), sheet.cell(row, col))
            row += 1
        sheet.cell(row, 5, 'ИТОГО В ЗОНЕ:')
        for col in range(1, cursor):
            _copy_style(reference.cell((7, 12, 16, 19)[index % 4], min(col, 10)), sheet.cell(row, col))
        for col in (1, 2):
            if row > start:
                sheet.merge_cells(start_row=start, start_column=col, end_row=row, end_column=col)
        for col, key in ((3, 'team_leaders'), (4, 'responsibles')):
            if direction[key] and not any(p[key] for p in direction['positions']) and row > start:
                sheet.merge_cells(start_row=start, start_column=col, end_row=row, end_column=col)
        row += 1
    for label in ('Волонтёры всего / смена', 'Тим-лидеров всего / смена', 'Факт набрано / смена вкл. тим-лидеров', 'Факт check-in / смена вкл. тим-лидеров', 'Набор в %', 'Явка в % от плана', 'Волонтёры всего, уникальные'):
        sheet.cell(row, 5, label)
        for col in range(1, cursor):
            _copy_style(reference.cell(20, min(col, 10)), sheet.cell(row, col))
        row += 1
    sheet.freeze_panes = reference.freeze_panes
    return wb


def write_xlsx(plan, template=None):
    """Точный исходный layout при неизменной геометрии; иначе расширение шаблона."""
    plan = deepcopy(plan)
    template = template or (TEMPLATE_DIR / 'one-day.xlsx').read_bytes()
    template = only_shifts_content(template)
    original_plan = read_xlsx(template)
    same_layout = (plan['dates'] == original_plan['dates'] and
                   original_plan['input_rows'] == sum(len(d['positions']) for d in plan['directions']) and
                   plan.get('quantity_widths') == original_plan.get('quantity_widths') and
                   [len(d['positions']) for d in plan['directions']] == [len(d['positions']) for d in original_plan['directions']] and
                   all(p.get('row') == q['row'] for d, e in zip(plan['directions'], original_plan['directions']) for p, q in zip(d['positions'], e['positions'])))
    if same_layout:
        reference = load_workbook(BytesIO(template))['Смены']
        cursor = 6 + 2 * len(plan['dates'])
        starts = []
        for width in plan['quantity_widths']:
            starts.append(cursor)
            cursor += width
        same_layout = not any(isinstance(reference.cell(p['row'], starts[i] + j), MergedCell) and q['count'] is not None
            for d in plan['directions'] for p in d['positions'] for i, day in enumerate(p['days']) for j, q in enumerate(day['quantities']))
    wb = load_workbook(BytesIO(template)) if same_layout else _build_layout(plan, template)
    for other in list(wb.sheetnames):
        if other != 'Смены':
            wb.remove(wb[other])
    sheet = wb['Смены']
    n = len(plan['dates'])
    widths = plan.get('quantity_widths', [3] * n)
    if len(widths) != n:
        widths = [3] * n
    starts, cursor = [], 6 + 2 * n
    for width in widths:
        starts.append(cursor)
        cursor += width

    def put(row, col, value):
        cell = sheet.cell(row, col)
        if not isinstance(cell, MergedCell):
            cell.value = value

    all_rows, lead_rows = [], []
    for di, direction in enumerate(plan['directions']):
        rows = []
        for position in direction['positions']:
            row = position['row']
            rows.append(row)
            all_rows.append(row)
            if position['is_team_lead_role']:
                lead_rows.append(row)
            for col, value in ((1, di + 1), (2, direction['name']), (3, '\n'.join(position['team_leaders'] or direction['team_leaders'])), (4, '\n'.join(position['responsibles'] or direction['responsibles'])), (5, position['name'])):
                put(row, col, value)
            cell = sheet.cell(row, 5)
            old_comment = cell.comment.text.split(META_PREFIX, 1)[0].strip() if cell.comment else ''
            metadata = {'position': position['id'], 'direction': direction['id'], 'days': {d['date']: [{k: s[k] for k in ('id', 'label', 'start', 'end')} for s in d['shifts']] for d in position['days']}}
            cell.comment = Comment((old_comment + '\n' if old_comment else '') + META_PREFIX + json.dumps(metadata, ensure_ascii=False, separators=(',', ':')), 'VC Platform')
            for i, day in enumerate(position['days']):
                put(row, 6 + i, day['work'])
                put(row, 6 + n + i, day['checkin_out'])
                for j, item in enumerate(day['quantities']):
                    if j < widths[i]:
                        put(row, starts[i] + j, item.get('raw', item['count']))
                if day['quantities'][0]['count'] is None and any(q['count'] is not None for q in day['quantities'][1:]):
                    first, last = get_column_letter(starts[i] + 1), get_column_letter(starts[i] + len(day['quantities']) - 1)
                    put(row, starts[i], f'=SUM({first}{row}:{last}{row})')
        total_row = max(rows) + 1
        for i, start in enumerate(starts):
            for j in range(widths[i]):
                col = get_column_letter(start + j)
                put(total_row, start + j, f'=SUM({col}{min(rows)}:{col}{max(rows)})')
    for row in range(3, sheet.max_row + 1):
        label = _text(sheet.cell(row, 5).value).lower().replace('ё', 'е')
        for i, start in enumerate(starts):
            col = get_column_letter(start)
            if label in ('волонтеры всего / смена', 'тим-лидеров всего / смена'):
                members = lead_rows if label.startswith('тим-') else all_rows
                put(row, start, '=' + '+'.join(f'{col}{r}' for r in members) if members else '=0')
            elif label.startswith('факт набрано / смена'):
                put(row, start, plan.get('stats', {}).get(plan['dates'][i], {}).get('recruited', 0))
            elif label.startswith('факт check-in / смена'):
                put(row, start, plan.get('stats', {}).get(plan['dates'][i], {}).get('checked_in', 0))
            elif label in ('набор в %', 'явка в % от плана'):
                metric = 'recruited' if label == 'набор в %' else 'checked_in'
                count = plan.get('stats', {}).get(plan['dates'][i], {}).get(metric, 0)
                planned = sum(sum(q['count'] or 0 for q in p['days'][i]['quantities'][1:]) if any(q['count'] is not None for q in p['days'][i]['quantities'][1:]) else p['days'][i]['quantities'][0]['count'] or 0 for d in plan['directions'] for p in d['positions'])
                put(row, start, count / planned if planned else 0)
            elif label in ('волонтеры всего', 'тим-лидеры всего'):
                if i == 0:
                    members = lead_rows if label.startswith('тим-') else all_rows
                    put(row, start, '=' + '+'.join(f'{get_column_letter(c)}{r}' for c in starts for r in members) if members else '=0')
                else:
                    put(row, start, None)
            elif label == 'волонтеры всего, уникальные':
                put(row, start, plan.get('stats', {}).get('unique_people', 0) if i == 0 else None)
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
