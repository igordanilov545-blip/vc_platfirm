"""Вид мероприятия у волонтёра: расшифровка требований (название + описание) и ссылка
на пост в Telegram-канале. Волонтёр открывает карточку меро и должен видеть, что от него
требуется и где анонс, а не только чипы-названия.
"""
from django.test import TestCase
from django.urls import reverse

from blog.models import EventRequirement, EventRequirementMap
from . import factories as f


class EventDetailVolunteerViewTests(TestCase):
    def setUp(self):
        self.user = f.make_user()
        self.client.force_login(self.user)
        self.event = f.make_event(title='Меро для волонтёра')
        f.make_shift(self.event)

    def _attach_requirement(self, title, description):
        req = EventRequirement.objects.create(title=title, description=description)
        EventRequirementMap.objects.create(event=self.event, requirement=req)
        return req

    def test_requirement_description_shown(self):
        self._attach_requirement('Возраст 18+', 'Нужно быть совершеннолетним')
        r = self.client.get(reverse('event_detail', args=[self.event.id]))
        self.assertContains(r, 'Возраст 18+')
        self.assertContains(r, 'Нужно быть совершеннолетним')

    def test_requirement_without_description_not_in_list(self):
        """У требования без описания расшифровки нет — только чип-название (title
        встречается в чипе, но описания в тексте нет)."""
        self._attach_requirement('Просто требование', '')
        r = self.client.get(reverse('event_detail', args=[self.event.id]))
        self.assertContains(r, 'Просто требование')  # чип есть
        # Строки расшифровки «title — description» быть не должно (описание пустое).
        self.assertNotContains(r, 'Просто требование —')

    def test_channel_post_link_shown_when_set(self):
        self.event.post_in_chanel_link = 'https://t.me/channel/42'
        self.event.save(update_fields=['post_in_chanel_link'])
        r = self.client.get(reverse('event_detail', args=[self.event.id]))
        self.assertContains(r, 'https://t.me/channel/42')
        self.assertContains(r, 'Пост в канале')

    def test_channel_post_link_absent_by_default(self):
        r = self.client.get(reverse('event_detail', args=[self.event.id]))
        self.assertNotContains(r, 'Пост в канале')
