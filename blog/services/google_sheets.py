"""Google Sheets REST: только разрешённые Google URL, ключи не попадают в HTML/логи."""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
from io import BytesIO
import json
import re
from urllib.parse import urlparse, parse_qs

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from google.auth.exceptions import GoogleAuthError
import requests
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import to_excel

from data_base import data_controller as dc
from .fap_workbook import META_PREFIX, normalized_name


API = 'https://sheets.googleapis.com/v4/spreadsheets/'


def parse_sheet_url(value):
    parsed = urlparse(value.strip())
    match = re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]{20,128})(?:/[^?#]*)?', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'docs.google.com' or not match:
        raise ValidationError('Вставьте ссылку https://docs.google.com/spreadsheets/d/…/edit.')
    gid = parse_qs(parsed.fragment).get('gid', parse_qs(parsed.query).get('gid', [None]))[0]
    if gid is not None and not str(gid).isdigit():
        raise ValidationError('Некорректный номер вкладки Google Таблицы.')
    return match[1], int(gid) if gid is not None else None


def _fernet():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('vc-google-sheets:' + settings.SECRET_KEY).encode()).digest()))


def encrypt_key(info):
    return _fernet().encrypt(json.dumps(info).encode()).decode()


def decrypt_key(value):
    try:
        return json.loads(_fernet().decrypt(value.encode()))
    except (InvalidToken, ValueError):
        raise ValidationError('Ключ Google не удалось расшифровать. Загрузите JSON-ключ повторно.')


def save_credentials(operator, content):
    from .event_sheets import _manager
    _manager(operator)
    try:
        info = json.loads(content)
        if not isinstance(info, dict) or info.get('type') != 'service_account' or not isinstance(info.get('client_email'), str) or not info['client_email'].endswith('.gserviceaccount.com'):
            raise ValueError
        # Не доверяем адресам сервера токенов из загружаемого документа.
        info['token_uri'] = 'https://oauth2.googleapis.com/token'
        Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    except (ValueError, TypeError, KeyError):
        raise ValidationError('Нужен действительный JSON-ключ сервисного аккаунта Google.')
    return dc.save_google_sheets_connection(encrypt_key(info), info['client_email'], operator)


def _hex(color):
    return ''.join(f'{round(color.get(k, 0) * 255):02X}' for k in ('red', 'green', 'blue'))


def _rgb(color):
    if color is None or color.type != 'rgb' or not isinstance(color.rgb, str):
        return None
    raw = color.rgb[-6:]
    return {k: int(raw[i:i + 2], 16) / 255 for k, i in (('red', 0), ('green', 2), ('blue', 4))}


def _shifts_sheet(payload):
    matching = [sheet for sheet in payload.get('sheets', [])
                if normalized_name(sheet['properties']['title']) == normalized_name('Смены')]
    if len(matching) != 1:
        raise ValidationError('В Google Таблице нужна одна вкладка «Смены» (регистр и пробелы не учитываются).')
    return matching[0]


