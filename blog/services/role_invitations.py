"""Многоразовые приглашения: истекает ссылка, выданные роли остаются."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import secrets
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from data_base import data_controller as dc
from .roles import has_manager_access, assign_role

EXPIRED_MESSAGE = 'срок данной ссылки истек'


def _manager(user):
    if not has_manager_access(user):
        raise PermissionDenied('Приглашения создаёт менеджер.')


def default_hours():
    return dc.get_const('role_invitation_default_hours', default=12)


def create_invitation(operator, role, hours=None):
    _manager(operator)
    if role not in ('team_lead', 'manager'):
        raise ValidationError('Выберите роль тим-лидера или менеджера.')
    try:
        duration = Decimal(str(default_hours() if hours is None else hours))
        if not duration.is_finite() or duration <= 0:
            raise ValueError
        now = timezone.now()
        expires_at = now + timedelta(hours=float(duration))
    except (ValueError, OverflowError, InvalidOperation):
        raise ValidationError('Срок действия должен быть положительным числом часов.')
    token = secrets.token_urlsafe(32)
    invitation = dc.create_role_invitation(token_hash=hashlib.sha256(token.encode()).hexdigest(), role=role, created_by=operator, created_at=now, expires_at=expires_at)
    return invitation, token


def get_invitation(token, *, lock=False):
    if not token or len(token) > 128:
        raise ValidationError('Ссылка недействительна.')
    queryset = dc.role_invitations_qs().select_related('created_by')
    if lock:
        queryset = queryset.select_for_update(of=('self',))
    invitation = queryset.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if invitation is None:
        raise ValidationError('Ссылка недействительна.')
    if invitation.expires_at <= timezone.now():
        raise ValidationError(EXPIRED_MESSAGE)
    if invitation.revoked_at or not has_manager_access(invitation.created_by):
        raise ValidationError('Ссылка недействительна.')
    return invitation


@transaction.atomic
def claim_invitation(user, token):
    if not user or not user.is_authenticated or user.status == 'blacklisted':
        raise PermissionDenied('Войдите в доступный аккаунт.')
    invitation = get_invitation(token, lock=True)
    assign_role(invitation.role, [user], assigned_by=invitation.created_by)
    dc.record_role_invitation_use(invitation, user)
    return invitation


def invitation_rows(operator):
    from django.db.models import Count
    _manager(operator)
    rows = list(dc.role_invitations_qs().select_related('created_by').annotate(use_count=Count('uses')))
    now = timezone.now()
    for row in rows:
        row.active = row.revoked_at is None and row.expires_at > now
    return rows


def invitation_detail(operator, invitation_id):
    _manager(operator)
    invitation = dc.role_invitations_qs().select_related('created_by').filter(pk=invitation_id).first()
    if not invitation:
        raise Http404('Приглашение не найдено.')
    uses = list(dc.role_invitation_uses_qs().filter(invitation=invitation).select_related('user').order_by('-used_at', '-pk'))
    return {'invitation': invitation, 'uses': uses}


def revoke_invitation(operator, invitation_id):
    _manager(operator)
    invitation = dc.role_invitations_qs().filter(pk=invitation_id).first()
    if not invitation:
        raise ValidationError('Приглашение не найдено.')
    dc.revoke_role_invitation(invitation, operator)
