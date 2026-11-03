"""В БД только имена соцсетей; ссылки собираются при показе и экспорте."""
from django.test import TestCase
from blog.forms import ProfileForm
from blog.services.social_profiles import social_username, social_url
from . import factories as f


class SocialProfilesTests(TestCase):
    def test_handles_from_links_and_at_signs(self):
        for value in ('@volunteer', 'https://vk.com/volunteer', 'Vk.com/volunteer/', 'www.vk.com/volunteer?from=test'):
            self.assertEqual(social_username(value, 'vk'), 'volunteer')
        for value in ('@volunteer', 'https://www.instagram.com/volunteer/', 'instagram.com/volunteer?igsh=abc'):
            self.assertEqual(social_username(value, 'instagram'), 'volunteer')
        self.assertEqual(social_username('@@volunteer', 'telegram'), 'volunteer')
        self.assertEqual(social_url('volunteer', 'instagram'), 'https://www.instagram.com/volunteer/')
        self.assertEqual(social_username('https://[bad', 'vk'), '')

    def test_profile_form_stores_handles_and_old_values_still_make_links(self):
        user = f.make_user(VK_username='https://vk.com/old', instagram_url='https://www.instagram.com/old/')
        data = {'first_name': 'Анна', 'phone': '+79000000000', 'telegram_username': '@anna',
                'VK_username': 'https://vk.com/anna', 'instagram_url': 'https://www.instagram.com/anna/',
                'preferred_contact_methods': ['telegram']}
        form = ProfileForm(data=data, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual((user.VK_username, user.instagram_url, user.telegram_username), ('anna', 'anna', 'anna'))
        self.assertEqual(user.instagram_profile_url, 'https://www.instagram.com/anna/')
