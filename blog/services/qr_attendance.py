"""Персональный QR и ACL фактического входа/выхода; db.md, раздел QR."""
from io import BytesIO
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

import qrcode
from qrcode.util import QRData, MODE_8BIT_BYTE
from django.core.exceptions import PermissionDenied, ValidationError
from django.core import signing
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
    """Ближайшие смены, прошедшие идущего мероприятия и история QR для исправлений."""
    now = timezone.now()
    attended = dc.shift_attendance_qs().filter(user=user).values('shift_id')
    ongoing_groups = dc.event_groups_qs().annotate(
        begins=Min('positions__shifts__start_time'), ends=Max('positions__shifts__end_time'),
    ).filter(begins__lte=now, ends__gte=now).values('pk')
    ongoing_positions = dc.events_qs().annotate(begins=Min('shifts__start_time'), ends=Max('shifts__end_time')).filter(begins__lte=now, ends__gte=now).values('pk')
    return dc.event_shifts_qs().filter(
        Q(participations__user=user, participations__status='pending') | Q(pk__in=attended),
    ).filter(
        Q(end_time__gte=now) | Q(event__event_group_id__in=ongoing_groups) | Q(event_id__in=ongoing_positions)
        | Q(pk__in=attended),
    ).select_related('event__event_group').distinct()


def _scan_ticket(operator, user, ticket=None):
    if ticket:
        try:
            payload = signing.loads(ticket, salt='qr-scan-window', max_age=60 * dc.get_const('qr_scan_window_minutes', default=720))
            if payload['operator'] != operator.pk or payload['user'] != user.pk:
                raise PermissionDenied('Окно сканирования принадлежит другому пользователю.')
            return ticket, datetime.fromisoformat(payload['at'])
        except (signing.BadSignature, ValueError, TypeError, KeyError):
            raise ValidationError('Окно сканирования устарело или повреждено. Отсканируйте QR заново.')
    at = timezone.now()
    return signing.dumps({'operator': operator.pk, 'user': user.pk, 'at': at.isoformat()}, salt='qr-scan-window'), at


