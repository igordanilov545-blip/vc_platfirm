"""Табличка желающих: разбор сообщений, сопоставление с мероприятием, ACL.

Желающие — люди, которые ещё ДО старта набора попросили тим-лидера/менеджера взять
их на следующий забег (documentation/volunteer-wishes.md). Мероприятия в платформе к
этому моменту нет, поэтому строка хранит подсказки (название, даты, позиция) и исходный
текст, а с мероприятием (`EventGroup`) сопоставляется при показе его страницы:

- есть название → совпадает по названию (слово/основа слова или аббревиатура
  «СКБС» = первые буквы названия); даты тогда лишь уточняют;
- названия нет, есть даты → хотя бы одна дата совпадает с днём смены мероприятия;
- ни того ни другого → в «прочих желающих» каждого мероприятия, пока не забрали.

«Забрали» — статус, а не удаление: человек остаётся в табличке (в своём мероприятии и
в подходящих других — с пометкой, куда забрали), пока мероприятие не прошло и статус
висит не дольше `Const wish_taken_hide_days` (3 дня). Потом строка уходит в архив;
«↩ Вернуть в желающие» снимает статус в любой момент.

Сообщения неформальные, поэтому разбор эвристический: исходный текст всегда
сохраняется рядом, а строку можно поправить вручную.

ACL: добавлять/забирать — активные тим-лидеры и менеджеры (веб и бот — одно правило,
`can_manage_wishes`); править/удалять — автор или менеджер; вернуть из «забрали» в
желающие — любой ТЛ/менеджер.
"""
import calendar
import datetime
import html
import re
import uuid

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from blog.logging_utils import get_web_logger, actor
from blog.services.roles import has_manager_access, is_team_leader
from data_base import data_controller as dc

logger = get_web_logger(__name__)

# ---------------------------------------------------------------------------
# Разбор сообщения
# ---------------------------------------------------------------------------

USERNAME_RE = re.compile(
    r'(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,31})\b'
    r'|(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})\b'
)
PHONE_RE = re.compile(r'(?<![\d+])(?:\+7|8|7)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)')
NAME_WORD = r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?'
NAME_AFTER_RE = re.compile(r'^[\s,:;—–-]*((?:' + NAME_WORD + r')(?:\s+' + NAME_WORD + r'){1,2})')
NAME_BEFORE_RE = re.compile(r'((?:' + NAME_WORD + r')(?:\s+' + NAME_WORD + r'){1,2})[\s,:;—–-]*$')
NAME_ONLY_RE = re.compile(r'((?:' + NAME_WORD + r')(?:\s+' + NAME_WORD + r'){1,2})\s+(?:очень\s+)?хо[чт]', re.UNICODE)
TOKEN_RE = re.compile(r'\d{1,2}\.\d{1,2}(?:\.\d{2,4})?(?!\d)|\d{1,4}(?:-?(?:го|ого|е|ое|й))?|[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9_/+.-]*|[-–—,.;:!?()«»"]')

