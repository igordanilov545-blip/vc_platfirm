"""Расхождения анкеты с загруженными старыми базами (решение пользователя 2026-11-11).

В профиле — только самые актуальные данные:
- пустое поле дополняется значением из базы;
- профиль, созданный базами (служебный legacy:*/import:* аккаунт): более новая
  база (год) обновляет данные, более старая — нет;
- профиль, который человек заполнял сам (настоящий Telegram или веб-логин), молча
  не меняется: расхождение уходит человеку, при входе он выбирает актуальное.
Каждое изменение и расхождение описывается в комментарии, видимом только
сотрудникам (UserComment.source='legacy_changes').
"""
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from data_base import data_controller as dc
from blog.services.legacy_workbook import phone_key, phone_number
from blog.services.social_profiles import social_username


FIELDS = {
    'first_name': 'Имя', 'last_name': 'Фамилия', 'birthday': 'Дата рождения', 'email': 'Почта',
    'phone': 'Телефон', 'telegram_username': 'Telegram', 'VK_username': 'ВКонтакте',
    'instagram_url': 'Instagram', 'tshirt_size': 'Размер футболки',
    'weekday_daytime_available': 'Помощь в будни днём', 'wants_team_lead': 'Желание стать тим-лидером',
    'volunteer_experience': 'Опыт волонтёрства', 'motivation': 'Мотивация',
    'familiar_positions': 'Знакомые позиции', 'performed_tasks': 'Выполняемые задачи',
}
BOOLEAN_FIELDS = {'weekday_daytime_available', 'wants_team_lead'}
TEXT_LIMITS = {'first_name': 100, 'last_name': 100, 'phone': 20, 'telegram_username': 100, 'VK_username': 100,
               'instagram_url': 255, 'volunteer_experience': 255, 'motivation': 255, 'familiar_positions': 255,
               'performed_tasks': 255}
SIZES = ('XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL')


def is_self_managed(user):
    """Человек сам ведёт профиль: вошёл через настоящий Telegram или веб-логин."""
    return str(user.telegram_id).isdigit() or bool(user.login)


def _empty(value):
    return value is None or isinstance(value, str) and not value.strip()


def _comparable(field, value):
    if _empty(value):
        return None
    if field == 'birthday':
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if field == 'phone':
        return phone_key(value) or str(value).strip().casefold()
    if field == 'telegram_username':
        return social_username(value, 'telegram').casefold() or str(value).strip().casefold()
    if field in BOOLEAN_FIELDS:
        return bool(value)
    return ' '.join(str(value).split()).casefold().replace('ё', 'е')


def display(field, value):
    if _empty(value):
        return '—'
    if field in BOOLEAN_FIELDS:
        return 'да' if value else 'нет'
    if field == 'birthday':
        value = date.fromisoformat(value) if isinstance(value, str) else value
        return value.strftime('%d.%m.%Y')
    return str(value)


def _stored(field, value):
    return date.fromisoformat(value) if field == 'birthday' and isinstance(value, str) else value


def sync_profile_from_base(operator, user, profile, base):
    """Сверить существующий профиль со строкой базы; вернуть счётчики изменений."""
    years = set(dc.legacy_base_people_qs().filter(user=user).exclude(base=base).values_list('base__year', flat=True))
    self_managed = is_self_managed(user)
    updates, notes, conflicts = {}, [], 0
    for field, label in FIELDS.items():
        proposed = profile.get(field)
        if _empty(proposed) or field in ('first_name', 'last_name') and str(proposed).casefold() == 'unnamed':
            continue
        current = getattr(user, field)
        if _comparable(field, current) == _comparable(field, proposed):
            continue
        shown_current, shown_proposed = display(field, current), display(field, proposed)
        if _empty(current):
            updates[field] = _stored(field, proposed)
            notes.append(f'{label}: дополнено «{shown_proposed}»')
        elif self_managed:
            dc.create_profile_conflict(user, field, shown_current, shown_proposed, f'База {base.year}')
            conflicts += 1
            notes.append(f'{label}: в профиле «{shown_current}», в базе «{shown_proposed}» — уточняется у человека')
        elif years and base.year >= max(years):
            updates[field] = _stored(field, proposed)
            notes.append(f'{label}: «{shown_current}» → «{shown_proposed}»')
        else:
            notes.append(f'{label}: в базе «{shown_proposed}», оставлено актуальное «{shown_current}»')
    if updates:
        dc.update_user_profile_fields(user, updates, operator, 'legacy base')
    if notes:
        dc.ensure_legacy_comment(user, 'legacy_changes', f'База {base.year} ({base.file_name}):\n' + '\n'.join(notes), operator)
    return {'conflicts': conflicts, 'updated': len(updates)}


def pending_conflicts(user):
    if not user or not user.is_authenticated:
        return dc.profile_conflicts_qs().none()
    return dc.profile_conflicts_qs().filter(user=user, resolved_at__isnull=True)


def _parse(field, raw):
    """Проверить введённое/выбранное значение по типу поля профиля."""
    value = (raw or '').strip()
    if not value:
        raise ValidationError('Укажите значение.')
    if field == 'email':
        validate_email(value)
        return value
    if field == 'birthday':
        for pattern in ('%d.%m.%Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                continue
        raise ValidationError('Дата в формате ДД.ММ.ГГГГ.')
    if field in BOOLEAN_FIELDS:
        if value.casefold() in ('да', 'нет'):
            return value.casefold() == 'да'
        raise ValidationError('Ответьте «да» или «нет».')
    if field == 'tshirt_size':
        if value.upper() in SIZES:
            return value.upper()
        raise ValidationError('Размер: ' + ', '.join(SIZES) + '.')
    if field == 'phone':
        return phone_number(value) or value[:20]
    limit = TEXT_LIMITS.get(field, 255)
    if len(value) > limit:
        raise ValidationError(f'Не длиннее {limit} символов.')
    return value


def resolve_conflicts(user, data):
    """data: choice_<id> = current|proposed|custom, custom_<id> = текст. Возвращает ошибки по id."""
    errors, updates, resolved = {}, {}, []
    for conflict in pending_conflicts(user):
        choice = data.get(f'choice_{conflict.pk}')
        if choice not in ('current', 'proposed', 'custom'):
            continue
        if choice == 'current':
            resolved.append((conflict, conflict.current_value))
            continue
        raw = conflict.proposed_value if choice == 'proposed' else data.get(f'custom_{conflict.pk}', '')
        try:
            value = _parse(conflict.field, raw)
        except ValidationError as error:
            errors[conflict.pk] = ' '.join(error.messages)
            continue
        updates[conflict.field] = value
        resolved.append((conflict, display(conflict.field, value)))
    if errors:
        return errors
    if updates:
        dc.update_user_profile_fields(user, updates, user, 'profile actualization')
    for conflict, value in resolved:
        dc.resolve_profile_conflict(conflict, value)
    return {}
