"""Поэтапная миграция старых баз (documentation/legacy-migration.md).

Этапы независимы и повторяемы: база → люди → колонки в мероприятие → ФиП →
сопоставление уникальных значений → загрузка колонок (повтор без дублей, перенос
при пересопоставлении, откат). Решения пользователя от 2026-11-11:
- позиция — набор тим-лидера из ФиП; значение ячейки сопоставляет человек;
- тим-лидер из базы: участие + EventStaff на позиции + глобальная роль;
- часы — по смене ФиП; правки сотрудников (статус, ручные часы) не трогаем;
- колонка без явной даты ждёт даты от человека;
- баз несколько, один человек — один аккаунт (отпечатки контактов).
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
import hashlib
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from data_base import data_controller as dc
from blog.services import event_sheets
from blog.services.fap_workbook import MSK, is_team_lead_text, read_xlsx, normalized_name, _leader_row_label
from blog.services.legacy_import import _contact_keys, identity_key, match_rows
from blog.services.legacy_workbook import read_legacy_workbook, split_code, value_key
from blog.services.position_pool import assign_function, classify, function_category, position_function, remember_positions
from blog.services.profile_conflicts import sync_profile_from_base
from blog.services.roles import has_manager_access
from blog.services.stats import recalc_user_aggregates


SUGGEST_THRESHOLD = 0.45
CODELESS_THRESHOLD = 0.85


def _manager(operator):
    if not has_manager_access(operator):
        raise PermissionDenied('Миграцией старой базы управляет менеджер.')


def _hash(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


# --- Этап 1: база и люди -------------------------------------------------------

def detect_base_year(file_name, headers, default):
    """Год базы: из имени файла, иначе самый частый явный год в заголовках колонок."""
    import re
    named = guess_year(file_name, None)
    if named:
        return named
    years = Counter(int(match) for header in headers for match in re.findall(r'(?<!\d)(20\d{2})(?!\d)', header or ''))
    return years.most_common(1)[0][0] if years else default


WORKBOOK_KINDS = {'база': 'base', 'смены': 'fap'}


def workbook_kind(content):
    """«base» (есть лист «База»), «fap» (есть лист «Смены») или None — по названиям
    листов, без разбора содержимого: файл попадёт в нужное место, в какую бы форму
    загрузки его ни отправили."""
    import re
    from io import BytesIO
    from zipfile import BadZipFile, ZipFile
    from xml.etree import ElementTree as ET
    try:
        with ZipFile(BytesIO(content)) as archive:
            book = ET.fromstring(archive.read('xl/workbook.xml'))
    except (BadZipFile, KeyError, ET.ParseError, OSError):
        return None
    names = {re.sub(r'[\W_]+', '', normalized_name(sheet.attrib.get('name', '')))
             for sheet in book.iter() if sheet.tag.endswith('}sheet')}
    if 'база' in names:
        return 'base'
    if 'смены' in names:
        return 'fap'
    return None


def guess_year(file_name, default):
    import re
    match = re.search(r'20\d{2}', file_name or '')
    return int(match[0]) if match else default


@transaction.atomic
def upload_base(operator, content, file_name, year=None):
    """Сохранить файл и колонки базы. Ничего не меняет в профилях и мероприятиях.

    Год (одна база = один год) — указанный человеком, иначе определяется сам: из
    имени файла, затем самый частый год в датах заголовков колонок, иначе текущий."""
    _manager(operator)
    content_hash = _hash(content)
    if dc.legacy_bases_qs().filter(content_hash=content_hash).exists():
        raise ValidationError('Эта база уже загружена — откройте её в списке баз.')
    max_rows = int(dc.get_const('legacy_import_max_rows', default=10000))
    fallback = _now().astimezone(MSK).year
    parsed = read_legacy_workbook(content, max_rows=max_rows, year=int(year or fallback))
    if not year:
        year = detect_base_year(file_name, [column['header'] for column in parsed['columns']], fallback)
        if year != fallback:
            parsed = read_legacy_workbook(content, max_rows=max_rows, year=year)
    base = dc.create_legacy_base(year=int(year), file_name=file_name, content=content,
                                 content_hash=content_hash, parsed=parsed, operator=operator)
    for column in parsed['columns']:
        counts = Counter(item['description'] for row in parsed['rows'] for item in row['assignments']
                         if item['column'] == column['index'])
        dc.create_legacy_base_column(base, index=column['index'], header=column['header'],
                                     title_hint=column['group'], day=column['day'], value_counts=dict(counts))
    return base


def pending_people_rows(base):
    """Строки базы, ещё не связанные с аккаунтами (повтор/догрузка начинается с них)."""
    loaded = set(dc.legacy_base_people_qs().filter(base=base).values_list('row_number', flat=True))
    return [row for row in base.parsed['rows'] if row['number'] not in loaded]


def new_people_result():
    return {'created': 0, 'existing': 0, 'conflicts': 0, 'updated': 0, 'created_ids': [], 'rows': []}


def load_people_rows(operator, base, rows, known, result):
    """Порция строк базы → аккаунты. known — контакты → User между порциями."""
    matches, errors = match_rows({'rows': rows})
    if errors:
        raise ValidationError(errors[0])
    for row in rows:
        profile = row['profile']
        contacts = _contact_keys(profile, row['number'])
        seen = {known[c].pk: known[c] for c in contacts if c in known}
        if matches[row['number']]:
            seen[matches[row['number']].pk] = matches[row['number']]
        if len(seen) > 1:
            raise ValidationError(f'Строка {row["number"]}: контакты указывают на разные аккаунты.')
        user = next(iter(seen.values()), None)
        if user is None:
            birthday = date.fromisoformat(profile['birthday']) if profile['birthday'] else None
            user = dc.create_user(telegram_id='legacy:' + uuid.uuid4().hex, telegram_username=profile['telegram_username'],
                                  first_name=profile['first_name'], last_name=profile['last_name'], phone=profile['phone'],
                                  email=profile['email'], vk_username=profile['VK_username'], birthday=birthday)
            fields = {name: value for name, value in profile.items() if name not in
                      ('first_name', 'last_name', 'phone', 'email', 'telegram_username', 'VK_username', 'birthday')}
            fields['registration_status'] = 'registered'
            dc.complete_legacy_user(user, fields, operator)
            result['created'] += 1
            result['created_ids'].append(user.pk)
        else:
            outcome = sync_profile_from_base(operator, user, profile, base)
            result['existing'] += 1
            result['conflicts'] += outcome['conflicts']
            result['updated'] += outcome['updated']
        for contact in contacts:
            known[contact] = user
        dc.create_legacy_identity(identity_key(profile, row['number']), user, row['reported_age'], operator)
        dc.record_legacy_base_person(base, row['number'], user)
        result['rows'].append(row['number'])
        for kind, comment in row['comments'].items():
            if comment:
                dc.ensure_legacy_comment(user, kind, comment, operator)
    return result


def finish_people(operator, base, result):
    if not base.people_loaded_at:
        dc.mark_base_people_loaded(base, operator)
    result['skipped'] = base.parsed.get('skipped_rows', 0)
    return result


@transaction.atomic
def load_people(operator, base):
    """Анкеты и комментарии строк базы за один раз (фоновая задача — порциями)."""
    _manager(operator)
    result = load_people_rows(operator, base, pending_people_rows(base), {}, new_people_result())
    return finish_people(operator, base, result)


# --- Этап 2: колонки → мероприятие --------------------------------------------

@transaction.atomic
def create_event_from_columns(operator, base, column_ids, title, group=None):
    _manager(operator)
    columns = list(dc.legacy_base_columns_qs().filter(base=base, pk__in=column_ids))
    if not columns:
        raise ValidationError('Отметьте хотя бы одну колонку базы.')
    if any(c.loaded_at for c in columns if c.event_group_id and (group is None or c.event_group_id != group.pk)):
        raise ValidationError('Колонка уже загружена в другое мероприятие. Сначала откатите её загрузку.')
    if group is None:
        title = (title or '').strip() or columns[0].title_hint or 'Мероприятие из базы'
        group = dc.create_legacy_group(title[:255], operator)
    for column in columns:
        dc.save_legacy_column(column, operator, event_group=group)
    return group


def set_column(operator, column, **fields):
    _manager(operator)
    allowed = {key: value for key, value in fields.items() if key in ('day', 'skipped', 'event_group')}
    if 'day' in allowed and column.loaded_at and allowed['day'] != column.day:
        raise ValidationError('Дату загруженной колонки меняйте на странице смены или откатите загрузку.')
    return dc.save_legacy_column(column, operator, **allowed)


# --- Этап 3: ФиП ---------------------------------------------------------------

def _carry_ids_by_name(group, plan):
    """Архивный ФиП без служебных ID: сопоставить с прежней версией по названию."""
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    if not link or not link.baseline:
        return plan
    previous = link.baseline['directions']
    incoming_ids = {d['id'] for d in plan['directions']}
    if incoming_ids & {d['id'] for d in previous}:
        return plan
    by_name = defaultdict(list)
    for direction in previous:
        by_name[normalized_name(direction['name'])].append(direction)
    for direction in plan['directions']:
        candidates = by_name.get(normalized_name(direction['name']), [])
        if len(candidates) != 1:
            continue
        old = candidates[0]
        direction['id'] = old['id']
        new_position, old_position = direction['positions'][0], old['positions'][0]
        new_position['id'] = old_position['id']
        old_days = {day['date']: day for day in old_position['days']}
        for day in new_position['days']:
            old_shifts = old_days.get(day['date'], {}).get('shifts', [])
            if len(day['shifts']) == 1 and len(old_shifts) == 1:
                day['shifts'][0]['id'] = old_shifts[0]['id']
    return plan


def document_plan(document):
    """Разобранный план ФиП. У файлов, загруженных до библиотеки (0049), плана нет —
    разбираем сохранённый файл один раз и запоминаем (год — из имени файла или
    мероприятия). Нечитаемый файл — пустой план без дней."""
    if document.plan.get('directions'):
        return document.plan
    group_year = _group_year(document.event_group) if document.event_group_id else _now().year
    content = document.content if 'content' not in document.get_deferred_fields() else         dc.fap_documents_qs().values_list('content', flat=True).get(pk=document.pk)
    try:
        plan = read_xlsx(bytes(content), default_year=guess_year(document.file_name, group_year))
    except ValidationError:
        return {}
    dc.save_fap_plan(document, plan, fap_title(document.file_name) if not document.title else document.title)
    return plan


def fap_title(file_name):
    """«Ночной 2026 - Функции и позиции .xlsx» → «Ночной 2026»."""
    import re
    stem = re.sub(r'\.xlsx$', '', file_name or '', flags=re.I).strip(' _')
    return re.split(r'\s+-\s+функции', stem, flags=re.I)[0].strip(' _-') or stem


def upload_fap_files(operator, files, default_year=None):
    """Положить файлы ФиП в библиотеку. Каждый файл проверяется отдельно:
    ошибка одного не мешает остальным; возвращает [(имя, документ|None, ошибка)]."""
    _manager(operator)
    results = []
    for name, content in files:
        year = guess_year(name, default_year or _now().year)
        try:
            plan = read_xlsx(content, default_year=year)
        except ValidationError as error:
            results.append((name, None, ' '.join(error.messages)))
            continue
        content_hash = _hash(content)
        existing = dc.fap_documents_qs().filter(content_hash=content_hash).defer('content').first()
        if existing:
            results.append((name, existing, 'Этот файл уже загружен.'))
            continue
        document = dc.create_library_fap(file_name=name, title=fap_title(name), content=content,
                                         content_hash=content_hash, plan=plan, operator=operator)
        results.append((name, document, ''))
    return results


@transaction.atomic
def apply_fap(operator, document, group):
    """Привязать документ библиотеки к мероприятию и создать позиции/смены."""
    _manager(operator)
    document = dc.fap_documents_qs().select_for_update().get(pk=document.pk)
    if document.event_group_id and document.event_group_id != group.pk:
        raise ValidationError(f'ФиП «{document.title}» уже относится к мероприятию «{document.event_group.title}».')
    if document.event_group_id == group.pk and document.applied_at:
        return document
    stored = document_plan(document)
    if not stored:
        raise ValidationError(f'ФиП «{document.file_name}» не читается — загрузите файл заново.')
    plan = _carry_ids_by_name(group, deepcopy(stored))
    event_sheets.import_plan(operator, group, plan, bytes(document.content), document.file_name)
    dc.attach_fap_document(document, group, plan['warnings'], operator)
    remember_positions(stored, operator)
    return document


def _group_year(group):
    day = dc.legacy_base_columns_qs().filter(event_group=group, day__isnull=False).values_list('day', flat=True).first()
    if day:
        return day.year
    base_year = dc.legacy_base_columns_qs().filter(event_group=group).values_list('base__year', flat=True).first()
    return base_year or _now().year


@transaction.atomic
def attach_fap(operator, group, content, file_name):
    """Загрузить ФиП сразу в мероприятие (новая версия): файл хранится всегда."""
    _manager(operator)
    same = dc.fap_documents_qs().filter(event_group=group, content_hash=_hash(content)).defer('content').first()
    if same and same.applied_at:
        return same  # тот же файл уже применён — новая версия-дубль не нужна
    year = guess_year(file_name, _group_year(group))
    plan = read_xlsx(content, default_year=year)
    document = dc.create_library_fap(file_name=file_name, title=fap_title(file_name), content=content,
                                     content_hash=_hash(content), plan=plan, operator=operator)
    return apply_fap(operator, document, group)


def fap_choices():
    """Варианты «ФиП · день» для таблицы сопоставления колонок базы."""
    choices = []
    for document in dc.fap_documents_qs().defer('content').select_related('event_group').order_by('title', '-version'):
        days = document_plan(document).get('dates', [])
        label = document.title + (f' (v{document.version} · {document.event_group.title})' if document.event_group_id else '')
        choices.append({'document': document, 'label': label,
                        'days': [{'value': f'{document.pk}|{day}', 'day': date.fromisoformat(day)} for day in days]})
    return choices


def suggest_fap(column, choices):
    """Подсказка ФиП по дате колонки: единственный файл с этим днём."""
    if not column.day:
        return ''
    found = [day['value'] for choice in choices for day in choice['days'] if day['day'] == column.day]
    return found[0] if len(found) == 1 else ''


@transaction.atomic
def map_columns_to_fap(operator, base, choices):
    """choices: {column_id: 'doc_id|YYYY-MM-DD' или ''}. Колонка получает мероприятие
    ФиП (создаётся по названию файла) и дату дня ФиП; ФиП применяется один раз."""
    _manager(operator)
    columns = {str(c.pk): c for c in dc.legacy_base_columns_qs().filter(base=base)}
    documents = {}
    for column_id, value in choices.items():
        column = columns.get(str(column_id))
        if column is None:
            continue
        if not value:
            if column.fap_document_id and not column.loaded_at:
                dc.save_legacy_column(column, operator, fap_document=None)
            continue
        document_id, raw_day = value.split('|', 1)
        document = documents.get(document_id) or dc.fap_documents_qs().defer('content').select_related('event_group').get(pk=document_id)
        documents[document_id] = document
        day = date.fromisoformat(raw_day)
        if day.isoformat() not in document_plan(document).get('dates', []):
            raise ValidationError(f'В ФиП «{document.title}» нет дня {day:%d.%m.%Y}.')
        group = document.event_group or column.event_group
        if column.event_group_id and group and column.event_group_id != group.pk:
            raise ValidationError(f'Колонка «{column.header}» уже в мероприятии «{column.event_group.title}», '
                                  f'а ФиП «{document.title}» — в «{group.title}».')
        if column.loaded_at and (column.day != day or column.event_group_id != (group.pk if group else None)):
            raise ValidationError(f'Колонка «{column.header}» уже загружена — сначала откатите её.')
        if group is None:
            group = dc.create_legacy_group(document.title[:255], operator)
        if document.event_group_id != group.pk or not document.applied_at:
            apply_fap(operator, document, group)
            document.event_group, document.event_group_id = group, group.pk
        dc.save_legacy_column(column, operator, event_group=group, day=day, fap_document=document)
    return True


# --- Этап 4: сопоставление ------------------------------------------------------

def _position_hints(group):
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    baseline = {}
    for direction in (link.baseline.get('directions', []) if link else []):
        for position in direction['positions']:
            baseline[position['id']] = position
    sheets = {s.event_id: str(s.source_key) for s in dc.sheet_positions_qs().filter(event__event_group=group)}
    functions = {link.event_id: link.category for link in dc.event_category_maps_qs()
                 .filter(event__event_group=group, category__kind='function').select_related('category').order_by('pk')}
    hints = []
    for event in dc.events_qs().filter(event_group=group).order_by('pk'):
        source = baseline.get(sheets.get(event.pk), {})
        base_name = source.get('base_name') or event.title.split(' · ', 1)[0]
        texts = [event.title, base_name] + list(source.get('source_rows', []))
        hints.append({'event': event, 'code': source.get('code', ''), 'function': functions.get(event.pk),
                      'texts': [value_key(split_code(text)[1]) for text in texts if text]})
    return hints


def suggest(raw, hints):
    """Подсказка позиции: код ФиП сужает выбор, затем ближайший текст строк ФиП."""
    code, rest = split_code(raw)
    target = value_key(rest)
    major = code.split('.')[0] if code else ''
    best, best_score = None, 0.0
    for hint in hints:
        score = max((SequenceMatcher(None, target, text).ratio() for text in hint['texts']), default=0.0)
        if code and hint['code']:
            # Точный код ФиП надёжнее текста: в базе встречаются подписи вроде
            # «10.10 … пункт питания (ПО6)», где по коду это пункт освежения ПО6.
            if hint['code'] == code:
                score += 0.5
            elif hint['code'].split('.')[0] == major:
                score += 0.05
            else:
                score -= 0.25
        if score > best_score:
            best, best_score = hint['event'], score
    role = 'team_lead' if is_team_lead_text(raw) else 'volunteer'
    # Без кода нечему сузить выбор — подсказываем только почти дословное совпадение.
    threshold = SUGGEST_THRESHOLD if code else CODELESS_THRESHOLD
    position = best if best_score >= threshold else None
    function = next((h['function'] for h in hints if position is not None and h['event'] == position), None)
    if function is None:
        name = classify(rest or raw)
        function = next((c for c in dc.event_functions_qs() if c.name == name), None) if name else None
    return {'position': position, 'score': round(best_score, 2), 'role': role, 'function': function}


def new_position_title(raw):
    _, rest = split_code(raw)
    if is_team_lead_text(rest):
        label = _leader_row_label([{'name': rest, 'is_team_lead_role': True}])
        return label or rest
    return rest or raw


def mapping_table(group):
    """Уникальные значения всех колонок мероприятия с числом людей по колонкам."""
    columns = list(dc.legacy_base_columns_qs().filter(event_group=group, skipped=False).select_related('base').order_by('day', 'index'))
    mappings = {m.value_key: m for m in dc.legacy_value_mappings_qs().filter(event_group=group).select_related('position')}
    hints = _position_hints(group)
    values = {}
    for column in columns:
        for raw, count in column.value_counts.items():
            key = value_key(raw)
            item = values.setdefault(key, {'key': key, 'raw': raw, 'counts': [], 'total': 0})
            item['counts'].append((column, count))
            item['total'] += count
    rows = []
    for key, item in sorted(values.items(), key=lambda pair: (split_code(pair[1]['raw'])[0] or '~', pair[1]['raw'])):
        mapping = mappings.get(key)
        suggestion = suggest(item['raw'], hints)
        item.update(mapping=mapping, suggestion=suggestion, new_title=new_position_title(item['raw']))
        mapped_function = position_function(mapping.position) if mapping and mapping.position_id else None
        function = mapped_function or suggestion['function']
        item['function_selected'] = str(function.pk) if function else ''
        if mapping:
            item['selected'] = 'skip' if mapping.skip else str(mapping.position_id or '')
            item['selected_role'] = mapping.role
        else:
            item['selected'] = str(suggestion['position'].pk) if suggestion['position'] else ''
            item['selected_role'] = suggestion['role']
        rows.append(item)
    # Сверху то, что требует решения: без выбора → с подсказкой → сохранённое.
    rows.sort(key=lambda row: 2 if row['mapping'] else (1 if row['selected'] else 0))
    return rows


@transaction.atomic
def save_mappings(operator, group, items):
    """items: key, raw, target ('', 'skip', 'new' или id позиции), role, title,
    function (id функции пула или 'new') и function_name — функция новой позиции."""
    _manager(operator)
    positions = {str(e.pk): e for e in dc.events_qs().filter(event_group=group)}
    created = {}
    for item in items:
        target = (item.get('target') or '').strip()
        role = item.get('role') if item.get('role') in ('volunteer', 'team_lead') else 'volunteer'
        if not target:
            continue
        position = None
        if target == 'new':
            title = (item.get('title') or new_position_title(item['raw'])).strip()[:255]
            position = created.get(normalized_name(title)) or next(
                (e for e in positions.values() if normalized_name(e.title) == normalized_name(title)), None)
            if position is None:
                chosen = (item.get('function') or '').strip()
                if chosen == 'new':
                    category = function_category(item.get('function_name') or '', operator)
                else:
                    category = dc.event_functions_qs().filter(pk=chosen).first() if chosen.isdigit() else None
                position = dc.create_legacy_position(group, title, operator)
                function = assign_function(position, item['raw'], category=category)
                if function is not None:
                    dc.ensure_position_template(function, title, operator)
                positions[str(position.pk)] = position
            created[normalized_name(title)] = position
        elif target != 'skip':
            position = positions.get(target)
            if position is None:
                raise ValidationError(f'Позиция для «{item["raw"]}» не относится к этому мероприятию.')
        dc.save_value_mapping(group, item['key'], item['raw'], position=position, role=role,
                              skip=target == 'skip', operator=operator)


# --- Состояния колонок -----------------------------------------------------------

STATE_LABELS = {
    'skipped': 'пропущена вручную', 'empty': 'пустая', 'no_event': 'не привязана к мероприятию',
    'no_date': 'нет даты', 'unmapped': 'не сопоставлены значения', 'no_people': 'люди базы не загружены',
    'ready': 'готова к загрузке', 'changed': 'сопоставление изменено — перезагрузите', 'loaded': 'загружена',
}


STATE_HINTS = {
    'skipped': 'Колонка отмечена «Пропустить» и в загрузку не входит. «Вернуть» — на странице базы или мероприятия.',
    'empty': 'В колонке нет заполненных ячеек — загружать нечего.',
    'no_event': 'Колонка не относится ни к одному мероприятию. На странице базы выберите для неё ФиП и день или добавьте её в мероприятие.',
    'no_date': 'Дата колонки не указана в её заголовке. Укажите дату в поле «Дата» (ДД.ММ.ГГГГ) или выберите день ФиП.',
    'no_people': 'Люди этой базы ещё не загружены — запустите «Загрузить людей» на странице базы.',
    'ready': 'Все значения сопоставлены — нажмите «Загрузить».',
    'changed': 'После загрузки сопоставление изменилось — нажмите «Перезагрузить», участия перенесутся.',
    'loaded': 'Колонка загружена. «Откатить» удалит созданное ею.',
}


def column_state(column, mappings=None):
    missing_raw = []
    if column.skipped:
        code = 'skipped'
    elif not column.value_counts:
        code = 'empty'
    elif not column.event_group_id:
        code = 'no_event'
    elif not column.day:
        code = 'no_date'
    else:
        if mappings is None:
            mappings = {m.value_key: m for m in dc.legacy_value_mappings_qs().filter(event_group_id=column.event_group_id)}
        keys = [value_key(raw) for raw in column.value_counts]
        missing = [k for k in keys if k not in mappings or not mappings[k].skip and mappings[k].position_id is None]
        missing_raw = [raw for raw in column.value_counts if value_key(raw) in set(missing)]
        if missing:
            code = 'unmapped'
        elif not column.base.people_loaded_at:
            code = 'no_people'
        elif column.loaded_at:
            changed = any(mappings[k].updated_at > column.loaded_at for k in keys)
            code = 'changed' if changed else 'loaded'
        else:
            code = 'ready'
    tone = {'loaded': 'success', 'ready': 'info', 'skipped': '', 'empty': ''}.get(code, 'warning')
    if code == 'unmapped':
        shown = '; '.join(f'«{raw}»' for raw in missing_raw[:6]) + (f' и ещё {len(missing_raw) - 6}' if len(missing_raw) > 6 else '')
        hint = (f'Нет позиции или «Пропустить» у {len(missing_raw)} значений: {shown}. '
                'Выберите их в таблице «Сопоставление значений» на странице мероприятия и сохраните.')
    else:
        hint = STATE_HINTS[code]
    return {'code': code, 'label': STATE_LABELS[code], 'done': code in ('loaded', 'skipped', 'empty'), 'tone': tone,
            'hint': hint, 'missing': missing_raw}


def _light_bases():
    return dc.legacy_bases_qs().defer('content', 'parsed')


def hub_overview():
    """Хаб: базы по годам, мероприятия из баз и что ещё не загружено (с причинами)."""
    columns = list(dc.legacy_base_columns_qs().select_related('base', 'event_group').defer('base__content', 'base__parsed')
                   .order_by('base__year', 'index'))
    mapping_rows = defaultdict(dict)
    for m in dc.legacy_value_mappings_qs():
        mapping_rows[m.event_group_id][m.value_key] = m
    by_base, by_group = defaultdict(list), defaultdict(list)
    for column in columns:
        item = {'column': column, 'state': column_state(column, mapping_rows.get(column.event_group_id, {}))}
        by_base[column.base_id].append(item)
        if column.event_group_id:
            by_group[column.event_group_id].append(item)
    bases = []
    for base in _light_bases():
        items = by_base.get(base.pk, [])
        bases.append({'base': base, 'total': len(items), 'loaded': sum(i['state']['code'] == 'loaded' for i in items),
                      'pending': [i for i in items if not i['state']['done']]})
    documents = defaultdict(list)
    for document in dc.fap_documents_qs().defer('content').order_by('-version'):
        documents[document.event_group_id].append(document)
    groups = []
    for group in dc.event_groups_qs().filter(pk__in=by_group.keys()).order_by('title'):
        items = by_group[group.pk]
        groups.append({'group': group, 'total': len(items), 'loaded': sum(i['state']['code'] == 'loaded' for i in items),
                       'pending': [i for i in items if not i['state']['done']], 'documents': documents.get(group.pk, [])})
    library = []
    for document in dc.fap_documents_qs().defer('content').select_related('event_group').order_by('-uploaded_at'):
        plan = document_plan(document)
        dates = [date.fromisoformat(day) for day in plan.get('dates', [])]
        library.append({'document': document, 'dates': dates, 'positions': len(plan.get('directions', [])),
                        'warnings': plan.get('warnings', [])})
    return {'bases': bases, 'groups': groups, 'library': library}


def base_overview(base):
    choices = fap_choices()
    columns = list(dc.legacy_base_columns_qs().filter(base=base).select_related('event_group', 'base', 'fap_document')
                   .defer('base__content', 'base__parsed', 'fap_document__content').order_by('index'))
    # День ФиП, уже выбранный колонкой, другим колонкам не предлагается — кроме
    # колонок той же даты («20 июня 1 смена» / «2 смена» на один день ФиП).
    taken = {f'{c.fap_document_id}|{c.day.isoformat()}': c for c in columns if c.fap_document_id and c.day}
    items = []
    for c in columns:
        selected = f'{c.fap_document_id}|{c.day.isoformat()}' if c.fap_document_id and c.day else ''
        suggested = '' if selected or c.event_group_id or c.skipped else suggest_fap(c, choices)
        options = []
        for choice in choices:
            days = [d for d in choice['days'] if d['value'] not in taken or taken[d['value']].pk == c.pk or d['day'] == c.day]
            if days:
                options.append({**choice, 'days': days})
        items.append({'column': c, 'state': column_state(c), 'fap_selected': selected or suggested,
                      'fap_suggested': bool(suggested), 'people': sum(c.value_counts.values()), 'fap_options': options})
    groups = dc.event_groups_qs().filter(pk__in={i['column'].event_group_id for i in items if i['column'].event_group_id}).order_by('title')
    free = [i for i in items if not i['column'].event_group_id and not i['column'].skipped]
    return {'base': base, 'columns': items, 'free_columns': free, 'groups': groups, 'fap_choices': choices,
            # Все мероприятия: обрезанный список прятал старые от сопоставления колонки.
            'all_groups': dc.event_groups_qs().order_by('-created_at'),
            'people_count': dc.legacy_base_people_qs().filter(base=base).count()}


def function_options(group):
    """Функции для выбора: сначала функции этого мероприятия, затем остальной пул."""
    used = list(dc.event_functions_qs().filter(event_map__event__event_group=group).distinct().order_by('name'))
    rest = list(dc.event_functions_qs().exclude(pk__in=[c.pk for c in used]).order_by('name'))
    return used, rest


def group_page(group):
    overview = group_overview(group)
    rows = mapping_table(group)
    functions = {link.event_id: link.category_id for link in dc.event_category_maps_qs().filter(event__event_group=group, category__kind='function').order_by('-pk')}
    positions = list(dc.events_qs().filter(event_group=group).order_by('title'))
    for position in positions:
        position.function_id = functions.get(position.pk)
    used_functions, other_functions = function_options(group)
    for item in overview['columns']:
        item['people'] = sum(item['column'].value_counts.values())
    ready = [i['column'].pk for i in overview['columns'] if i['state']['code'] in ('ready', 'changed')]
    return {'group': group, 'rows': rows, 'positions': positions, 'ready_ids': ready, 'overlaps': overlaps(group),
            'used_functions': used_functions, 'other_functions': other_functions,
            'documents': list(dc.fap_documents_qs().filter(event_group=group).defer('content').order_by('-version')),
            'unmapped': sum(1 for row in rows if not row['mapping']), **overview}


def overlaps(group, limit=50):
    """Люди с пересекающимися по времени сменами разных позиций мероприятия.

    Не ошибка (решение 2026-11-11: тим-лидер может вести несколько наборов и
    сам быть волонтёром) — только предупреждение менеджеру."""
    rows = (dc.participations_qs().filter(event_day__event__event_group=group)
            .select_related('user', 'event_day__event').order_by('user_id', 'event_day__start_time'))
    by_user = defaultdict(list)
    for participation in rows:
        if not participation.event_day.time_unknown:
            by_user[participation.user_id].append(participation)
    result = []
    for items in by_user.values():
        clashing = {}
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if b.event_day.start_time >= a.event_day.end_time:
                    break
                if a.event_day.event_id != b.event_day.event_id:
                    clashing[a.pk], clashing[b.pk] = a.event_day, b.event_day
        if clashing:
            result.append({'user': items[0].user, 'shifts': list(clashing.values())})
            if len(result) >= limit:
                break
    return result


def group_overview(group):
    mappings = {m.value_key: m for m in dc.legacy_value_mappings_qs().filter(event_group=group)}
    columns = list(dc.legacy_base_columns_qs().filter(event_group=group).select_related('base').order_by('day', 'index'))
    items = [{'column': c, 'state': column_state(c, mappings)} for c in columns]
    return {'columns': items, 'pending': [i for i in items if not i['state']['done']],
            'loaded': sum(i['state']['code'] == 'loaded' for i in items)}


# --- Этап 5: загрузка -------------------------------------------------------------

def _hours(shift):
    if shift.time_unknown:
        return Decimal('0')
    seconds = (shift.end_time - shift.start_time).total_seconds()
    return (Decimal(seconds) / Decimal(3600)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _resolve_shift(position, column, operator):
    """Смена позиции для колонки: по дате колонки; несколько колонок одного дня —
    по порядку; нет смены ФиП — смена с неизвестным временем (ключ колонки)."""
    key = _hash(f'migration:{position.pk}:{column.pk}')
    source = dc.legacy_shifts_qs().filter(key=key).select_related('shift').first()
    if source:
        return source.shift
    same_day = list(dc.legacy_base_columns_qs().filter(event_group_id=column.event_group_id, day=column.day,
                                                         skipped=False).order_by('index').values_list('pk', flat=True))
    rank = same_day.index(column.pk) if column.pk in same_day else 0
    existing = list(dc.event_shifts_qs().filter(event=position, day=column.day, legacy_source__isnull=True).order_by('start_time', 'pk'))
    if existing and (len(same_day) == 1 or rank < len(existing)):
        return existing[min(rank, len(existing) - 1)]
    return dc.create_legacy_shift(position, column.day, datetime.combine(column.day, time.min, MSK), key, column.header, operator)


def _touched(participation):
    return participation.status != 'attended' or participation.hours_overridden


def _undo_cell(cell, operator, affected):
    """Удалить созданное этой ячейкой. Изменённое сотрудником участие — конфликт."""
    if cell.participation and _touched(cell.participation):
        return False
    if cell.participation:
        dc.delete_legacy_participation(cell.participation, operator)
    if cell.application and cell.shift:
        dc.unlink_legacy_application_shift(cell.application, cell.shift, operator)
    if cell.staff and not dc.legacy_loaded_cells_qs().filter(staff=cell.staff).exclude(pk=cell.pk).exists():
        # Назначения тим-лидера на остальные позиции функции, сделанные этой
        # загрузкой (не раньше ячейки), снимаются вместе с ней; ручные — остаются.
        function = position_function(cell.staff.event)
        if function is not None:
            for other in dc.event_staff_qs().filter(user_id=cell.user_id, staff_role='team_lead',
                                                    event__event_group_id=cell.staff.event.event_group_id,
                                                    event__category_map__category=function,
                                                    assigned_at__gte=cell.created_at - timedelta(minutes=1)).exclude(pk=cell.staff.pk):
                if not dc.legacy_loaded_cells_qs().filter(staff__event=other.event, user_id=cell.user_id).exclude(pk=cell.pk).exists():
                    dc.delete_event_staff(other, operator)
        dc.delete_event_staff(cell.staff, operator)
    affected[cell.user_id] = cell.user
    dc.delete_loaded_cell(cell, operator)
    return True


def new_columns_result():
    return {'participations': 0, 'moved': 0, 'conflicts': [], 'team_leads': 0}


def prepare_column(column):
    """Проверить готовность и собрать строки базы с ячейкой этой колонки."""
    column = dc.legacy_base_columns_qs().select_related('base', 'event_group').get(pk=column.pk)
    state = column_state(column)
    if state['code'] not in ('ready', 'loaded', 'changed'):
        raise ValidationError(f'Колонка «{column.header}»: {state["label"]}. {state["hint"]}')
    rows = [(row, item) for row in column.base.parsed['rows']
            for item in row['assignments'] if item['column'] == column.index]
    return {'column': column, 'rows': rows, 'handled': set()}


def load_column_rows(operator, context, rows, result, affected):
    """Порция ячеек колонки: создать/перенести участия по сопоставлению."""
    column = context['column']
    mappings = {m.value_key: m for m in dc.legacy_value_mappings_qs().filter(event_group=column.event_group).select_related('position')}
    numbers = [row['number'] for row, _ in rows]
    people = dict(dc.legacy_base_people_qs().filter(base=column.base, row_number__in=numbers).values_list('row_number', 'user_id'))
    users = {u.pk: u for u in dc.users_qs().filter(pk__in=people.values())}
    cells = {c.user_id: c for c in dc.legacy_loaded_cells_qs().filter(column=column, user_id__in=people.values())
             .select_related('participation', 'application', 'staff', 'user', 'shift')}
    for row, item in rows:
        user = users.get(people.get(row['number']))
        if user is None or user.pk in context['handled']:
            continue
        context['handled'].add(user.pk)
        key = value_key(item['description'])
        mapping = mappings[key]
        cell = cells.get(user.pk)
        if cell and not mapping.skip and cell.position_id == mapping.position_id:
            if mapping.role == 'team_lead' and not cell.staff:
                _grant_team_lead(operator, cell.position, user, result)
            continue
        if cell:
            if not _undo_cell(cell, operator, affected):
                result['conflicts'].append({'user': user, 'column': column, 'participation': cell.participation})
                continue
            result['moved'] += 0 if mapping.skip else 1
        if mapping.skip:
            continue
        position = mapping.position
        shift = _resolve_shift(position, column, operator)
        application = dc.ensure_legacy_application(user, position, shift, item['description'], operator)
        dc.ensure_legacy_decision(application, shift, operator)
        participation, created = dc.ensure_legacy_participation(user, shift, operator)
        if created:
            hours = _hours(shift)
            if hours:
                dc.set_participation_hours(participation, hours, operator)
            result['participations'] += 1
        staff = _grant_team_lead(operator, position, user, result) if mapping.role == 'team_lead' else None
        dc.record_loaded_cell(column, user, key, position=position, shift=shift, application=application,
                              participation=participation if created else None, staff=staff, operator=operator)
        affected[user.pk] = user
    return result


def finish_column(operator, context):
    dc.save_legacy_column(context['column'], operator, loaded_at=_now())


def recalc_affected(affected):
    for user in affected.values():
        recalc_user_aggregates(user)
    affected.clear()


@transaction.atomic
def load_columns(operator, columns):
    """Загрузить готовые колонки за один раз (фоновая задача — порциями)."""
    _manager(operator)
    result, affected = new_columns_result(), {}
    for column in columns:
        context = prepare_column(column)
        load_column_rows(operator, context, context['rows'], result, affected)
        finish_column(operator, context)
    recalc_affected(affected)
    return result


def _grant_team_lead(operator, position, user, result):
    """Тим-лидер видит весь набор своей функции по каждой смене (решение 2026-11-11):
    назначение на все позиции этой функции в мероприятии, плюс глобальная роль."""
    existed = dc.event_staff_qs().filter(event=position, user=user, staff_role='team_lead').exists()
    staff = dc.ensure_event_team_lead(position, user, operator)
    function = position_function(position)
    if function is not None:
        for other in dc.events_qs().filter(event_group_id=position.event_group_id, category_map__category=function).exclude(pk=position.pk):
            dc.ensure_event_team_lead(other, user, operator)
    if not dc.has_active_role('team_lead', user):
        dc.create_role('team_lead', user, assigned_by=operator)
        result['team_leads'] += 1
    return None if existed else staff


def _now():
    from django.utils import timezone
    return timezone.now()


@transaction.atomic
def unload_column(operator, column):
    """Откат колонки: удаляется только созданное ею; правленое сотрудниками остаётся."""
    _manager(operator)
    affected, conflicts = {}, []
    for cell in dc.legacy_loaded_cells_qs().filter(column=column).select_related('participation', 'application', 'staff', 'user', 'shift'):
        if not _undo_cell(cell, operator, affected):
            conflicts.append(cell)
    if not conflicts:
        dc.save_legacy_column(column, operator, loaded_at=None)
    for user in affected.values():
        recalc_user_aggregates(user)
    return {'conflicts': conflicts}