MONTHS = [
    ('янв', 1), ('фев', 2), ('мар', 3), ('апр', 4), ('мая', 5), ('май', 5), ('мае', 5),
    ('июн', 6), ('июл', 7), ('авг', 8), ('сен', 9), ('окт', 10), ('ноя', 11), ('дек', 12),
]
RANGE_SEPARATORS = {'-', '–', '—', 'по'}
LIST_SEPARATORS = {',', 'и'}
# Число рядом с этими словами — не день: «10 км», «2 человека», «18 лет», «2 дня», «3 смены».
NUMBER_UNITS = ('км', 'k', 'к', 'м', 'мин', 'лет', 'год', 'чел', 'раз', 'час', 'ч', 'дн', 'ден', 'смен', 'недел', 'мес', 'шт')
PUNCT = {',', '.', ';', ':', '!', '?', '(', ')', '«', '»', '"', '-', '–', '—'}
# Слова, на которых обрывается название после «на»: «на скорость, очень классная».
PHRASE_STOP = {
    'очень', 'пожалуйста', 'если', 'можно', 'тоже', 'еще', 'ещё', 'он', 'она', 'оно', 'они',
    'его', 'ее', 'её', 'их', 'в', 'во', 'с', 'со', 'к', 'когда', 'как', 'хочет', 'хотят',
    'хочу', 'хотел', 'хотела', 'хотели', 'будет', 'сможет', 'может', 'классная', 'классный',
    'класс', 'супер', 'ок', 'всё', 'все', 'весь', 'чтобы', 'потому', 'там', 'тут', 'день',
    'дни', 'дня', 'числа', 'число', 'смену', 'смены', 'опыт', 'был', 'была', 'были', 'тлом',
}
NAME_STOP_STEMS = ('хоч', 'хот', 'очен', 'жела') + tuple(stem for stem, _ in MONTHS)
# Позиции/функции на забеге, которые пишут неформально («на справки», «на ПП/дистанцию»).
# Дополняются названиями функций, категорий и типовых позиций платформы.
POSITION_STEMS = (
    'справк', 'пп', 'кпп', 'дистанц', 'старт', 'финиш', 'медал', 'раздач', 'выдач', 'гардероб',
    'камер', 'регистрац', 'инфо', 'питан', 'пит', 'водн', 'навигац', 'сцен', 'фотозон',
    'трасс', 'разминк', 'медпункт', 'церемон', 'награжд', 'логист', 'аккредитац', 'экспо',
    'стартов', 'зону', 'зона', 'тл', 'тимлид', 'тим-лид',
)


def _norm(value):
    return re.sub(r'[^0-9a-zа-я]+', ' ', (value or '').lower().replace('ё', 'е')).strip()


def _stem(word):
    word = word.lower().replace('ё', 'е')
    return word if len(word) <= 4 else word[:max(4, len(word) - 2)]


def _normalize_phone(raw):
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits[0] in '78':
        return '+7' + digits[1:]
    return raw.strip()


def _month_of(token):
    low = token.lower()
    for stem, month in MONTHS:
        if low.startswith(stem):
            return month
    return None


def _day_value(token):
    match = re.match(r'^(\d{1,2})(?:-?(?:го|ого|е|ое|й))?$', token)
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 31 else None


def _resolve_date(day, month, today, year=None):
    """День (и месяц) без года → ближайшая НЕ прошедшая дата: желающих записывают
    заранее, поэтому «5 ноября» 11 ноября — это следующий год, а «5-го» — следующий месяц."""
    if year:
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None
    if month:
        for candidate_year in (today.year, today.year + 1):
            try:
                value = datetime.date(candidate_year, month, day)
            except ValueError:
                continue
            if value >= today:
                return value
        return None
    year_, month_ = today.year, today.month
    for _ in range(3):
        if day <= calendar.monthrange(year_, month_)[1]:
            value = datetime.date(year_, month_, day)
            if value >= today:
                return value
        month_ += 1
        if month_ > 12:
            year_, month_ = year_ + 1, 1
    return None


def _tokens(text):
    return [m.group(0) for m in TOKEN_RE.finditer(text)]