def scan_context(operator, token, *, scan_ticket=None):
    """Мини-карточка без контактов: ФИО, незаконченные отметки и порядок смен."""
    user = _scanned_user(operator, token)
    ticket, scanned_at = _scan_ticket(operator, user, scan_ticket)
    records = {row.shift_id: row for row in dc.shift_attendance_qs().filter(user=user).select_related('shift__event__event_group')}
    meals = {row.shift_id: row for row in dc.shift_meals_qs().filter(user=user)}
    badges = {row.event_group_id: row for row in dc.event_badges_qs().filter(user=user)}
    now = timezone.now()
    shifts = sorted(_available_shifts(user), key=lambda shift: (shift.end_time < now, shift.start_time, shift.pk))
    rows = []
    groups = {}
    for shift in shifts:
        record = records.get(shift.pk)
        rows.append({'shift': shift, 'attendance': record,
                     'meal': meals.get(shift.pk),
                     'action': 'out' if record and record.entered_at else 'in',
                     'can_mark': shift.event.event_status != 'finished' and can_mark_shift(operator, shift)})
        if shift.event.event_group_id:
            group_id = shift.event.event_group_id
            candidate = {'group': shift.event.event_group, 'shift': shift, 'badge': badges.get(group_id), 'can_mark': rows[-1]['can_mark']}
            if group_id not in groups or candidate['can_mark']:
                groups[group_id] = candidate
    return {'scanned_user': user, 'shift_rows': rows, 'nearest_shift': rows[0]['shift'] if rows else None,
            'badge_rows': list(groups.values()), 'scan_ticket': ticket, 'scanned_at': scanned_at,
            'last_attendance': max((row for row in records.values() if row.entered_at), key=lambda row: (row.exited_at or row.entered_at, row.pk), default=None),
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
def enroll_scanned_user(operator, token, shift_id, *, defer_entry=False):
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
        if defer_entry:
            return 'Записан на смену. Вход выбран и сохранится при закрытии окна.'
        mark_scan(operator, token, shift.pk, 'in')
        return 'Записан на смену. Вход отмечен.'
    return 'Записан на смену. Явка пока не отмечена.'


def _set_attendance(operator, user, shift, choices, at):
    """Применить итоговые состояния пары вход/выход и пересчитать фактические часы."""
    participation = dc.participations_qs().select_for_update().get(user=user, event_day=shift)
    record = dc.shift_attendance_qs().filter(user=user, shift=shift).first()
    entered = record.entered_at if record else None
    exited = record.exited_at if record else None
    wanted_in = choices.get('in', bool(entered))
    wanted_out = choices.get('out', bool(exited))
    if not wanted_in:
        if choices.get('out'):
            raise ValidationError('Сначала отметьте вход.')
        wanted_out = False
    entered = (entered or at) if wanted_in else None
    exited = (exited or at) if wanted_out else None
    if exited and exited < entered:
        raise ValidationError('Время выхода раньше входа.')
    if record and (record.entered_at, record.exited_at) == (entered, exited):
        return record
    if not record and not entered:
        return None
    if not _available_shifts(user).filter(pk=shift.pk).exists():
        raise ValidationError('Смена недоступна для регистрации.')
    created = False
    old_status = participation.status
    if not record:
        record, created = dc.create_shift_entry(user, shift, operator, at=entered)
    dc.save_shift_attendance(record, entered, exited, operator)
    hours = (Decimal(str((exited - entered).total_seconds())) / Decimal(3600)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) if exited else Decimal(0)
    dc.save_qr_participation(participation, hours,
                             full_shift=bool(exited and entered <= shift.start_time and exited >= shift.end_time),
                             operator=operator, status='attended' if entered else 'pending')
    recalc_user_aggregates(user)
    if created and old_status != 'attended':
        from blog.services.stats import apply_churn_activity_decay
        apply_churn_activity_decay(user, event=shift.event)
    return record


@transaction.atomic
def mark_scan(operator, token, shift_id, action, *, at=None):
    """Совместимый одиночный вход/выход без изменения уже сохранённого времени."""
    user = _scanned_user(operator, token)
    dc.users_qs().select_for_update().get(pk=user.pk)
    shift = dc.event_shifts_qs().filter(pk=shift_id, participations__user=user).select_related('event__event_group').first()
    if not shift:
        raise ValidationError('Смена не найдена среди доступных для отметки.')
    if not can_mark_shift(operator, shift):
        raise PermissionDenied('Нет права отмечать эту смену.')
    if shift.event.event_status == 'finished':
        raise ValidationError('Позиция завершена.')
    if action not in ('in', 'out'):
        raise ValidationError('Неизвестное действие.')
    return _set_attendance(operator, user, shift, {action: True}, at or timezone.now())


@transaction.atomic
def commit_scan(operator, token, scan_ticket, changes):
    """Закрытие окна: атомарно установить либо снять выбранные отметки."""
    user = _scanned_user(operator, token)
    if not scan_ticket:
        raise ValidationError('Повторно отсканируйте QR-код.')
    _, at = _scan_ticket(operator, user, scan_ticket)
    if not isinstance(changes, list) or len(changes) > dc.get_const('qr_scan_max_changes', default=100):
        raise ValidationError('Некорректный список отметок.')
    dc.users_qs().select_for_update().get(pk=user.pk)
    shifts = {}
    attendance = {}
    for item in changes:
        if not isinstance(item, dict) or item.get('kind') not in ('in', 'out', 'lunch', 'badge'):
            raise ValidationError('Неизвестная отметка.')
        checked = item.get('checked', True)
        if not isinstance(checked, bool):
            raise ValidationError('Некорректное состояние отметки.')
        try:
            shift_id = int(item['shift_id'])
        except (ValueError, TypeError, KeyError):
            raise ValidationError('Некорректная смена.')
        if shift_id not in shifts:
            shifts[shift_id] = dc.event_shifts_qs().filter(pk=shift_id, participations__user=user).select_related('event__event_group').first()
        shift = shifts[shift_id]
        if not shift:
            raise ValidationError('Смена не найдена среди участий человека.')
        if not can_mark_shift(operator, shift):
            raise PermissionDenied('Нет права отмечать эту смену.')
        if shift.event.event_status == 'finished':
            raise ValidationError('Позиция завершена.')
        kind = item['kind']
        if kind in ('in', 'out'):
            attendance.setdefault(shift_id, {})[kind] = checked
        elif kind == 'lunch':
            if checked:
                dc.issue_shift_meal(user, shift, operator, at)
            else:
                dc.revoke_shift_meal(user, shift, operator)
        elif shift.event.event_group_id:
            if checked:
                dc.issue_event_badge(user, shift.event.event_group, operator, at)
            else:
                dc.revoke_event_badge(user, shift.event.event_group, operator)
        else:
            raise ValidationError('У позиции не указано мероприятие для выдачи значка.')
    for shift_id, choices in attendance.items():
        _set_attendance(operator, user, shifts[shift_id], choices, at)


def mark_scan_context(operator, token, shift_id, action, checked=True, *, scan_ticket=None):
    """Совместимость старого URL отметки с обедом, значком и снятием галочек."""
    user = _scanned_user(operator, token)
    ticket, _ = _scan_ticket(operator, user, scan_ticket)
    commit_scan(operator, token, ticket, [{'kind': action, 'shift_id': shift_id, 'checked': checked}])
    return scan_context(operator, token, scan_ticket=ticket)


@transaction.atomic
def enroll_scan_context(operator, token, shift_id, *, scan_ticket=None):
    user = _scanned_user(operator, token)
    ticket, _ = _scan_ticket(operator, user, scan_ticket)
    notice = enroll_scanned_user(operator, token, shift_id, defer_entry=True)
    context = scan_context(operator, token, scan_ticket=ticket)
    shift = dc.event_shifts_qs().get(pk=shift_id)
    if shift.start_time <= timezone.now() + timedelta(minutes=context['checkin_lead_minutes']):
        context['suggested_entry_shift'] = shift.pk
    context['scan_notice'] = notice
    return context


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
