"""Приглашение выдаёт роль до истечения ссылки; полученная роль бессрочна."""
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from . import factories as f


class RoleInvitationTests(TestCase):
    def setUp(self):
        self.manager, self.volunteer = f.make_manager(), f.make_user()

    def test_manager_creates_default_twelve_hour_link(self):
        from blog.services.role_invitations import create_invitation
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            invitation, token = create_invitation(self.manager, 'team_lead')
        self.assertEqual(invitation.expires_at, now + timedelta(hours=12))
        self.assertNotEqual(invitation.token_hash, token)
        with self.assertRaises(PermissionDenied):
            create_invitation(self.volunteer, 'manager')

    def test_link_is_reusable_role_permanent_and_duplicate_visit_safe(self):
        from blog.services.role_invitations import create_invitation, claim_invitation
        from blog.services.roles import is_manager, is_team_leader
        from blog.models import TeamLeader, RoleInvitationUse
        invitation, token = create_invitation(self.manager, 'manager', hours=2)
        claim_invitation(self.volunteer, token)
        claim_invitation(self.volunteer, token)
        another = f.make_user()
        claim_invitation(another, token)
        self.assertTrue(is_manager(self.volunteer))
        self.assertTrue(is_team_leader(self.volunteer))
        self.assertEqual(TeamLeader.objects.filter(user=self.volunteer, revoked_at=None).count(), 1)
        self.assertEqual(RoleInvitationUse.objects.filter(invitation=invitation).count(), 2)
        with patch('django.utils.timezone.now', return_value=invitation.expires_at + timedelta(days=1)):
            self.assertTrue(is_manager(self.volunteer))

    def test_expired_link_shows_exact_message_even_without_login(self):
        from blog.services.role_invitations import create_invitation
        invitation, token = create_invitation(self.manager, 'team_lead', hours=1)
        with patch('django.utils.timezone.now', return_value=invitation.expires_at):
            response = self.client.get(reverse('role_invitation_accept', args=[token]))
        self.assertContains(response, 'срок данной ссылки истек')

    def test_active_anonymous_invite_returns_after_login(self):
        from blog.services.role_invitations import create_invitation
        from blog.services.roles import is_team_leader
        invitation, token = create_invitation(self.manager, 'team_lead')
        url = reverse('role_invitation_accept', args=[token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('next=', response.url)
        self.client.force_login(self.volunteer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(is_team_leader(self.volunteer))

    def test_creation_ui_and_invalid_role(self):
        self.client.force_login(self.volunteer)
        self.assertEqual(self.client.get(reverse('role_invitation_create')).status_code, 403)
        self.client.force_login(self.manager)
        response = self.client.post(reverse('role_invitation_create'), {'role': 'manager', 'hours': 3}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, 'readonly')
        self.assertContains(response, '/join/')
        response = self.client.post(reverse('role_invitation_create'), {'role': 'admin', 'hours': 3})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'errorlist')

    def test_certificate_controls_hidden_in_profile_and_settings(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('profile_detail', args=[self.volunteer.pk]))
        self.assertNotContains(response, reverse('pgas_verify_user', args=[self.volunteer.pk]))
        response = self.client.get(reverse('settings'))
        self.assertNotContains(response, 'data-tab="pgas_template"')
        self.client.force_login(self.volunteer)
        response = self.client.get(reverse('profile_detail', args=[self.volunteer.pk]))
        self.assertNotContains(response, reverse('pgas_certificate_issue', args=[self.volunteer.pk]))