def _extract_dates(tokens, today):
    """Даты из токенов: «21.11», «14 и 15-го», «21-22», «21 ноября». Возвращает
    (даты, индексы использованных токенов)."""
    dates, used = [], set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        explicit = re.match(r'^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\.?$', token)
        if explicit:
            day, month = int(explicit.group(1)), int(explicit.group(2))
            year = explicit.group(3)
            year = (2000 + int(year) if len(year) == 2 else int(year)) if year else None
            if 1 <= month <= 12:
                value = _resolve_date(day, month, today, year)
                if value:
                    dates.append(value)
                    used.add(i)
            i += 1
            continue
        if _day_value(token) is None or (i > 0 and tokens[i - 1] == ':') or (i + 1 < len(tokens) and tokens[i + 1] == ':'):
            i += 1
            continue
        # Серия чисел: 14 и 15-го / 21-22 / 21, 22 по 23 [месяц]
        run = [(i, _day_value(token), None)]
        j = i + 1
        while j + 1 < len(tokens) and tokens[j].lower() in RANGE_SEPARATORS | LIST_SEPARATORS and _day_value(tokens[j + 1]) is not None:
            run.append((j + 1, _day_value(tokens[j + 1]), tokens[j].lower()))
            j += 2
        month = _month_of(tokens[j]) if j < len(tokens) else None
        next_token = tokens[j].lower() if j < len(tokens) else ''
        if month is None and next_token.startswith(NUMBER_UNITS):
            i = j
            continue
        days = []
        for index, (_, value, separator) in enumerate(run):
            if separator in RANGE_SEPARATORS and days and 0 < value - days[-1] <= 14:
                days.extend(range(days[-1] + 1, value + 1))
            else:
                days.append(value)
        for value in days:
            resolved = _resolve_date(value, month, today)
            if resolved:
                dates.append(resolved)
        used.update(range(i, j + (1 if month else 0)))
        i = j + (1 if month else 0)
    return dates, used


def _is_position(item, vocab_stems):
    for part in re.split(r'[/+]', item.lower().replace('ё', 'е')):
        for word in part.split():
            for stem in vocab_stems:
                if (len(stem) <= 3 and word == stem) or (len(stem) > 3 and word.startswith(stem)):
                    return True
    return False


def _pretty(item):
    return item[:1].upper() + item[1:] if item.islower() else item


def _extract_targets(tokens, used, vocab_stems):
    """Фразы после «на»: «на СКБС и на Скорость», «на ПП/дистанцию». Возвращает
    (мероприятия, позиции)."""
    events, positions = [], []
    i = 0
    rest = [(index, token) for index, token in enumerate(tokens) if index not in used]
    words = [token for _, token in rest]
    while i < len(words):
        if words[i].lower() != 'на':
            i += 1
            continue
        i += 1
        items, current = [], []
        while i < len(words):
            low = words[i].lower()
            if low == 'на':
                break
            if low in ('и', ','):
                if current:
                    items.append(current)
                    current = []
                nxt = words[i + 1].lower() if i + 1 < len(words) else ''
                if not nxt or nxt in PUNCT or nxt in PHRASE_STOP:
                    i += 1
                    break
                i += 1
                continue
            if low in PUNCT or low in PHRASE_STOP or len(current) >= 4:
                break
            current.append(words[i])
            i += 1
        if current:
            items.append(current)
        for item_words in items:
            item = ' '.join(item_words).strip(' .-')
            if not item:
                continue
            target = positions if _is_position(item, vocab_stems) else events
            if item.lower() not in {value.lower() for value in target}:
                target.append(item if target is positions else _pretty(item))
    return events, positions


def _person_name(after_text, before_text):
    for regex, text in ((NAME_AFTER_RE, after_text), (NAME_BEFORE_RE, before_text)):
        match = regex.search(text)
        if not match:
            continue
        words = []
        for word in match.group(1).split():
            if word.lower().startswith(NAME_STOP_STEMS):
                if regex is NAME_AFTER_RE:
                    break
                words = []
                continue
            words.append(word)
        if len(words) >= 2:
            return ' '.join(words), match
    return '', None


