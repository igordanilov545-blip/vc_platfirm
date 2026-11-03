"""FaP: ACL, атомарный импорт, стабильные ID и явный обмен без скрытого overwrite."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from data_base import data_controller as dc
from blog.services.roles import has_manager_access, is_team_leader
from .fap_workbook import read_xlsx, write_xlsx, only_shifts_content, group_directions, MSK


def _manager(operator):
    if not has_manager_access(operator):
        raise PermissionDenied('Таблицей мероприятия управляет менеджер платформы.')


def _key(kind, pk):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'vc-platform:{kind}:{pk}'))


def _iso(value):
    return value.astimezone(MSK).isoformat() if value else None


def fingerprint(plan):
    """Содержимое, без координат, предупреждений и вычисляемых фактов."""
    clean = deepcopy(plan)
    clean.pop('warnings', None)
    clean.pop('stats', None)
    clean.pop('input_rows', None)
    for direction in clean['directions']:
        for position in direction['positions']:
            position.pop('row', None)
    return hashlib.sha256(json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def current_plan(group):
    """Включает ручные новые позиции/смены; ID выводятся из PK, а не имён/строк."""
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    baseline = link.baseline if link else {}
    plan = {'dates': list(baseline.get('dates', [])), 'directions': [], 'warnings': [], 'quantity_widths': list(baseline.get('quantity_widths', []))}
    for key in ('grouped_directions', 'quantity_labels', 'daily_zone_shifts'):
        if key in baseline:
            plan[key] = deepcopy(baseline[key])
    original_positions = {p['id']: p for d in baseline.get('directions', []) for p in d['positions']}
    directions = list(dc.event_directions_qs().filter(event_group=group))
    direction_map = {d.pk: {'id': str(d.source_key), 'name': d.name, 'order': d.sort_order, 'team_leaders': [], 'responsibles': [], 'positions': []} for d in directions}
    mapped_positions = {p.event_id: p for p in dc.sheet_positions_qs().filter(event__event_group=group)}
    mapped_shifts = {s.shift_id: s for s in dc.sheet_shifts_qs().filter(shift__event__event_group=group)}
    day_records = {(d.position_id, d.day.isoformat()): d for d in dc.sheet_days_qs().filter(position__event__event_group=group)}
    leaders = list(dc.sheet_leaders_qs().filter(direction__event_group=group).select_related('user'))
    responsibles = list(dc.zone_responsibles_qs().filter(direction__event_group=group))
    for key, records in (('team_leaders', leaders), ('responsibles', responsibles)):
        for item in records:
            if item.position_id is None:
                direction_map[item.direction_id][key].append(item.display_name)
    runtime_positions = list(dc.events_qs().filter(event_group=group).prefetch_related('shifts').order_by('pk'))
    all_dates = set(plan['dates'])
    for event in runtime_positions:
        mapped = mapped_positions.get(event.pk)
        pid = str(mapped.source_key) if mapped else _key('position', event.pk)
        original = original_positions.get(pid, {})
        if mapped:
            direction = direction_map[mapped.direction_id]
        else:
            # Ручная позиция тоже является самостоятельным направлением FaP.
            direction = {'id': pid, 'name': event.title, 'order': len(direction_map), 'team_leaders': [], 'responsibles': [], 'positions': []}
            direction_map[('manual', event.pk)] = direction
        if mapped and baseline.get('grouped_directions'):
            direction['name'] = event.title
        position = {'id': pid, 'name': event.title, 'order': mapped.sort_order if mapped else event.pk,
                    'is_team_lead_role': mapped.is_team_lead_role if mapped else False,
                    'team_leaders': [x.display_name for x in leaders if mapped and x.position_id == mapped.pk],
                    'responsibles': [x.display_name for x in responsibles if mapped and x.position_id == mapped.pk],
                    'days': [], 'row': original.get('row')}
        shifts_by_day = {}
        for shift in event.shifts.all():
            day = shift.day.isoformat()
            all_dates.add(day)
            source = mapped_shifts.get(shift.pk)
            count = None if source and source.planned_count is None and shift.volunteer_needed == 0 else shift.volunteer_needed
            shifts_by_day.setdefault(day, []).append({'id': str(source.source_key) if source else _key('shift', shift.pk),
                'label': source.label if source else '', 'start': _iso(shift.start_time), 'end': _iso(shift.end_time), 'count': count,
                'checkin': _iso(source.checkin) if source else None, 'checkout': _iso(source.checkout) if source else None})
        position['_shift_days'] = shifts_by_day
        position['_mapped_pk'] = mapped.pk if mapped else None
        position['_original'] = original
        direction['positions'].append(position)
    plan['dates'] += sorted(all_dates - set(plan['dates']))
    if not plan['dates']:
        plan['dates'] = [timezone.localdate().isoformat()]
    for direction in direction_map.values():
        if not direction['positions']:
            continue
        direction['positions'].sort(key=lambda p: p['order'])
        for position in direction['positions']:
            day_shifts = position.pop('_shift_days')
            mapped_pk = position.pop('_mapped_pk')
            original_days = {d['date']: d for d in position.pop('_original').get('days', [])}
            for day in plan['dates']:
                stored = day_records.get((mapped_pk, day))
                previous = original_days.get(day, {})
                shifts = day_shifts.get(day, [])
                item = {'date': day, 'work': stored.raw_work_time if stored else None,
                        'checkin_out': stored.raw_checkin_out if stored else None,
                        'quantities': deepcopy(stored.quantities) if stored else [{'label': '', 'count': None}, {'label': 'A', 'count': None}, {'label': 'B', 'count': None}], 'shifts': shifts}
                if shifts != previous.get('shifts', []):
                    def interval(s, a, b):
                        if not s[a] or not s[b]:
                            return ''
                        prefix = f"{s['label']}: " if s['label'] else ''
                        return prefix + datetime.fromisoformat(s[a]).strftime('%H:%M') + '-' + datetime.fromisoformat(s[b]).strftime('%H:%M')
                    item['work'] = '\n'.join(interval(s, 'start', 'end') for s in shifts) or None
                    item['checkin_out'] = '\n'.join(filter(None, (interval(s, 'checkin', 'checkout') for s in shifts))) or None
                    if len(shifts) <= 1:
                        item['quantities'] = [{'label': '', 'count': shifts[0]['count'] if shifts else None}, {'label': 'A', 'count': None}, {'label': 'B', 'count': None}]
                    else:
                        for i, s in enumerate(shifts):
                            s['label'] = s['label'] or chr(65 + i)
                        item['quantities'] = [{'label': '', 'count': sum(s['count'] or 0 for s in shifts)}] + [{'label': s['label'], 'count': s['count']} for s in shifts]
                position['days'].append(item)
        plan['directions'].append(direction)
    plan['quantity_widths'] = [max([3] + [len(p['days'][i]['quantities']) for d in plan['directions'] for p in d['positions']]) for i in range(len(plan['dates']))]
    plan['stats'] = {}
    parts = list(dc.participations_qs().filter(event_day__event__event_group=group).values('event_day__day', 'user_id', 'status'))
    for day in plan['dates']:
        selected = [p for p in parts if p['event_day__day'].isoformat() == day]
        plan['stats'][day] = {'recruited': len(selected), 'checked_in': sum(p['status'] == 'attended' for p in selected)}
    plan['stats']['unique_people'] = len({p['user_id'] for p in parts if p['status'] == 'attended'})
    return group_directions(plan)


def _validate_plan(group, plan):
    keys = [p['id'] for d in plan['directions'] for p in d['positions']]
    shift_keys = [s['id'] for d in plan['directions'] for p in d['positions'] for day in p['days'] for s in day['shifts']]
    if len(keys) != len(set(keys)) or len(shift_keys) != len(set(shift_keys)):
        raise ValidationError('В таблице повторяются служебные ID. Не копируйте позиции вместе со служебными комментариями.')
    if dc.sheet_positions_qs().filter(source_key__in=keys).exclude(event__event_group=group).exists() or dc.sheet_shifts_qs().filter(source_key__in=shift_keys).exclude(shift__event__event_group=group).exists():
        raise ValidationError('Таблица содержит идентификаторы другого мероприятия.')
    for direction in plan['directions']:
        if len(direction['name']) > 500:
            raise ValidationError('Название направления длиннее 500 символов.')
        for position in direction['positions']:
            if len(position['name']) > 255:
                raise ValidationError('Название позиции длиннее 255 символов.')
            if any(len(name) > 255 for key in ('team_leaders', 'responsibles') for name in direction[key] + position[key]):
                raise ValidationError('Имя ответственного длиннее 255 символов.')
    removed = dc.sheet_shifts_qs().filter(shift__event__event_group=group).exclude(source_key__in=shift_keys)
    if removed.filter(shift__participations__isnull=False).exists() or removed.filter(shift__applications__isnull=False).exists():
        raise ValidationError('Нельзя удалить из плана смены с участниками или заявками. Сначала обработайте их в системе.')
    removed_positions = dc.sheet_positions_qs().filter(event__event_group=group).exclude(source_key__in=keys)
    if removed_positions.filter(event__applications__isnull=False).exists() or removed_positions.filter(event__shifts__participations__isnull=False).exists():
        raise ValidationError('Нельзя удалить из таблицы позиции с заявками или участниками.')


def _apply_plan(group, plan):
    _validate_plan(group, plan)
    runtime_events = {_key('position', e.pk): e for e in dc.events_qs().filter(event_group=group)}
    runtime_shifts = {_key('shift', s.pk): s for s in dc.event_shifts_qs().filter(event__event_group=group)}
    keep_positions, keep_shifts = [], []
    for direction_data in plan['directions']:
        direction = dc.save_sheet_direction(group, direction_data['id'], direction_data['name'], direction_data['order'])
        for key, kind in (('team_leaders', 'team_lead'), ('responsibles', 'zone_responsible')):
            dc.sync_sheet_staff(direction, None, direction_data[key], kind)
        for position_data in direction_data['positions']:
            position = dc.save_sheet_position(group, direction, position_data['id'], position_data['name'], position_data['order'], position_data['is_team_lead_role'], existing_event=runtime_events.get(position_data['id']))
            keep_positions.append(position.source_key)
            for key, kind in (('team_leaders', 'team_lead'), ('responsibles', 'zone_responsible')):
                dc.sync_sheet_staff(direction, position, position_data[key], kind)
            for day in position_data['days']:
                record = dc.save_sheet_day(position, day['date'], day['work'], day['checkin_out'], day['quantities'])
                for order, shift in enumerate(day['shifts']):
                    dc.save_sheet_shift(record, shift['id'], shift['label'], datetime.fromisoformat(shift['start']), datetime.fromisoformat(shift['end']), shift['count'],
                        datetime.fromisoformat(shift['checkin']) if shift['checkin'] else None,
                        datetime.fromisoformat(shift['checkout']) if shift['checkout'] else None, order, existing_shift=runtime_shifts.get(shift['id']))
                    keep_shifts.append(shift['id'])
    dc.delete_sheet_shift_records(dc.sheet_shifts_qs().filter(shift__event__event_group=group).exclude(source_key__in=keep_shifts))
    dc.delete_sheet_position_records(dc.sheet_positions_qs().filter(event__event_group=group).exclude(source_key__in=keep_positions))
    dc.delete_empty_sheet_days(dc.sheet_days_qs().filter(position__event__event_group=group, shifts__isnull=True).exclude(day__in=plan['dates']))
    dc.delete_unused_sheet_directions(group, [d['id'] for d in plan['directions']])
    dc.refresh_sheet_leader_staff(group.pk)


def import_workbook(operator, group, content, name='Смены.xlsx'):
    _manager(operator)
    plan = read_xlsx(content)
    return import_plan(operator, group, plan, content, name)


@transaction.atomic
def import_plan(operator, group, plan, content, name, **link_values):
    _manager(operator)
    group = dc.event_groups_qs().select_for_update().get(pk=group.pk)
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    if link and link.baseline and not link.baseline.get('grouped_directions'):
        repair_direction_import(operator, group)
        link = dc.event_sheet_links_qs().get(event_group=group)
    source_hash = hashlib.sha256(content).hexdigest()
    if link and link.source_hash == source_hash and plan.get('daily_zone_shifts') and not link.baseline.get('daily_zone_shifts'):
        # Повторная загрузка того же исходника исправляет прежнее дробление смен,
        # сохраняя позиции и первую смену дня. Данные с заявками не объединяем.
        positions = dc.sheet_positions_qs().filter(event__event_group=group)
        if positions.filter(event__applications__isnull=False).exists() or positions.filter(event__shifts__participations__isnull=False).exists():
            raise ValidationError('У прежних смен есть заявки или явка. Автоматическое объединение остановлено, данные сохранены.')
        if fingerprint(current_plan(group)) != fingerprint(link.baseline):
            raise ValidationError('После импорта позиции изменены в системе. Автоматическое объединение остановлено, данные сохранены.')
        previous = {p['row']: (d, p) for d in link.baseline['directions'] for p in d['positions']}
        plan = deepcopy(plan)
        for direction in plan['directions']:
            position = direction['positions'][0]
            if position['row'] not in previous:
                raise ValidationError('Не удалось сопоставить блоки исходного файла; данные сохранены.')
            old_direction, old_position = previous[position['row']]
            direction['id'], position['id'] = old_direction['id'], old_position['id']
            old_days = {day['date']: day for day in old_position['days']}
            for day in position['days']:
                old_shifts = old_days.get(day['date'], {}).get('shifts', [])
                if day['shifts'] and old_shifts:
                    day['shifts'][0]['id'] = old_shifts[0]['id']
        _apply_plan(group, plan)
        return dc.save_event_sheet_link(group, baseline=plan, warnings=plan['warnings'], synced_at=timezone.now(), **link_values)
    if link and link.source_hash == source_hash and not link_values:
        return link
    if link and link.baseline:
        previous = fingerprint(link.baseline)
        local, remote = fingerprint(current_plan(group)), fingerprint(plan)
        if local != previous and remote == previous:
            raise ValidationError('В системе есть изменения, которых пока нет в таблице. Сначала отправьте текущий план; локальные изменения сохранены.')
        if local != previous and remote != previous and local != remote:
            raise ValidationError('Конфликт: изменены и система, и таблица. Скачайте текущий план и согласуйте изменения; данные не перезаписаны.')
        known = {p['id'] for d in link.baseline['directions'] for p in d['positions']}
        incoming = {p['id'] for d in plan['directions'] for p in d['positions']}
        if known and not known.intersection(incoming):
            raise ValidationError('В файле нет ID этого мероприятия. Скачайте текущий XLSX из системы и редактируйте его; это защищает от дублей.')
    _apply_plan(group, plan)
    # Нормализуем staff/порядок к фактическим записям; исходное оформление остаётся.
    link = dc.save_event_sheet_link(group, template=only_shifts_content(content), baseline=plan, source_hash=source_hash, source_name=name[:255], warnings=plan['warnings'], synced_at=timezone.now(), **link_values)
    return link


@transaction.atomic
def repair_direction_import(operator, group):
    """Исправляет прежний импорт без заявок/явки, сохраняя первую позицию направления."""
    _manager(operator)
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    if not link or not link.baseline or link.baseline.get('grouped_directions'):
        return link
    plan = group_directions(link.baseline)
    dc.consolidate_sheet_directions(group, plan)
    _apply_plan(group, plan)
    return dc.save_event_sheet_link(group, baseline=plan, warnings=plan['warnings'])


def export_workbook(operator, group):
    _manager(operator)
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    plan = current_plan(group)
    if not plan['directions']:
        raise ValidationError('В мероприятии пока нет позиций для выгрузки.')
    return write_xlsx(plan, bytes(link.template) if link and link.template else None)


@transaction.atomic
def bind_team_leader(operator, assignment_id, user):
    _manager(operator)
    assignment = dc.sheet_leaders_qs().filter(pk=assignment_id).select_related('direction', 'position').first()
    if not assignment:
        raise ValidationError('Назначение тим-лидера не найдено.')
    if not is_team_leader(user):
        raise ValidationError('Сначала назначьте выбранному пользователю роль тим-лидера в настройках.')
    dc.bind_sheet_leader_record(assignment, user, operator)
    return assignment


def content_signature(plan):
    """Проверка неизменённого исходника без ещё не записанных в Google ID."""
    value = deepcopy(plan)
    for direction in value['directions']:
        direction['id'] = ''
        for position in direction['positions']:
            position['id'] = ''
            for day in position['days']:
                for shift in day['shifts']:
                    shift['id'] = ''
    return fingerprint(value)


def _source_ids(group, incoming):
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    if link and link.baseline and content_signature(incoming) == content_signature(link.baseline):
        # Это весь тот же документ, без правок. Имена не используются как ID
        # и никогда не служат основанием объединения разных людей/позиций.
        restored = deepcopy(link.baseline)
        for d, source in zip(restored['directions'], incoming['directions']):
            for p, original in zip(d['positions'], source['positions']):
                p['row'] = original['row']
        restored['warnings'] = incoming['warnings']
        return restored
    return incoming


def prepare_sheet_input(operator, *, content=None, name='', google_url=''):
    """Сетевые обращения и парсинг ДО начала транзакции записи мероприятия."""
    _manager(operator)
    if content is not None:
        return {'plan': read_xlsx(content), 'content': content, 'name': name or 'Смены.xlsx', 'link_values': {}}
    from .google_sheets import GoogleSheetClient, parse_sheet_url
    spreadsheet_id, sheet_id = parse_sheet_url(google_url)
    client = GoogleSheetClient()
    try:
        content, sheet_id = client.read_google(spreadsheet_id, sheet_id)
    finally:
        client.close()
    return {'plan': read_xlsx(content), 'content': content, 'name': 'Google Таблица',
            'link_values': {'spreadsheet_id': spreadsheet_id, 'sheet_id': sheet_id}}


def apply_prepared_sheet(operator, group, prepared):
    plan = _source_ids(group, prepared['plan'])
    return import_plan(operator, group, plan, prepared['content'], prepared['name'], **prepared['link_values'])


def pull_google(operator, group):
    _manager(operator)
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    if not link or not link.spreadsheet_id:
        raise ValidationError('Сначала свяжите мероприятие с Google Таблицей.')
    prepared = prepare_sheet_input(operator, google_url=link.google_url)
    return apply_prepared_sheet(operator, group, prepared)


def push_google(operator, group):
    """Медленный Google-вызов не держит SQLite write-lock всей платформы."""
    from .google_sheets import GoogleSheetClient
    _manager(operator)
    link = dc.event_sheet_links_qs().filter(event_group=group).first()
    if not link or not link.spreadsheet_id:
        raise ValidationError('Сначала свяжите мероприятие с Google Таблицей.')
    client = GoogleSheetClient()
    try:
        if not client.session:
            raise ValidationError('Для отправки подключите JSON-ключ через «Настроить Google» и выдайте аккаунту доступ редактора.')
        content, sheet_id = client.read_google(link.spreadsheet_id, link.sheet_id)
        remote = _source_ids(group, read_xlsx(content))
        plan = current_plan(group)
        if fingerprint(remote) != fingerprint(link.baseline) and fingerprint(remote) != fingerprint(plan):
            raise ValidationError('Google Таблица изменена после прошлого обмена. Сначала получите изменения из Google; таблица не перезаписана.')
        prepared_hash = fingerprint(plan)
        exported = write_xlsx(plan, bytes(link.template) if link.template else None)
        normalized = read_xlsx(exported)
        client.write_google(link.spreadsheet_id, sheet_id, exported)
        with transaction.atomic():
            dc.event_groups_qs().select_for_update().get(pk=group.pk)
            if fingerprint(current_plan(group)) != prepared_hash:
                raise ValidationError('План отправлен в Google, но во время отправки система изменилась. Повторите проверку обмена; локальные данные сохранены.')
            _apply_plan(group, normalized)
            return dc.save_event_sheet_link(group, baseline=normalized, template=exported, source_hash=hashlib.sha256(exported).hexdigest(), synced_at=timezone.now(), sheet_id=sheet_id, warnings=normalized['warnings'])
    finally:
        client.close()
