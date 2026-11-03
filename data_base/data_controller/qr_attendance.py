"""Тонкий CRUD личных QR, прав сканирования и фактических отметок."""
from django.utils import timezone
from blog.models import UserQRCode, ScannerGrant, ShiftAttendance, ShiftMeal, EventBadge
from ._base import logger, actor


def user_qr(user):
    """Лениво получить постоянный токен, не записывая его значение в лог."""
    row, created = UserQRCode.objects.get_or_create(user=user)
    if created:
        logger.info('INSERT user_qr_codes: user=%s', user.pk)
    return row


def user_from_qr(token):
    """Найти владельца токена; QR сам по себе не предоставляет права входа."""
    row = UserQRCode.objects.select_related('user').filter(token=token).first()
    return row.user if row else None


def scanner_grants_qs():
    """Ленивый queryset для ACL и управления доступом."""
    return ScannerGrant.objects.all()


def create_scanner_grant(user, event_group, assigned_by):
    row, created = ScannerGrant.objects.get_or_create(user=user, event_group=event_group, revoked_at=None, defaults={'assigned_by': assigned_by})
    if created:
        logger.info('INSERT qr_scanner_grants: grant=%s user=%s group=%s by=%s', row.pk, user.pk, event_group.pk, actor(assigned_by))
    return row


def revoke_scanner_grant(grant, assigned_by):
    grant.revoked_at = timezone.now()
    grant.save(update_fields=['revoked_at'])
    logger.info('REVOKE qr_scanner_grants: grant=%s by=%s', grant.pk, actor(assigned_by))


def shift_attendance_qs():
    """Ленивый queryset фактических входов/выходов."""
    return ShiftAttendance.objects.all()


def create_shift_entry(user, shift, operator, at=None):
    row, created = ShiftAttendance.objects.get_or_create(user=user, shift=shift, defaults={'entered_by': operator, 'entered_at': at or timezone.now()})
    if created:
        logger.info('INSERT shift_attendance: attendance=%s user=%s shift=%s by=%s', row.pk, user.pk, shift.pk, actor(operator))
    return row, created


def save_shift_exit(row, operator, at=None):
    row.exited_at = at or timezone.now()
    row.exited_by = operator
    row.save(update_fields=['exited_at', 'exited_by'])
    logger.info('EXIT shift_attendance: attendance=%s by=%s', row.pk, actor(operator))
    return row


def save_qr_participation(participation, hours, full_shift=False, operator=None):
    """Явная отметка присутствия, отдельно от одобрения заявки."""
    participation.status = 'attended'
    participation.hours = hours
    participation.full_shift = full_shift
    participation.hours_overridden = False
    participation.save(update_fields=['status', 'hours', 'full_shift', 'hours_overridden'])
    logger.info('UPDATE participations via QR: participation=%s hours=%s by=%s', participation.pk, hours, actor(operator))
    return participation


def shift_meals_qs():
    return ShiftMeal.objects.all()


def event_badges_qs():
    return EventBadge.objects.all()


def issue_shift_meal(user, shift, operator, at):
    record, created = ShiftMeal.objects.get_or_create(user=user, shift=shift, defaults={'issued_by': operator, 'issued_at': at})
    if created:
        logger.info('INSERT shift_meals: user=%s shift=%s by=%s', user.pk, shift.pk, actor(operator))
    return record


def issue_event_badge(user, group, operator, at):
    record, created = EventBadge.objects.get_or_create(user=user, event_group=group, defaults={'issued_by': operator, 'issued_at': at})
    if created:
        logger.info('INSERT event_badges: user=%s group=%s by=%s', user.pk, group.pk, actor(operator))
    return record