def _parse_line(line, today, vocab_stems):
    spans = []
    for match in USERNAME_RE.finditer(line):
        spans.append((match.start(), match.end(), 'username', (match.group(1) or match.group(2)).lower()))
    for match in PHONE_RE.finditer(line):
        if not any(start <= match.start() < end for start, end, *_ in spans):
            spans.append((match.start(), match.end(), 'phone', _normalize_phone(match.group(0))))
    spans.sort()
    blanks = [(start, end) for start, end, *_ in spans]
    people, current = [], None
    for index, (start, end, kind, value) in enumerate(spans):
        next_start = spans[index + 1][0] if index + 1 < len(spans) else len(line)
        prev_end = spans[index - 1][1] if index else 0
        if current is not None and not current[kind] and current.get('_last') != kind:
            current[kind] = value
        else:
            current = {'username': '', 'phone': '', 'full_name': ''}
            current[kind] = value
            people.append(current)
        current['_last'] = kind
        if not current['full_name']:
            name, match = _person_name(line[end:next_start], line[prev_end:start])
            if name:
                current['full_name'] = name
                offset = end if match.re is NAME_AFTER_RE else prev_end
                blanks.append((offset + match.start(1), offset + match.end(1)))
    content = list(line)
    for start, end in blanks:
        content[start:end] = ' ' * (end - start)
    content = ''.join(content)
    tokens = _tokens(content)
    dates, used = _extract_dates(tokens, today)
    events, positions = _extract_targets(tokens, used, vocab_stems)
    has_content = bool(dates or events or positions or re.search(r'\bхо[чт]', content.lower()))
    for person in people:
        person.pop('_last', None)
    return {'people': people, 'dates': dates, 'events': events, 'positions': positions,
            'has_content': has_content, 'text': line}


def _new_group():
    return {'people': [], 'dates': [], 'events': [], 'positions': [], 'has_content': False,
            'content_first': False, 'lines': []}


def _merge_line(group, info):
    if info['has_content'] and not group['people'] and not info['people']:
        group['content_first'] = True
    group['people'].extend(info['people'])
    for key in ('dates', 'events', 'positions'):
        for value in info[key]:
            if value not in group[key]:
                group[key].append(value)
    group['has_content'] = group['has_content'] or info['has_content']
    group['lines'].append(info['text'])


def position_stems(extra_names=()):
    """Основы слов-позиций: встроенный список + названия из пула платформы."""
    stems = set(POSITION_STEMS)
    for name in extra_names:
        for word in _norm(name).split():
            if len(word) >= 4 and not word.isdigit():
                stems.add(_stem(word))
    return stems


def parse_wish_message(text, today=None, position_vocab=()):
    """Разбирает сообщение о желающих в строки «человек × мероприятие».

    Каждая строка — dict: telegram_username (без @, нижний регистр), phone (+7…),
    full_name, event_hint, dates (list[date]), position_hint. Пустой список — в
    сообщении нет ни @юзернейма, ни телефона, ни ФИО рядом с «хочет».

    Строки сообщения группируются: строка с контактом начинает новую группу, если у
    текущей уже есть и люди, и пожелание, а у новой строки — своё пожелание (или
    пожелание в текущей шло ПОСЛЕ людей). Так «@a хочет на X\\n@b хочет на Y» — два
    разных пожелания, а «Хотят на X:\\n@a\\n@b» — одно на двоих."""
    today = today or timezone.localdate()
    vocab_stems = position_stems(position_vocab)
    groups, group = [], None
    for raw_line in (text or '').replace('\r', '').split('\n'):
        if not raw_line.strip():
            continue
        info = _parse_line(raw_line, today, vocab_stems)
        if group is None:
            group = _new_group()
            groups.append(group)
        elif info['people'] and group['people'] and group['has_content'] and (
            info['has_content'] or not group['content_first']
        ):
            group = _new_group()
            groups.append(group)
        _merge_line(group, info)

    rows = []
    for group in groups:
        people = group['people']
        if not people:
            match = NAME_ONLY_RE.search(' '.join(group['lines']))
            if match and not match.group(1).split()[0].lower().startswith(NAME_STOP_STEMS):
                people = [{'username': '', 'phone': '', 'full_name': match.group(1)}]
        seen = set()
        for person in people:
            key = (person['username'], person['phone'], person['full_name'])
            if key in seen:
                continue
            seen.add(key)
            dates = sorted(set(group['dates']))
            position = ', '.join(group['positions'])
            for event in group['events'] or ['']:
                rows.append({
                    'telegram_username': person['username'],
                    'phone': person['phone'],
                    'full_name': person['full_name'],
                    'event_hint': event,
                    'dates': dates,
                    'position_hint': position,
                })
    return rows


