"""Записи приглашений и аудит использования; bearer-токены не логируются."""
from django.utils import timezone
from blog.models import RoleInvitation, RoleInvitationUse
from ._base import logger, actor


def role_invitations_qs():
    return RoleInvitation.objects.all()


def create_role_invitation(*, token_hash, role, created_by, created_at, expires_at):
    invitation = RoleInvitation.objects.create(token_hash=token_hash, role=role, created_by=created_by, created_at=created_at, expires_at=expires_at)
    logger.info('INSERT role_invitations: id=%s role=%s by=%s expires=%s', invitation.pk, role, actor(created_by), expires_at)
    return invitation


def record_role_invitation_use(invitation, user):
    use, created = RoleInvitationUse.objects.get_or_create(invitation=invitation, user=user)
    if created:
        logger.info('INSERT role_invitation_uses: invitation=%s user=%s', invitation.pk, user.pk)
    return use


def revoke_role_invitation(invitation, operator):
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=['revoked_at'])
    logger.info('REVOKE role_invitations: id=%s by=%s', invitation.pk, actor(operator))
