"""Импорт заявок из Excel (архитектура.md 4.2, db.md раздел applications).

Ожидаемые колонки (рус.): Мероприятие, Автор, Фамилия, Телеграм, Телефон,
Функция, Смена, Роль, Статус обращающегося, Дата подачи,
Дата начала (опционально), Дата окончания (опционально).

Если мероприятие с таким названием не найдено — строка помечается как
"мероприятие отсутствует" и на превью менеджеру предлагается создать его
(по умолчанию с сегодняшней датой; если указан период дат — на каждый день
периода создаётся отдельный EventDay).
"""
import datetime
import uuid

import openpyxl
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from blog.models import Event, EventDay
from blog.services.applications import find_matching_user

COLUMN_MAP = {
    'event': ['Мероприятие', 'Название мероприятия'],
    'first_name': ['Автор', 'Имя'],
    'last_name': ['Фамилия'],
    'telegram_username': ['Телеграм', 'Telegram'],
    'phone': ['Номер телефона', 'Телефон'],
    'functions': ['Функция'],
    'shifts': ['Смена'],
    'role_in_event': ['Роль'],
    'user_status': ['Статус обращающегося'],
    'submitted_at': ['Дата подачи'],
    'event_start_date': ['Дата начала', 'Дата начала мероприятия'],
    'event_end_date': ['Дата окончания', 'Дата окончания мероприятия'],
}


def _find_col(header_row, candidates):
    for idx, cell in enumerate(header_row):
        if cell and str(cell).strip() in candidates:
            return idx
    return None


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return parse_date(value)
    return None


def parse_excel(file) -> dict:
    """Возвращает превью: {'rows': [...], 'errors': [...]}.

    Строки с несуществующим мероприятием не отбрасываются — помечаются
    event_missing=True с предложенными датами (по умолчанию сегодня,
    либо период, если он указан в файле), чтобы менеджер мог создать
    мероприятие прямо при подтверждении импорта.
    """
    wb = openpyxl.load_workbook(file, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        return {'rows': [], 'errors': ['Файл пуст']}

    col_idx = {key: _find_col(header, names) for key, names in COLUMN_MAP.items()}
    missing = [key for key in ('event', 'first_name') if col_idx[key] is None]
    if missing:
        return {'rows': [], 'errors': [f'Не найдены обязательные колонки: {missing}']}

    today = timezone.now().date()
    rows = []
    errors = []
    for line_no, row in enumerate(rows_iter, start=2):
        if row is None or all(v is None for v in row):
            continue

        def get(key):
            idx = col_idx.get(key)
            return row[idx] if idx is not None and idx < len(row) else None

        event_title = get('event')
        if not event_title:
            errors.append(f'Строка {line_no}: не указано название мероприятия')
            continue

        first_name = get('first_name')
        if not first_name:
            errors.append(f'Строка {line_no}: не указано имя заявителя')
            continue

        event = Event.objects.filter(title=event_title).first()

        event_start = _to_date(get('event_start_date')) or today
        event_end = _to_date(get('event_end_date')) or event_start

        submitted_raw = get('submitted_at')
        submitted_at = None
        if isinstance(submitted_raw, str):
            submitted_at = parse_datetime(submitted_raw)
        elif hasattr(submitted_raw, 'year'):
            submitted_at = submitted_raw

        telegram_username = get('telegram_username')
        phone = get('phone')
        last_name = get('last_name')
        matched_user = find_matching_user(
            telegram_username=telegram_username, phone=phone,
            first_name=first_name, last_name=last_name,
        )

        rows.append({
            'event_id': event.id if event else None,
            'event_title': event_title,
            'event_missing': event is None,
            'event_start_date': event_start.isoformat(),
            'event_end_date': event_end.isoformat(),
            'first_name': first_name,
            'last_name': last_name,
            'telegram_username': telegram_username,
            'phone': phone,
            'functions': get('functions'),
            'shifts': get('shifts'),
            'role_in_event': get('role_in_event'),
            'user_status': get('user_status'),
            'submitted_at': submitted_at,
            'matched_user_id': matched_user.id if matched_user else None,
            'matched_user_label': matched_user.full_name if matched_user else 'Новый профиль',
            'line_no': line_no,
        })

    return {'rows': rows, 'errors': errors}


def _create_event_with_days(row: dict) -> Event:
    """Создаёт мероприятие с EventDay на каждый день периода (или один день — сегодня по умолчанию)."""
    event = Event.objects.create(title=row['event_title'])

    start = row['event_start_date']
    end = row['event_end_date']
    if isinstance(start, str):
        start = datetime.date.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.date.fromisoformat(end)

    day = start
    while day <= end:
        EventDay.objects.create(
            event=event,
            day=day,
            start_time=timezone.make_aware(datetime.datetime.combine(day, datetime.time(0, 0))),
            end_time=timezone.make_aware(datetime.datetime.combine(day, datetime.time(23, 59))),
        )
        day += datetime.timedelta(days=1)

    return event


def _get_or_create_event(row: dict, events_cache: dict) -> Event:
    """Возвращает мероприятие для строки импорта, создавая его не более одного
    раза за импорт: несколько строк с одинаковым новым названием мероприятия
    должны попасть в одно и то же созданное мероприятие, а не плодить дубли."""
    if row.get('event_id'):
        return Event.objects.get(pk=row['event_id'])

    title = row['event_title']
    if title in events_cache:
        return events_cache[title]

    # На случай, если это же мероприятие уже создала более ранняя строка
    # того же импорта (event_id мог быть не проставлен на этапе превью).
    event = Event.objects.filter(title=title).first()
    if event is None:
        event = _create_event_with_days(row)

    events_cache[title] = event
    return event


def _user_match_key(row: dict):
    """Ключ для сопоставления «новых» заявителей друг с другом в рамках
    одного импорта, чтобы не создавать по пользователю на каждую строку."""
    if row.get('telegram_username'):
        return ('tg', row['telegram_username'].lstrip('@').lower())
    if row.get('phone'):
        return ('phone', row['phone'])
    if row.get('last_name'):
        return ('name', row['first_name'].strip().lower(), row['last_name'].strip().lower())
    return None


def commit_import(rows: list) -> int:
    """Создаёт мероприятия (если отсутствуют), Application и User из превью-строк."""
    from blog.models import Application, User

    events_cache = {}
    new_users_cache = {}
    created = 0

    for row in rows:
        event = _get_or_create_event(row, events_cache)

        user = None
        if row.get('matched_user_id'):
            user = User.objects.filter(id=row['matched_user_id']).first()
        elif row.get('create_new_user'):
            match_key = _user_match_key(row)
            user = new_users_cache.get(match_key) if match_key else None
            if user is None:
                telegram_id = f"import:{uuid.uuid4()}"
                user = User.objects.create_user(
                    telegram_id=telegram_id,
                    telegram_username=row.get('telegram_username'),
                    first_name=row.get('first_name'),
                    last_name=row.get('last_name'),
                    phone=row.get('phone'),
                )
                if match_key:
                    new_users_cache[match_key] = user

        Application.objects.create(
            event=event,
            user=user,
            first_name=row['first_name'],
            last_name=row.get('last_name'),
            telegram_username=row.get('telegram_username'),
            phone=row.get('phone'),
            functions=row.get('functions'),
            shifts=row.get('shifts'),
            role_in_event=row.get('role_in_event'),
            user_status=row.get('user_status'),
            submitted_at=row.get('submitted_at') or timezone.now(),
            status='new',
        )
        created += 1
    return created
