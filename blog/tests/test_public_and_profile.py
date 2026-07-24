"""Публичные (без входа) страницы и профиль/опыт волонтёра — не были покрыты ни
одним тестом. Публичные страницы — единственный анонимный поверхностный слой
приложения (риск утечки чужих данных/обхода видимости), поэтому отдельно проверяем,
что показывается только опубликованное/по правильному токену.
"""
from django.test import TestCase
from django.urls import reverse

from blog.models import ExternalExperience
from . import factories as f


class PublicEventListTests(TestCase):
    def test_accessible_without_login(self):
        f.make_event(title='Открытое меро')
        r = self.client.get(reverse('public_event_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Открытое меро')

    def test_unpublished_event_not_listed(self):
        f.make_event(title='Черновик', published=False)
        r = self.client.get(reverse('public_event_list'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Черновик')


class PublicEventDetailTests(TestCase):
    def test_valid_token_shows_event(self):
        event = f.make_event(title='По ссылке')
        r = self.client.get(reverse('public_event_detail', args=[event.public_token]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'По ссылке')

    def test_unpublished_event_404(self):
        event = f.make_event(title='Не опубликовано', published=False)
        r = self.client.get(reverse('public_event_detail', args=[event.public_token]))
        self.assertEqual(r.status_code, 404)

    def test_unknown_token_404(self):
        import uuid
        r = self.client.get(reverse('public_event_detail', args=[uuid.uuid4()]))
        self.assertEqual(r.status_code, 404)


class PublicExperienceTests(TestCase):
    def test_valid_token_shows_experience(self):
        user = f.make_user()
        r = self.client.get(reverse('public_experience', args=[user.experience_token]))
        self.assertEqual(r.status_code, 200)

    def test_unknown_token_404(self):
        import uuid
        r = self.client.get(reverse('public_experience', args=[uuid.uuid4()]))
        self.assertEqual(r.status_code, 404)

    def test_no_pii_leak_comments_not_present(self):
        """Публичная страница опыта не должна показывать внутренние комментарии —
        только сам опыт (см. докстринг вьюхи «без ПДн/комментариев»)."""
        from blog.models import UserComment
        user = f.make_user()
        manager = f.make_manager()
        UserComment.objects.create(target_user=user, author=manager, text='СЕКРЕТНЫЙ_КОММЕНТАРИЙ')
        r = self.client.get(reverse('public_experience', args=[user.experience_token]))
        self.assertNotContains(r, 'СЕКРЕТНЫЙ_КОММЕНТАРИЙ')


class ProfileEditTests(TestCase):
    def setUp(self):
        self.user = f.make_user(first_name='Старое')
        self.client.force_login(self.user)

    def test_get_form(self):
        r = self.client.get(reverse('profile_edit'))
        self.assertEqual(r.status_code, 200)

    def test_post_updates_profile(self):
        r = self.client.post(reverse('profile_edit'), {
            'first_name': 'Новое', 'last_name': self.user.last_name or '',
            'middle_name': '', 'telegram_username': self.user.telegram_username,
            'phone': self.user.phone, 'email': '', 'birthday': '', 'about': '', 'vk_link': '',
            'system_username': self.user.system_username or '',
        })
        self.assertIn(r.status_code, (200, 302))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Новое')

    def test_complete_profile_is_same_view(self):
        r = self.client.get(reverse('complete_profile'))
        self.assertEqual(r.status_code, 200)


class ExternalExperienceCrudTests(TestCase):
    def setUp(self):
        self.user = f.make_user()
        self.client.force_login(self.user)

    def test_add_experience(self):
        r = self.client.post(reverse('external_experience_add'), {
            'title': 'Субботник', 'date': '2026-01-01', 'date_to': '', 'description': '',
        })
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(ExternalExperience.objects.filter(user=self.user, title='Субботник').exists())

    def test_edit_own_experience(self):
        exp = ExternalExperience.objects.create(user=self.user, title='Старое', date='2026-01-01')
        r = self.client.post(reverse('external_experience_edit', args=[exp.id]), {
            'title': 'Новое', 'date': '2026-01-01', 'date_to': '', 'description': '',
        })
        self.assertIn(r.status_code, (200, 302))
        exp.refresh_from_db()
        self.assertEqual(exp.title, 'Новое')

    def test_cannot_edit_others_experience(self):
        other = f.make_user()
        exp = ExternalExperience.objects.create(user=other, title='Чужое', date='2026-01-01')
        r = self.client.post(reverse('external_experience_edit', args=[exp.id]), {
            'title': 'Взлом', 'date': '2026-01-01', 'date_to': '', 'description': '',
        })
        self.assertEqual(r.status_code, 404)

    def test_delete_own_experience(self):
        exp = ExternalExperience.objects.create(user=self.user, title='Удалить', date='2026-01-01')
        r = self.client.post(reverse('external_experience_delete', args=[exp.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ExternalExperience.objects.filter(id=exp.id).exists())

    def test_cannot_delete_others_experience(self):
        other = f.make_user()
        exp = ExternalExperience.objects.create(user=other, title='Чужое', date='2026-01-01')
        r = self.client.post(reverse('external_experience_delete', args=[exp.id]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(ExternalExperience.objects.filter(id=exp.id).exists())