def grid_to_xlsx(payload):
    """Только выбранная вкладка «Смены»; скрытые ID берутся из DeveloperMetadata."""
    source = _shifts_sheet(payload)
    wb = Workbook()
    sheet = wb.active
    sheet.title = 'Смены'
    for block in source.get('data', []):
        row_start, col_start = block.get('startRow', 0), block.get('startColumn', 0)
        rows = block.get('rowData', [])
        if sum(len(row.get('values', [])) for row in rows) > 250000:
            raise ValidationError('Слишком большой лист «Смены».')
        for ri, row in enumerate(rows, row_start + 1):
            for ci, value in enumerate(row.get('values', []), col_start + 1):
                cell = sheet.cell(ri, ci)
                entered = value.get('userEnteredValue', value.get('effectiveValue', {}))
                cell.value = next(iter(entered.values()), None)
                if 'formulaValue' in entered:
                    cell.value = entered['formulaValue']
                fmt = value.get('userEnteredFormat', {})
                num = fmt.get('numberFormat', {})
                if num.get('pattern'):
                    cell.number_format = num['pattern']
                text = fmt.get('textFormat', {})
                cell.font = Font(name=text.get('fontFamily', 'Arial'), size=text.get('fontSize', 10), bold=text.get('bold', False), italic=text.get('italic', False),
                    color=_hex(text['foregroundColor']) if 'foregroundColor' in text else None)
                color = fmt.get('backgroundColorStyle', {}).get('rgbColor', fmt.get('backgroundColor'))
                if color:
                    cell.fill = PatternFill('solid', fgColor=_hex(color))
                cell.alignment = Alignment(horizontal=fmt.get('horizontalAlignment', 'GENERAL').lower(),
                    vertical={'MIDDLE': 'center'}.get(fmt.get('verticalAlignment'), fmt.get('verticalAlignment', 'BOTTOM').lower()),
                    wrap_text=fmt.get('wrapStrategy') == 'WRAP', text_rotation=fmt.get('textRotation', {}).get('angle', 0))
                borders = {}
                for side, border in fmt.get('borders', {}).items():
                    if side in ('top', 'bottom', 'left', 'right'):
                        style = {'SOLID': 'thin', 'SOLID_MEDIUM': 'medium', 'SOLID_THICK': 'thick', 'DASHED': 'dashed', 'DOTTED': 'dotted', 'DOUBLE': 'double'}.get(border.get('style'))
                        borders[side] = Side(style=style, color=_hex(border.get('color', {})))
                cell.border = Border(**borders)
                if value.get('note'):
                    cell.comment = Comment(value['note'], 'Google Sheets')
        for i, dimension in enumerate(block.get('rowMetadata', []), row_start + 1):
            if 'pixelSize' in dimension:
                sheet.row_dimensions[i].height = dimension['pixelSize'] * .75
        for i, dimension in enumerate(block.get('columnMetadata', []), col_start + 1):
            if 'pixelSize' in dimension:
                sheet.column_dimensions[get_column_letter(i)].width = max(0, (dimension['pixelSize'] - 5) / 7)
    for area in source.get('merges', []):
        sheet.merge_cells(start_row=area.get('startRowIndex', 0) + 1, end_row=area['endRowIndex'], start_column=area.get('startColumnIndex', 0) + 1, end_column=area['endColumnIndex'])
    props = source['properties'].get('gridProperties', {})
    if props.get('frozenRowCount') or props.get('frozenColumnCount'):
        sheet.freeze_panes = sheet.cell(props.get('frozenRowCount', 0) + 1, props.get('frozenColumnCount', 0) + 1).coordinate
    for item in source.get('developerMetadata', []) + payload.get('developerMetadata', []):
        if item.get('metadataKey') != 'vc_fap_position':
            continue
        location = item.get('location', {}).get('dimensionRange', {})
        if location.get('sheetId') != source['properties']['sheetId'] or location.get('dimension') != 'ROWS':
            continue
        cell = sheet.cell(location['startIndex'] + 1, 5)
        previous = cell.comment.text if cell.comment else ''
        note = previous.split(META_PREFIX, 1)[0].strip()
        data = json.loads(previous.split(META_PREFIX, 1)[1].splitlines()[0]) if META_PREFIX in previous else {}
        data.update(json.loads(item['metadataValue']))
        cell.comment = Comment((note + '\n' if note else '') + META_PREFIX + json.dumps(data, separators=(',', ':')), 'VC Platform')
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue(), source['properties']['sheetId']


