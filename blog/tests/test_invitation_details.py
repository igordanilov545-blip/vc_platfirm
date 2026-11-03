"""История ссылки приглашения: профили и время выдачи роли, только менеджеру."""
from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from blog.services import role_invitations as invitations
from . import factories as f


class InvitationDetailsTests(TestCase):
    def setUp(self):
        self.manager, self.user = f.make_manager(), f.make_user()
        self.invitation, self.token = invitations.create_invitation(self.manager, 'team_lead')
        invitations.claim_invitation(self.user, self.token)
        invitations.claim_invitation(self.user, self.token)
        self.url = reverse('role_invitation_detail', args=[self.invitation.pk])

    def test_manager_sees_unique_user_time_profile_and_modal_link(self):
        self.client.force_login(self.manager)
        response = self.client.get(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, reverse('profile_detail', args=[self.user.pk]))
        self.assertContains(response, self.user.full_name)
        self.assertContains(response, 'МСК')
        self.assertEqual(len(response.context['uses']), 1)
        self.assertNotContains(response, '<html')
        self.assertContains(self.client.get(reverse('role_invitation_list')), self.url)

    def test_expired_and_revoked_invitation_history_still_available(self):
        self.invitation.expires_at = timezone.now() - timedelta(days=1)
        self.invitation.revoked_at = timezone.now()
        self.invitation.save(update_fields=['expires_at', 'revoked_at'])
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(self.url), self.user.full_name)

    def test_access_and_missing_invitation(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('role_invitation_detail', args=[999999])).status_code, 404)
