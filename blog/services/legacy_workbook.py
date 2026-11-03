"""Чтение листа «База» без обращений к БД и без исполнения формул Excel."""
from datetime import date
from io import BytesIO
import re
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from openpyxl import load_workbook
from blog.services.fap_workbook import normalized_name, _date
from blog.services.social_profiles import social_value


def key(value):
    return re.sub(r'[\W_]+', '', normalized_name(value))


FIELDS = {
    'Имя': 'first_name', 'Фамилия': 'last_name', 'Дата рождения': 'birthday',
    'Электронная почта': 'email', 'Мобильный телефон': 'phone', 'Ник в Telegram': 'telegram_username',
    'Ссылка на вашу страницу в ВКонтакте': 'VK_username', 'Ссылка на вашу страницу в Инстаграме': 'instagram_url',
    'Вы могли бы помогать нам в дневное время в будни?': 'weekday_daytime_available',
    'Опыт волонтёрства': 'volunteer_experience', 'Мотивация быть волонтёром': 'motivation',
    'Знакомые позиции': 'familiar_positions', 'Выполняемые задачи': 'performed_tasks',
    'Желание стать тим-лидером': 'wants_team_lead', 'Размер футболки': 'tshirt_size',
    'Комментарий координатора': 'coordinator_comment', 'Комментарий тим-лидера': 'leader_comment', 'Возраст': 'reported_age',
}
FIELD_KEYS = {key(label): name for label, name in FIELDS.items()}
IGNORED = {key(label) for label in ('Дата заполнения анкеты', 'Наиболее удобный способ связи',
           'В каких забегах планируете принять участие', 'Число смен', 'VOLUNTEER_ID')}
MONTHS = ('январ', 'феврал', 'март', 'апрел', 'ма', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр')


def phone_key(value):
    digits = re.sub(r'\D', '', text(value))
    return '7' + digits[1:] if len(digits) == 11 and digits.startswith('8') else digits


def text(value):
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value if value is not None else '').strip()


def phone_number(value):
    raw = text(value)
    digits = phone_key(value)
    return '+' + digits if digits and any(digit != '0' for digit in digits) and len(digits) <= 19 and re.fullmatch(r'[\d+\s().-]+', raw) else ''


def yes_no(value):
    words = set(re.findall(r'\b(?:да|нет)\b', text(value).casefold()))
    return 'да' in words if len(words) == 1 else None


def column_day(header):
    raw = text(header)
    match = re.search(r'(?<!\d)(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[./-]\d{1,2}(?:[./-](?:\d{4}|\d{2}))?)(?!\d)', raw)
    numeric = _date(match[0], reference='2026-01-01') if match else None
    if numeric:
        return numeric
    match = re.search(r'(?<!\d)(\d{1,2})\s*([а-яё]+)(?:\s*(\d{4}))?', raw.casefold())
    if match:
        month = next((index for index, stem in enumerate(MONTHS, 1) if match[2].startswith(stem)), 0)
        try:
            return date(int(match[3] or 2026), month, int(match[1])).isoformat()
        except ValueError:
            pass
    return None


def column_group(header):
    first = text(header).splitlines()[0].strip()
    first = re.split(r'(?<!\d)\d{1,2}(?:[./-]|\s+[а-яё])', first, maxsplit=1, flags=re.I)[0]
    first = re.sub(r'\([^)]*резерв[^)]*\)', '', first, flags=re.I)
    first = first.split(',', 1)[0]
    first = re.sub(r'\s+(?:пн|вт|ср|чт|чтв|пт|сб|вс)\s*$', '', first, flags=re.I)
    return first.strip(' ,;—-\n') or text(header).splitlines()[0].strip()


def position_name(value):
    raw = text(value)
    match = re.match(r'^\s*(\d+(?:[.,]\d+)*)(?=\s|[-–—:.)]|$)', raw)
    return match[1].replace(',', '.') if match else raw[:255]