def xlsx_update_requests(content, sheet_id, original=None):
    """Один атомарный batch: значения, стили, merges, размеры и ID, без новых вкладок."""
    sheet = load_workbook(BytesIO(content))['Смены']
    original = original or {}
    requests_list = []
    old_source = next((s for s in original.get('sheets', []) if normalized_name(s['properties']['title']) == normalized_name('Смены')), {})
    grid = old_source.get('properties', {}).get('gridProperties', {})
    requests_list.append({'updateSheetProperties': {'properties': {'sheetId': sheet_id, 'gridProperties': {
        'rowCount': max(sheet.max_row, grid.get('rowCount', 1)), 'columnCount': max(sheet.max_column, grid.get('columnCount', 1)),
        'frozenRowCount': sheet[sheet.freeze_panes].row - 1 if sheet.freeze_panes else 0,
        'frozenColumnCount': sheet[sheet.freeze_panes].column - 1 if sheet.freeze_panes else 0,
    }}, 'fields': 'gridProperties'}})
    for area in old_source.get('merges', []):
        requests_list.append({'unmergeCells': {'range': {**area, 'sheetId': sheet_id}}})
    # Старые строки убираются только на выбранном листе, оформление задаётся ниже.
    requests_list.append({'updateCells': {'range': {'sheetId': sheet_id}, 'fields': 'userEnteredValue,note'}})
    old_formats = {}
    for block in old_source.get('data', []):
        for ri, row in enumerate(block.get('rowData', []), block.get('startRow', 0)):
            for ci, item in enumerate(row.get('values', []), block.get('startColumn', 0)):
                old_formats[ri, ci] = item.get('userEnteredFormat', {})
    same_geometry = bool(old_source) and sorted((a.get('startRowIndex', 0), a['endRowIndex'], a.get('startColumnIndex', 0), a['endColumnIndex']) for a in old_source.get('merges', [])) == sorted((a.min_row - 1, a.max_row, a.min_col - 1, a.max_col) for a in sheet.merged_cells.ranges)
    rows = []
    for row in sheet:
        cells = []
        for cell in row:
            item = {}
            val = cell.value
            if val is not None:
                if isinstance(val, datetime):
                    item['userEnteredValue'] = {'numberValue': to_excel(val)}
                elif isinstance(val, bool):
                    item['userEnteredValue'] = {'boolValue': val}
                elif isinstance(val, (int, float)):
                    item['userEnteredValue'] = {'numberValue': val}
                elif cell.data_type == 'f':
                    item['userEnteredValue'] = {'formulaValue': val}
                else:
                    item['userEnteredValue'] = {'stringValue': str(val)}
            font = cell.font
            fmt = {'textFormat': {'fontFamily': font.name or 'Arial', 'fontSize': max(1, round(font.sz or 10)), 'bold': bool(font.b), 'italic': bool(font.i)},
                   'wrapStrategy': 'WRAP' if cell.alignment.wrap_text else 'OVERFLOW_CELL',
                   'verticalAlignment': {'center': 'MIDDLE', 'top': 'TOP'}.get(cell.alignment.vertical, 'BOTTOM')}
            if cell.alignment.horizontal in ('left', 'center', 'right'):
                fmt['horizontalAlignment'] = cell.alignment.horizontal.upper()
            if _rgb(font.color):
                fmt['textFormat']['foregroundColor'] = _rgb(font.color)
            if cell.fill.patternType == 'solid' and _rgb(cell.fill.fgColor):
                fmt['backgroundColor'] = _rgb(cell.fill.fgColor)
            if cell.number_format != 'General':
                fmt['numberFormat'] = {'type': 'DATE' if cell.is_date else 'NUMBER', 'pattern': cell.number_format}
            borders = {}
            for side in ('top', 'bottom', 'left', 'right'):
                border = getattr(cell.border, side)
                if border and border.style:
                    borders[side] = {'style': {'thin': 'SOLID', 'medium': 'SOLID_MEDIUM', 'thick': 'SOLID_THICK', 'dashed': 'DASHED', 'dotted': 'DOTTED', 'double': 'DOUBLE'}.get(border.style, 'SOLID'), 'color': _rgb(border.color) or {'red': 0, 'green': 0, 'blue': 0}}
            if borders:
                fmt['borders'] = borders
            item['userEnteredFormat'] = deepcopy(old_formats.get((cell.row - 1, cell.column - 1), fmt)) if same_geometry else fmt
            if cell.comment:
                # Полные ID смен хранятся в примечании ячейки: они не расходуют
                # ограниченные 30 000 символов DeveloperMetadata на весь лист.
                item['note'] = cell.comment.text
            cells.append(item)
        rows.append({'values': cells})
    requests_list.append({'updateCells': {'start': {'sheetId': sheet_id, 'rowIndex': 0, 'columnIndex': 0}, 'rows': rows, 'fields': 'userEnteredValue,userEnteredFormat,note'}})
    for area in sheet.merged_cells.ranges:
        requests_list.append({'mergeCells': {'range': {'sheetId': sheet_id, 'startRowIndex': area.min_row - 1, 'endRowIndex': area.max_row, 'startColumnIndex': area.min_col - 1, 'endColumnIndex': area.max_col}, 'mergeType': 'MERGE_ALL'}})
    if not same_geometry:
        for i, dimension in sheet.row_dimensions.items():
            if dimension.height:
                requests_list.append({'updateDimensionProperties': {'range': {'sheetId': sheet_id, 'dimension': 'ROWS', 'startIndex': i - 1, 'endIndex': i}, 'properties': {'pixelSize': round(dimension.height / .75)}, 'fields': 'pixelSize'}})
        for column, dimension in sheet.column_dimensions.items():
            from openpyxl.utils import column_index_from_string
            i = column_index_from_string(column)
            requests_list.append({'updateDimensionProperties': {'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': i - 1, 'endIndex': i}, 'properties': {'pixelSize': round(dimension.width * 7 + 5)}, 'fields': 'pixelSize'}})
    requests_list.append({'deleteDeveloperMetadata': {'dataFilter': {'developerMetadataLookup': {'metadataKey': 'vc_fap_position', 'metadataLocation': {'sheetId': sheet_id}, 'locationMatchingStrategy': 'INTERSECTING_LOCATION'}}}})
    existing_chars = sum(len(m.get('metadataKey', '')) + len(m.get('metadataValue', '')) for m in old_source.get('developerMetadata', []) if m.get('metadataKey') != 'vc_fap_position')
    metadata_budget = max(0, 30000 - existing_chars)
    for row in sheet:
        cell = row[4]
        if cell.comment and META_PREFIX in cell.comment.text:
            raw = cell.comment.text.split(META_PREFIX, 1)[1].splitlines()[0]
            data = json.loads(raw)
            compact = json.dumps({k: data[k] for k in ('position', 'direction')}, separators=(',', ':'))
            cost = len('vc_fap_position') + len(compact)
            if cost <= metadata_budget:
                requests_list.append({'createDeveloperMetadata': {'developerMetadata': {'metadataKey': 'vc_fap_position', 'metadataValue': compact, 'visibility': 'DOCUMENT', 'location': {'dimensionRange': {'sheetId': sheet_id, 'dimension': 'ROWS', 'startIndex': cell.row - 1, 'endIndex': cell.row}}}}})
                metadata_budget -= cost
    return requests_list


