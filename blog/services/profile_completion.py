"""Единый состав полной анкеты и её заполненность, без обращений к БД."""
from collections.abc import Mapping


def can_view_questionnaire(operator, target):
    from .roles import has_manager_access, is_team_leader
    return operator.pk != target.pk and (has_manager_access(operator) or is_team_leader(operator))


PROFILE_SECTIONS = (
    ('personal', 'Основная информация', ('first_name', 'last_name', 'middle_name', 'system_username', 'birthday', 'gender', 'about')),
    ('contacts', 'Контакты', ('telegram_username', 'phone', 'email', 'VK_username', 'instagram_url', 'preferred_contact_methods')),
    ('volunteering', 'Волонтёрство', ('weekday_daytime_available', 'volunteer_experience', 'motivation', 'familiar_positions', 'performed_tasks', 'wants_team_lead', 'tshirt_size')),
)


def profile_completion(source):
    fields = [name for _, _, names in PROFILE_SECTIONS for name in names]

    def filled(name):
        value = source.get(name) if isinstance(source, Mapping) else getattr(source, name, None)
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, bool):
            return True
        return bool(value)

    count = sum(filled(name) for name in fields)
    return {'filled': count, 'total': len(fields), 'percent': round(100 * count / len(fields))}
