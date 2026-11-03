"""Персональный QR и ACL фактического входа/выхода; db.md, раздел QR."""
from io import BytesIO
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import qrcode
from qrcode.util import QRData, MODE_8BIT_BYTE
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Min, Max, Q
from django.utils import timezone

from data_base import data_controller as dc
from blog.services.roles import has_manager_access, is_team_leader
from blog.services.stats import recalc_user_aggregates


def personal_token(user):
    """Один постоянный 32-байтный ASCII-токен на пользователя, даже незаполненного."""
    return dc.user_qr(user).token


def qr_matrix(token):
    """Строго version 2-L, byte mode; URL и ФИО внутрь не добавляются."""
    qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=12, border=4)
    qr.add_data(QRData(token.encode('ascii'), mode=MODE_8BIT_BYTE))
    qr.make(fit=False)
    return qr


def personal_qr_png(user):
    """Генерирует PNG по токену: крупное изображение не хранится в строке пользователя."""
    output = BytesIO()
    qr_matrix(personal_token(user)).make_image(fill_color='black', back_color='white').save(output, format='PNG')
    return output.getvalue()


def can_scan(user):
    """Право открыть сканер: менеджер, ТЛ либо отдельный активный доступ."""
    if not user or not user.is_authenticated:
        return False
    return has_manager_access(user) or is_team_leader(user) or dc.scanner_grants_qs().filter(user=user, revoked_at=None).exists()


def can_mark_shift(user, shift):
    """Просмотр всех смен не расширяет право отмечать чужие мероприятия."""
    if has_manager_access(user):
        return True
    if not dc.get_const('qr_scanner_scoped_access', default=0):
        return can_scan(user)
    if is_team_leader(user) and dc.event_staff_qs().filter(event=shift.event, user=user, staff_role='team_lead').exists():
        return True
    return bool(shift.event.event_group_id and dc.scanner_grants_qs().filter(user=user, event_group_id=shift.event.event_group_id, revoked_at=None).exists())


def _scanned_user(operator, token):
    if not can_scan(operator):
        raise PermissionDenied('Нет доступа к сканеру.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32}', token or ''):
        raise ValidationError('QR-код не распознан.')
    user = dc.user_from_qr(token)
    if not user:
        raise ValidationError('QR-код не найден.')
    return user


def _available_shifts(user):
    """Будущие/текущие смены и прошедшие внутри ещё идущего мероприятия."""
    now = timezone.now()
    open_entries = dc.shift_attendance_qs().filter(user=user, exited_at=None).values('shift_id')
    ongoing_groups = dc.event_groups_qs().annotate(
        begins=Min('positions__shifts__start_time'), ends=Max('positions__shifts__end_time'),
    ).filter(begins__lte=now, ends__gte=now).values('pk')
    ongoing_positions = dc.events_qs().annotate(begins=Min('shifts__start_time'), ends=Max('shifts__end_time')).filter(begins__lte=now, ends__gte=now).values('pk')
    return dc.event_shifts_qs().filter(
        Q(participations__user=user, participations__status='pending') | Q(pk__in=open_entries),
    ).filter(
        Q(end_time__gte=now) | Q(event__event_group_id__in=ongoing_groups) | Q(event_id__in=ongoing_positions)
        | Q(pk__in=open_entries),
    ).select_related('event__event_group').distinct()


def scan_context(operator, token):
    """Мини-карточка без контактов: ФИО, незаконченные отметки и порядок смен."""
    user = _scanned_user(operator, token)
    records = {row.shift_id: row for row in dc.shift_attendance_qs().filter(user=user).select_related('shift__event__event_group')}
    now = timezone.now()
    shifts = sorted(_available_shifts(user), key=lambda shift: (shift.end_time < now, shift.start_time, shift.pk))
    rows = []
    for shift in shifts:
        record = records.get(shift.pk)
        if record and record.exited_at:
            continue
        rows.append({'shift': shift, 'attendance': record,
                     'action': 'out' if record else 'in',
                     'can_mark': shift.event.event_status != 'finished' and can_mark_shift(operator, shift)})
    return {'scanned_user': user, 'shift_rows': rows, 'nearest_shift': rows[0]['shift'] if rows else None,
            'last_attendance': max(records.values(), key=lambda row: (row.exited_at or row.entered_at, row.pk), default=None),
            'enrollment_shifts': _enrollment_shifts(operator, user),
            'checkin_lead_minutes': dc.get_const('qr_enroll_checkin_lead_minutes', default=60)}


def _enrollment_shifts(operator, user):
    """Открытый набор: только ещё не закончившиеся смены в области прав оператора."""
    shifts = dc.event_shifts_qs().filter(recruit_status='open', end_time__gt=timezone.now()).exclude(
        event__event_status='finished',
    ).exclude(participations__user=user).select_related('event__event_group').order_by('start_time', 'pk')
    if not has_manager_access(operator) and dc.get_const('qr_scanner_scoped_access', default=0):
        groups = dc.scanner_grants_qs().filter(user=operator, revoked_at=None).values('event_group_id')
        scope = Q(event__event_group_id__in=groups)
        if is_team_leader(operator):
            positions = dc.event_staff_qs().filter(user=operator, staff_role='team_lead').values('event_id')
            scope |= Q(event_id__in=positions)
        shifts = shifts.filter(scope)
    return shifts


