"""Идентичность людей старой базы: отпечатки контактов и сопоставление с аккаунтами.

Прежняя одношаговая загрузка (мероприятия «по первым цифрам ячейки») заменена
поэтапной миграцией — blog/services/legacy_migration.py (решение 2026-11-11)."""
from collections import defaultdict
import hashlib

from data_base import data_controller as dc
from blog.services.fap_workbook import normalized_name
from blog.services.legacy_workbook import phone_number
from blog.services.social_profiles import social_username


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