def read_legacy_workbook(content, *, max_rows=10000):
    try:
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except Exception as error:
        raise ValidationError('Не удалось прочитать XLSX-файл.') from error
    try:
        names = [name for name in wb.sheetnames if key(name) == key('База')]
        if len(names) != 1:
            raise ValidationError('Нужен один лист «База» (регистр и пробелы не учитываются).')
        ws = wb[names[0]]
        if ws.max_column is not None and ws.max_column > 512:
            raise ValidationError('В листе больше 512 колонок. Уберите лишние пустые колонки.')

        def checked_rows():
            # Некоторые экспортёры не записывают dimension. Читаем поток без
            # предварительного второго прохода, лимит проверяем по самим строкам.
            for values in ws.iter_rows(values_only=True):
                if len(values) > 512:
                    raise ValidationError('В листе больше 512 колонок. Уберите лишние пустые колонки.')
                yield values

        iterator = iter(checked_rows())
        header = None
        for row_number in range(1, 31):
            values = next(iterator, ())
            if key('Имя') in {key(value) for value in values} and key('Фамилия') in {key(value) for value in values}:
                header = values
                break
        if header is None:
            raise ValidationError('Не найдены колонки «Имя» и «Фамилия».')
        mapping = {}
        columns = []
        for index, value in enumerate(header):
            normalized = key(value)
            if normalized in FIELD_KEYS:
                field = FIELD_KEYS[normalized]
                if field in mapping:
                    raise ValidationError(f'Дублируется колонка «{text(value)}».')
                mapping[field] = index
            elif normalized and normalized not in IGNORED:
                columns.append({'index': index, 'header': text(value), 'group': column_group(value),
                                'day': column_day(value), 'used': 0})
        rows, errors, warnings = [], [], []
        for number, values in enumerate(iterator, row_number + 1):
            if number - row_number > max_rows:
                raise ValidationError(f'В файле больше {max_rows} строк. Разделите его на части.')
            if not any(value is not None and text(value) for value in values):
                continue
            get = lambda name: values[mapping[name]] if name in mapping and mapping[name] < len(values) else None
            profile = {name: text(get(name))[:255] for name in ('volunteer_experience', 'motivation', 'familiar_positions', 'performed_tasks')}
            for name in ('first_name', 'last_name'):
                profile[name] = text(get(name))[:100] or 'unnamed'
            profile['birthday'] = _date(get('birthday'), epoch=wb.epoch)
            for field, platform in (('telegram_username', 'telegram'), ('VK_username', 'vk'), ('instagram_url', 'instagram')):
                maximum = 255 if platform == 'instagram' else 100
                profile[field] = social_value(get(field), platform)[:maximum]
            profile['phone'] = phone_number(get('phone')) or text(get('phone'))[:20]
            profile['email'] = text(get('email'))
            try:
                if profile['email']:
                    validate_email(profile['email'])
            except ValidationError:
                profile['email'] = ''
            profile.update({name: yes_no(get(name)) for name in ('weekday_daytime_available', 'wants_team_lead')})
            size = text(get('tshirt_size')).upper()
            profile['tshirt_size'] = size if size in ('XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL') else ''
            profile['preferred_contact_methods'] = []
            assignments = []
            for column in columns:
                value = values[column['index']] if column['index'] < len(values) else None
                if text(value):
                    column['used'] += 1
                    assignments.append({'column': column['index'], 'position': position_name(value), 'description': text(value)[:255]})
            try:
                age = int(get('reported_age'))
                age = age if 0 <= age <= 120 else None
            except (ValueError, TypeError):
                age = None
            rows.append({'number': number, 'profile': profile, 'reported_age': age, 'assignments': assignments,
                         'comments': {'legacy_coordinator': text(get('coordinator_comment')), 'legacy_team_lead': text(get('leader_comment'))}})
        return {'rows': rows, 'columns': columns, 'errors': errors, 'warnings': warnings}
    finally:
        wb.close()
