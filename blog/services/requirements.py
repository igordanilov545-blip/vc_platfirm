"""Проверка соответствия волонтёра требованиям мероприятия при подаче заявки.

Исходим из того, что ВСЕ волонтёры по умолчанию соответствуют ВСЕМ требованиям —
несоответствие фиксируется белым списком исключений (UserRequirementException) для
требований с check_type='manual', либо проверяется автоматически по дате рождения
для требования с check_type='age' (пользователь просил конкретно «18+»).

Если волонтёр не соответствует хотя бы одному требованию меро — заявка при подаче
СРАЗУ уходит в резерв (status='rejected'), но пользователю не показывается никакого
особого сообщения (обычное «заявка отправлена» — как при любой другой подаче);
тим-лидеру в уведомлении о новой заявке указывается причина.
"""
import datetime
from django.utils import timezone

from data_base import data_controller as dc


def _age_on(birthday: datetime.date, today: datetime.date) -> int:
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))


def check_application_requirements(event, user) -> dict:
    """Возвращает {'auto_reject': bool, 'reasons': [str, ...], 'unknown_age': bool}.

    `reasons` — человекочитаемые причины несоответствия (для уведомления/поля
    auto_reject_reason). `unknown_age` — True, если у меро есть требование «18+», а
    дата рождения волонтёра неизвестна (заявка НЕ уходит в резерв по одной лишь
    неизвестности возраста — это только пометка для тим-лидера)."""
    requirements = list(dc.requirements_qs().filter(event_map__event=event))
    reasons = []
    unknown_age = False

    if not requirements or not user:
        return {'auto_reject': False, 'reasons': [], 'unknown_age': False}

    exception_ids = set(
        dc.user_requirement_exceptions_qs().filter(
            user=user, requirement__in=requirements
        ).values_list('requirement_id', flat=True)
    )

    today = timezone.localdate()
    for req in requirements:
        if req.check_type == 'age':
            if not user.birthday:
                unknown_age = True
                continue
            if _age_on(user.birthday, today) < 18:
                reasons.append(f'не выполнено требование «{req.title}» (возраст менее 18 лет)')
        else:
            if req.id in exception_ids:
                reasons.append(f'не выполнено требование «{req.title}»')

    return {'auto_reject': bool(reasons), 'reasons': reasons, 'unknown_age': unknown_age}