def parse_dates_text(text, today=None):
    """Даты из свободного текста формы правки («21.11.2026, 22.11» / «21-22 ноября»)."""
    dates, _ = _extract_dates(_tokens(text or ''), today or timezone.localdate())
    return sorted(set(dates))


def _position_vocab():
    names = list(dc.event_functions_qs().values_list('name', flat=True))
    names += list(dc.event_categories_qs().values_list('name', flat=True))
    names += list(dc.position_templates_qs().values_list('name', flat=True))
    return names


# ---------------------------------------------------------------------------
# ACL
# ---------------------------------------------------------------------------

def can_manage_wishes(user) -> bool:
    """Видеть табличку, добавлять и забирать желающих — тим-лидер или менеджер."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return has_manager_access(user) or is_team_leader(user)


def can_edit_wish(user, wish) -> bool:
    return can_manage_wishes(user) and (has_manager_access(user) or wish.added_by_id == user.id)


def can_untake_wish(user, wish) -> bool:
    """Вернуть из «забрали» в желающие — любой ТЛ/менеджер: табличка — общий пул
    сообщества, кто и когда забирал, видно в строке."""
    return can_manage_wishes(user)


# ---------------------------------------------------------------------------
# Операции
# ---------------------------------------------------------------------------

def _match_user(row):
    first_name = last_name = None
    parts = row['full_name'].split()
    if len(parts) >= 2:
        # В чатах пишут «Фамилия Имя».
        last_name, first_name = parts[0], parts[1]
    return dc.find_matching_user(
        telegram_username=row['telegram_username'] or None, phone=row['phone'] or None,
        first_name=first_name, last_name=last_name,
    )


def add_wishes_from_message(actor_user, text, source='web', today=None):
    """Разобрать сообщение и записать желающих. Возвращает (строки, ошибка):
    'forbidden' — не ТЛ/менеджер, 'no_people' — в сообщении никого не нашли."""
    if not can_manage_wishes(actor_user):
        return [], 'forbidden'
    text = (text or '').strip()[:4000]
    rows = parse_wish_message(text, today=today, position_vocab=_position_vocab())
    if not rows:
        return [], 'no_people'
    batch_id = uuid.uuid4()
    created = []
    with transaction.atomic():
        for row in rows:
            created.append(dc.create_volunteer_wish(
                added_by=actor_user,
                telegram_username=row['telegram_username'][:100],
                phone=row['phone'][:20],
                full_name=row['full_name'][:255],
                user=_match_user(row),
                event_hint=row['event_hint'][:255],
                wish_dates=[value.isoformat() for value in row['dates']],
                position_hint=row['position_hint'][:255],
                raw_text=text,
                batch_id=batch_id,
                source=source,
            ))
    logger.info('Табличка желающих: добавлено %s строк batch=%s source=%s by=%s', len(created), batch_id, source, actor(actor_user))
    return created, None


def update_wish(actor_user, wish, data):
    """Ручная правка строки (форма сайта). data — cleaned_data формы правки."""
    if not can_edit_wish(actor_user, wish):
        return None, 'forbidden'
    fields = {
        'telegram_username': (data.get('telegram_username') or '').strip().lstrip('@').lower()[:100],
        'phone': _normalize_phone(data.get('phone') or '')[:20] if data.get('phone') else '',
        'full_name': (data.get('full_name') or '').strip()[:255],
        'event_hint': (data.get('event_hint') or '').strip()[:255],
        'position_hint': (data.get('position_hint') or '').strip()[:255],
        'wish_dates': [value.isoformat() for value in data.get('dates') or []],
    }
    fields['user'] = _match_user(fields)
    return dc.update_volunteer_wish(wish, operator=actor_user, **fields), None


def _wish_or_error(actor_user, wish_id):
    if not can_manage_wishes(actor_user):
        return None, 'forbidden'
    wish = dc.get_volunteer_wish(wish_id)
    return (wish, None) if wish else (None, 'not_found')


def mark_wish_taken(actor_user, wish_id, group_id):
    """«Отметить, что забрал» в мероприятие group_id."""
    wish, error = _wish_or_error(actor_user, wish_id)
    if error:
        return None, error
    group = dc.event_groups_qs().filter(pk=group_id).first()
    if group is None:
        return None, 'not_found'
    return dc.set_volunteer_wish_taken(wish, group, operator=actor_user), None


def unmark_wish_taken(actor_user, wish_id):
    wish, error = _wish_or_error(actor_user, wish_id)
    if error:
        return None, error
    if not can_untake_wish(actor_user, wish):
        return None, 'forbidden'
    return dc.set_volunteer_wish_taken(wish, None, operator=actor_user), None


def delete_wish(actor_user, wish_id):
    wish, error = _wish_or_error(actor_user, wish_id)
    if error:
        return error
    if not can_edit_wish(actor_user, wish):
        return 'forbidden'
    dc.delete_volunteer_wishes([wish], operator=actor_user)
    return None


def delete_wish_batch(actor_user, batch_id):
    """«Отменить запись» из бота: удаляет строки одного сообщения — только автор."""
    if not can_manage_wishes(actor_user):
        return 0, 'forbidden'
    try:
        batch_id = uuid.UUID(str(batch_id))
    except ValueError:
        return 0, 'not_found'
    rows = list(dc.volunteer_wishes_qs().filter(batch_id=batch_id))
    if not rows:
        return 0, 'not_found'
    if any(row.added_by_id != actor_user.id for row in rows):
        return 0, 'forbidden'
    return dc.delete_volunteer_wishes(rows, operator=actor_user), None


# ---------------------------------------------------------------------------
# Сопоставление с мероприятием и выборки для страниц
# ---------------------------------------------------------------------------

def _acronym(title):
    return ''.join(word[0] for word in _norm(title).split() if not word.isdigit())


def name_matches(hint, title) -> bool:
    """Подходит ли название из сообщения к мероприятию: каждое слово подсказки — слово
    (или основа) названия, либо подсказка — аббревиатура названия («СКБС»)."""
    words = [word for word in _norm(hint).split() if not word.isdigit()]
    if not words:
        return False
    tokens = [word for word in _norm(title).split() if not word.isdigit()]
    if len(words) == 1 and len(words[0]) >= 2 and words[0] == _acronym(title):
        return True
    return all(any(token == word or token.startswith(_stem(word)) for token in tokens) for word in words)


def match_reason(wish, title, days):
    """Почему строка подходит мероприятию: 'name' / 'dates' / None."""
    if wish.event_hint:
        return 'name' if name_matches(wish.event_hint, title) else None
    if days and set(wish.dates) & set(days):
        return 'dates'
    return None


def hide_days() -> int:
    """Сколько дней «Забрали» висит в табличке (Const, по умолчанию 3)."""
    try:
        return max(0, int(dc.get_const('wish_taken_hide_days', default=3)))
    except (TypeError, ValueError):
        return 3


def _group_last_days(group_ids):
    """Последний день смен каждого мероприятия — чтобы понять, что оно прошло."""
    rows = (dc.event_shifts_qs().filter(event__event_group_id__in=set(group_ids))
            .values('event__event_group_id').annotate(last=Max('day')))
    return {row['event__event_group_id']: row['last'] for row in rows}


def _apply_lifecycle(wishes, viewer):
    """Помечает строки: can_edit/can_untake, `hide_on` (когда «забрали» уйдёт из
    таблички) и `archived` — мероприятие, куда забрали, прошло, или статус висит
    дольше hide_days(). Архивные из таблички пропадают, но запись цела."""
    wishes = list(wishes)
    last_days = _group_last_days(w.taken_event_group_id for w in wishes if w.taken_event_group_id)
    today = timezone.localdate()
    days = hide_days()
    for wish in wishes:
        wish.can_edit = can_edit_wish(viewer, wish)
        wish.can_untake = bool(wish.taken_event_group_id) and can_untake_wish(viewer, wish)
        wish.hide_on = wish.archived = None
        if not wish.taken_event_group_id:
            wish.archived = False
            continue
        limits = []
        if wish.taken_at:
            limits.append(timezone.localtime(wish.taken_at + datetime.timedelta(days=days)).date())
        last = last_days.get(wish.taken_event_group_id)
        if last:
            limits.append(last + datetime.timedelta(days=1))
        wish.hide_on = min(limits) if limits else None
        expired_by_time = wish.taken_at and wish.taken_at <= timezone.now() - datetime.timedelta(days=days)
        expired_by_event = last is not None and last < today
        wish.archived = bool(expired_by_time or expired_by_event)
    return wishes


def _sort_key(wish):
    # Сначала не забранные (раньше попросились — выше), забранные — в конце.
    return (wish.taken_event_group_id is not None, wish.created_at)


def wishes_for_event_group(group, viewer, hide_taken=False):
    """Табличка на странице мероприятия.

    matched — подходят по названию/датам (в т.ч. уже забранные куда-то — со статусом
    «Забрали в «X»», чтобы не забирать человека дважды) и забранные сюда; others — не
    забранные без совпадения (чтобы никого не потерять). Архивные строки не показываются;
    hide_taken — скрыть всех со статусом «Забрали»."""
    days = set(dc.event_shifts_qs().filter(event__event_group=group).values_list('day', flat=True))
    matched, others = [], []
    for wish in _apply_lifecycle(dc.volunteer_wishes_qs(), viewer):
        if wish.archived or (hide_taken and wish.taken_event_group_id):
            continue
        if wish.taken_event_group_id == group.pk:
            wish.match = 'taken'
            matched.append(wish)
            continue
        wish.match = match_reason(wish, group.title, days)
        if wish.match:
            matched.append(wish)
        elif not wish.taken_event_group_id:
            others.append(wish)
    matched.sort(key=_sort_key)
    others.sort(key=_sort_key)
    return {'matched': matched, 'others': others,
            'open_count': sum(1 for wish in matched if not wish.taken_event_group_id)}


WISH_FILTERS = {
    'active': 'Желающие',
    'mine': 'Мои',
    'archive': 'Архив забранных',
}


def wishes_list(viewer, status='active', hide_taken=False):
    """Общая табличка (страница из профиля): active — желающие и «забрали» до срока,
    mine — добавленные мной (тоже без архива), archive — ушедшие из таблички."""
    qs = dc.volunteer_wishes_qs()
    if status == 'mine':
        qs = qs.filter(added_by=viewer)
    rows = _apply_lifecycle(qs, viewer)
    if status == 'archive':
        rows = [wish for wish in rows if wish.archived]
    else:
        rows = [wish for wish in rows if not wish.archived and not (hide_taken and wish.taken_event_group_id)]
    return sorted(rows, key=_sort_key)


def describe_wish(wish) -> str:
    """Короткое описание строки для бота (HTML-экранировано)."""
    who = []
    if wish.telegram_username:
        who.append(f'@{wish.telegram_username}')
    if wish.full_name:
        who.append(wish.full_name)
    if wish.phone:
        who.append(wish.phone)
    what = []
    if wish.event_hint:
        what.append(wish.event_hint)
    if wish.dates:
        what.append(', '.join(value.strftime('%d.%m') for value in wish.dates))
    if wish.position_hint:
        what.append(f'позиция: {wish.position_hint}')
    line = ' '.join(who) + ' — ' + (' · '.join(what) if what else 'на ближайший забег')
    if wish.user_id:
        line += ' (есть на платформе)'
    return html.escape(line)