@transaction.atomic
def enroll_scanned_user(operator, token, shift_id):
    """Ручное одобрение одной смены; при скором начале сразу фиксируется вход."""
    from blog.services.applications import create_manual_application, application_shifts, ensure_shift_decisions, process_shift_decision
    from blog.services.requirements import check_application_requirements

    user = _scanned_user(operator, token)
    # Сериализуем параллельные записи одного человека, в том числе создание заявки.
    user = dc.users_qs().select_for_update().get(pk=user.pk)
    shift = dc.event_shifts_qs().filter(pk=shift_id).select_related('event__event_group').first()
    if not shift:
        raise ValidationError('Смена не найдена.')
    if not can_mark_shift(operator, shift):
        raise PermissionDenied('Нет права записывать на эту смену.')
    if dc.participations_qs().filter(user=user, event_day=shift).exists():
        return 'Участник уже записан на смену.'
    if not _enrollment_shifts(operator, user).filter(pk=shift.pk).exists():
        raise ValidationError('Набор закрыт, смена закончилась или позиция завершена.')
    requirements = check_application_requirements(shift.event, user)
    if requirements['auto_reject']:
        raise ValidationError('; '.join(requirements['reasons']))
    application, created = create_manual_application(shift.event, user, operator, shifts=[shift])
    if not created:
        # Сначала материализуем прежние решения: общий approved не должен
        # автоматически одобрять новую смену при расширении выбора.
        ensure_shift_decisions(application)
        selected = application_shifts(application)
        if all(item.pk != shift.pk for item in selected):
            dc.set_application_shifts(application, selected + [shift])
    process_shift_decision(application, shift, 'approved', operator)
    lead_minutes = dc.get_const('qr_enroll_checkin_lead_minutes', default=60)
    if shift.start_time <= timezone.now() + timedelta(minutes=lead_minutes):
        mark_scan(operator, token, shift.pk, 'in')
        return 'Записан на смену. Вход отмечен.'
    return 'Записан на смену. Явка пока не отмечена.'


@transaction.atomic
def mark_scan(operator, token, shift_id, action):
    """Повторная отправка не меняет вход/выход и не начисляет часы дважды."""
    user = _scanned_user(operator, token)
    shift = dc.event_shifts_qs().filter(pk=shift_id, participations__user=user).select_related('event__event_group').first()
    if not shift:
        raise ValidationError('Смена не найдена среди доступных для отметки.')
    if not can_mark_shift(operator, shift):
        raise PermissionDenied('Нет права отмечать эту смену.')
    participation = dc.participations_qs().select_for_update().filter(user=user, event_day=shift).first()
    if not participation:
        raise ValidationError('Участие не найдено.')
    record = dc.shift_attendance_qs().filter(user=user, shift=shift).first()
    if record and (action == 'in' or action == 'out' and record.exited_at):
        return record
    if shift.event.event_status == 'finished':
        raise ValidationError('Позиция завершена.')
    if not _available_shifts(user).filter(pk=shift.pk).exists():
        raise ValidationError('Явка уже отмечена или смена недоступна для регистрации.')
    old_status = participation.status
    if action == 'in':
        if record:
            return record
        record, created = dc.create_shift_entry(user, shift, operator)
        if not created:
            return record
        dc.save_qr_participation(participation, 0, operator=operator)
    elif action == 'out':
        if not record:
            raise ValidationError('Сначала отметьте вход.')
        if record.exited_at:
            return record
        if timezone.now() < record.entered_at:
            raise ValidationError('Время выхода раньше входа.')
        dc.save_shift_exit(record, operator)
        hours = (Decimal(str((record.exited_at - record.entered_at).total_seconds())) / Decimal(3600)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        dc.save_qr_participation(participation, hours, full_shift=record.entered_at <= shift.start_time and record.exited_at >= shift.end_time, operator=operator)
    else:
        raise ValidationError('Неизвестное действие.')
    recalc_user_aggregates(user)
    if action == 'in' and old_status != 'attended':
        from blog.services.stats import apply_churn_activity_decay
        apply_churn_activity_decay(user, event=shift.event)
    return record


@transaction.atomic
def grant_scanner(operator, user, group):
    """Выдать право сканирования мероприятия без изменения бизнес-роли."""
    if not has_manager_access(operator):
        raise PermissionDenied('Выдавать доступ может менеджер.')
    return dc.create_scanner_grant(user, group, operator)


@transaction.atomic
def revoke_scanner(operator, grant_id):
    """Отозвать назначение, сохранив историческую запись."""
    if not has_manager_access(operator):
        raise PermissionDenied('Отзывать доступ может менеджер.')
    grant = dc.scanner_grants_qs().filter(pk=grant_id, revoked_at=None).first()
    if not grant:
        raise ValidationError('Назначение не найдено.')
    dc.revoke_scanner_grant(grant, operator)
