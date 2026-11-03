"""Общие операции выдачи для QR и таблицы позиции; данные только через контроллер."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from data_base import data_controller as dc
from blog.services.roles import can_process_applications


def change_handout(user, shift, operator, kind, checked, at):
    """Применить состояние выдачи после проверки вызывающим сервисом участия и ACL."""
    if kind not in ('lunch', 'badge') or not isinstance(checked, bool):
        raise ValidationError('Некорректная отметка выдачи.')
    if kind == 'lunch':
        if checked:
            dc.issue_shift_meal(user, shift, operator, at)
        else:
            dc.revoke_shift_meal(user, shift, operator)
    elif not shift.event.event_group_id:
        raise ValidationError('У позиции не указано мероприятие для выдачи жетона.')
    elif checked:
        dc.issue_event_badge(user, shift.event.event_group, operator, at)
    else:
        dc.revoke_event_badge(user, shift.event.event_group, operator)


def position_handouts(event):
    """Два запроса на всю позицию вместо запросов для каждой строки каждой смены."""
    meals = set(dc.shift_meals_qs().filter(shift__event=event).values_list('user_id', 'shift_id'))
    badges = set(dc.event_badges_qs().filter(event_group_id=event.event_group_id).values_list('user_id', flat=True)) if event.event_group_id else set()
    return meals, badges


@transaction.atomic
def set_participation_handout(operator, participation_id, kind, checked):
    part = dc.participations_qs().select_related('user', 'event_day__event__event_group').filter(pk=participation_id).first()
    if not part:
        raise Http404('Участие не найдено.')
    if not can_process_applications(operator, part.event_day.event_id):
        raise PermissionDenied('Нет доступа к выдаче на этой позиции.')
    if part.event_day.event.event_status == 'finished':
        raise PermissionDenied('Позиция завершена. Сначала откройте её для редактирования.')
    dc.users_qs().select_for_update().get(pk=part.user_id)
    change_handout(part.user, part.event_day, operator, kind, checked, timezone.now())
    return {'checked': checked, 'kind': kind, 'user_id': part.user_id,
            'shift_id': part.event_day_id, 'group_id': part.event_day.event.event_group_id}
