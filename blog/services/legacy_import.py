"""Предпросмотр, сопоставление и атомарное добавление истории из старой базы."""
from collections import defaultdict
from datetime import date, datetime, time
import hashlib
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from data_base import data_controller as dc
from blog.services.fap_workbook import MSK, normalized_name
from blog.services.legacy_workbook import phone_number
from blog.services.social_profiles import social_username
from blog.services.roles import has_manager_access
from blog.services.stats import recalc_user_aggregates


def _manager(operator):
    if not has_manager_access(operator):
        raise PermissionDenied('Загружать базу может только менеджер.')


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _recognized_contacts(profile):
    telegram = social_username(profile.get('telegram_username'), 'telegram').casefold()
    if not any(character.isalnum() for character in telegram):
        telegram = ''
    return {'telegram_username': telegram,
            'phone': phone_number(profile.get('phone')), 'email': (profile.get('email') or '').strip().casefold()}


def identity_key(profile, row_number=None):
    for name, value in _recognized_contacts(profile).items():
        if value:
            return _hash(name + ':' + value)
    identity = 'name:' + normalized_name(profile['first_name']) + ':' + normalized_name(profile['last_name']) + ':' + str(profile.get('birthday') or '')
    if any(profile[name].casefold() == 'unnamed' for name in ('first_name', 'last_name')):
        identity += ':row:' + str(row_number)
    return _hash(identity)


def _contact_keys(profile, row_number=None):
    return [_hash(name + ':' + value) for name, value in _recognized_contacts(profile).items() if value] or [identity_key(profile, row_number)]


def match_rows(plan):
    """Сопоставить все контакты; разные аккаунты по TG/телефону/почте — ошибка."""
    indexes = {name: defaultdict(set) for name in ('telegram_username', 'phone', 'email')}
    users = {user.pk: user for user in dc.users_qs()}
    for user in users.values():
        values = _recognized_contacts({'telegram_username': user.telegram_username, 'phone': user.phone, 'email': user.email})
        for name, value in values.items():
            if value:
                indexes[name][value].add(user.pk)
    bindings = dict(dc.legacy_identities_qs().values_list('key', 'user_id'))
    matches, errors = {}, []
    for row in plan['rows']:
        candidates = set()
        contacts = _recognized_contacts(row['profile'])
        for name, index in indexes.items():
            if contacts[name]:
                candidates |= index.get(contacts[name], set())
        linked = bindings.get(identity_key(row['profile'], row['number']))
        if linked:
            candidates.add(linked)
        if len(candidates) > 1:
            errors.append(f'Строка {row["number"]}: контакты указывают на разные аккаунты. Исправьте их в файле.')
        matches[row['number']] = users[next(iter(candidates))] if len(candidates) == 1 else None
    return matches, errors


def preview_context(operator, plan, date_overrides=None):
    _manager(operator)
    matches, conflicts = match_rows(plan)
    columns = []
    errors = list(plan['errors']) + conflicts
    overrides = date_overrides or {}
    for original in plan['columns']:
        column = dict(original)
        column['field_name'] = f'date_{column["index"]}'
        column['day'] = overrides.get(str(column['index'])) or column['day']
        if column['day']:
            try:
                column['day'] = date.fromisoformat(column['day']).isoformat()
            except (ValueError, TypeError):
                errors.append(f'Колонка «{column["header"]}»: неверная дата.')
                column['day'] = None
        column['needs_date'] = bool(column['used'] and not column['day'])
        columns.append(column)
    return {'plan': plan, 'columns': columns, 'errors': errors, 'warnings': plan['warnings'],
            'people': [{'row': row, 'existing': matches[row['number']]} for row in plan['rows']],
            'can_commit': not errors and not any(column['needs_date'] for column in columns)}


@transaction.atomic
def commit_legacy_base(operator, plan, *, date_overrides=None):
    context = preview_context(operator, plan, date_overrides)
    if not context['can_commit']:
        raise ValidationError(context['errors'][0] if context['errors'] else 'Укажите точные даты всех заполненных колонок.')
    # Повторная проверка внутри транзакции, до любых INSERT.
    list(dc.users_qs().select_for_update().filter(pk__in=[item['existing'].pk for item in context['people'] if item['existing']]).values_list('pk', flat=True))
    groups = defaultdict(list)
    for group in dc.event_groups_qs():
        groups[normalized_name(group.title)].append(group)
    positions = defaultdict(list)
    for event in dc.events_qs().select_related('event_group'):
        positions[(event.event_group_id, normalized_name(event.title))].append(event)
    source_shifts = {item.key: item.shift for item in dc.legacy_shifts_qs().select_related('shift__event')}
    columns = {column['index']: column for column in context['columns']}
    result = {'created_users': 0, 'existing_users': 0, 'groups': 0, 'positions': 0, 'shifts': 0, 'participations': 0}
    known = {}
    affected = {}
    # Даже пустые колонки представлены мероприятием; никаких выдуманных смен.
    for column in columns.values():
        group_key = normalized_name(column['group'])
        candidates = groups[group_key]
        if len(candidates) > 1:
            raise ValidationError(f'Несколько мероприятий с названием «{column["group"]}». Уточните название в файле.')
        if not candidates:
            candidates.append(dc.create_legacy_group(column['group'], operator))
            result['groups'] += 1
        column['group_object'] = candidates[0]
    for item in context['people']:
        row, user = item['row'], item['existing']
        profile = row['profile']
        fingerprint = identity_key(profile, row['number'])
        contacts = _contact_keys(profile, row['number'])
        seen = {known[contact].pk: known[contact] for contact in contacts if contact in known}
        if user:
            seen[user.pk] = user
        if len(seen) > 1:
            raise ValidationError(f'Строка {row["number"]}: конфликт аккаунтов между строками файла.')
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
            result['created_users'] += 1
        else:
            result['existing_users'] += 1
        for contact in contacts:
            known[contact] = user
        dc.create_legacy_identity(fingerprint, user, row['reported_age'], operator)
        for source, comment in row['comments'].items():
            if comment:
                dc.ensure_legacy_comment(user, source, comment, operator)
        for assignment in row['assignments']:
            column = columns[assignment['column']]
            group = column['group_object']
            position_key = (group.pk, normalized_name(assignment['position']))
            candidates = positions[position_key]
            if len(candidates) > 1:
                raise ValidationError(f'В мероприятии «{group.title}» несколько позиций «{assignment["position"]}».')
            if not candidates:
                candidates.append(dc.create_legacy_position(group, assignment['position'], operator))
                result['positions'] += 1
            event = candidates[0]
            source_key = _hash('2026:' + str(event.pk) + ':' + normalized_name(column['header']))
            shift = source_shifts.get(source_key)
            if shift is None:
                day = date.fromisoformat(column['day'])
                shift = dc.create_legacy_shift(event, day, datetime.combine(day, time.min, MSK), source_key, column['header'], operator)
                source_shifts[source_key] = shift
                result['shifts'] += 1
            elif shift.day != date.fromisoformat(column['day']):
                raise ValidationError(f'У ранее загруженной смены «{column["header"]}» другая дата. Исправьте её на странице позиции.')
            app = dc.ensure_legacy_application(user, event, shift, assignment['description'], operator)
            dc.ensure_legacy_decision(app, shift, operator)
            _, created = dc.ensure_legacy_participation(user, shift, operator)
            result['participations'] += int(created)
            if created:
                affected[user.pk] = user
    for user in affected.values():
        recalc_user_aggregates(user)
    return result