class GoogleSheetClient:
    def __init__(self):
        config = dc.google_sheets_connection()
        self.session = None
        self.payload = None
        if config:
            info = decrypt_key(config.credentials_encrypted)
            self.session = AuthorizedSession(Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/spreadsheets']))

    def _request(self, method, url, **kwargs):
        try:
            response = (self.session or requests).request(method, url, timeout=20, **kwargs)
            if response.status_code != 200:
                messages = {401: 'Ключ Google отклонён. Подключите актуальный ключ.', 403: 'Google не дал доступ. Включите Sheets API и выдайте сервисному аккаунту доступ редактора.', 404: 'Таблица не найдена или недоступна сервисному аккаунту.'}
                raise ValidationError(messages.get(response.status_code, 'Google временно не выполнил запрос. Повторите позже.'))
            return response
        except (requests.RequestException, GoogleAuthError):
            # Текст исключения библиотеки может включать токен/ответ Google.
            raise ValidationError('Не удалось связаться с Google. Проверьте сеть и настройки интеграции.') from None

    def read_google(self, spreadsheet_id, sheet_id=None):
        if self.session:
            metadata = self._request('GET', API + spreadsheet_id, params={'fields': 'sheets(properties(sheetId,title))'}).json()
            title = _shifts_sheet(metadata)['properties']['title']
            escaped = title.replace("'", "''")
            self.payload = self._request('GET', API + spreadsheet_id, params={'ranges': f"'{escaped}'", 'includeGridData': 'true'}).json()
            return grid_to_xlsx(self.payload)
        params = {'format': 'xlsx'}
        if sheet_id is not None:
            params['gid'] = sheet_id
        response = self._request('GET', f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export', params=params)
        if len(response.content) > 10 * 1024 * 1024:
            raise ValidationError('Таблица превышает 10 МБ. Загрузите меньший XLSX.')
        return response.content, sheet_id

    def write_google(self, spreadsheet_id, sheet_id, content):
        if not self.session:
            raise ValidationError('Для отправки изменений подключите JSON-ключ Google через «Настроить Google» и выдайте аккаунту доступ редактора.')
        self._request('POST', API + spreadsheet_id + ':batchUpdate', json={'requests': xlsx_update_requests(content, sheet_id, self.payload)})

    def close(self):
        if self.session:
            self.session.close()
