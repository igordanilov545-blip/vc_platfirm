"""Опыт волонтёра: роли в системных мероприятиях (тим-лидер/волонтёр) для экспорта
«Скопировать опыт» и вспомогательный JSON-тег. Роль на меро мы хотим выделять отдельно
(интересные роли — тим-лидер/координатор), см. build_experience и experience_copy_json.
"""
import json

from django.test import TestCase
from django.urls import reverse

from blog.services.experience import build_experience
from . import factories as f


class ExperienceRoleTests(TestCase):
    def _attended(self, user, event, **kw):
        shift = f.make_shift(event, days_from_now=-3, **kw)  # прошедшая смена
        f.make_participation(user, shift, status='attended')
        return shift

    def test_volunteer_role_by_default(self):
        user = f.make_user()
        event = f.make_event(title='Обычное меро')
        self._attended(user, event)
        items = build_experience(user)['items']
        sys_item = next(i for i in items if i['kind'] == 'system')
        self.assertEqual(sys_item['role'], 'volunteer')
        self.assertEqual(sys_item['role_label'], 'волонтёр')

    def test_team_lead_role_when_assigned(self):
        """Если у пользователя активное назначение team_lead на меро — роль в опыте
        по этому меро становится 'team_lead' (его подсвечиваем в экспорте)."""
        user = f.make_user()
        event = f.make_event(title='Меро с ТЛ')
        self._attended(user, event)
        f.assign_team_leader(event, user)
        items = build_experience(user)['items']
        sys_item = next(i for i in items if i['kind'] == 'system')
        self.assertEqual(sys_item['role'], 'team_lead')

    def test_role_is_per_event(self):
        """Роль привязана к конкретному меро: ТЛ на одном, волонтёр на другом."""
        user = f.make_user()
        led = f.make_event(title='Веду')
        joined = f.make_event(title='Участвую')
        self._attended(user, led)
        self._attended(user, joined)
        f.assign_team_leader(led, user)
        by_title = {i['title']: i for i in build_experience(user)['items'] if i['kind'] == 'system'}
        self.assertEqual(by_title['Веду']['role'], 'team_lead')
        self.assertEqual(by_title['Участвую']['role'], 'volunteer')

    def test_external_and_upcoming_have_no_role(self):
        """Внешний опыт и предстоящие заявки роль не несут (role=None) — роль про
        реальное участие в меро центра."""
        from blog.models import ExternalExperience
        user = f.make_user()
        ExternalExperience.objects.create(user=user, title='Внешнее')
        upcoming = f.make_event(title='Скоро')
        shift = f.make_shift(upcoming, days_from_now=5)
        f.make_application(upcoming, user=user, status='approved', shifts=[shift])
        for i in build_experience(user)['items']:
            if i['kind'] in ('external', 'upcoming'):
                self.assertIsNone(i['role'])


class ExperienceCopyJsonTagTests(TestCase):
    def test_json_lists_system_events_with_roles(self):
        from django.template import Context, Template
        user = f.make_user()
        led = f.make_event(title='Веду')
        shift = f.make_shift(led, days_from_now=-3)
        f.make_participation(user, shift, status='attended')
        f.assign_team_leader(led, user)

        experience = build_experience(user)
        tmpl = Template('{% load custom_tags %}{% experience_copy_json experience "http://x/exp" %}')
        rendered = tmpl.render(Context({'experience': experience}))
        payload = json.loads(rendered)
        self.assertEqual(payload['url'], 'http://x/exp')
        self.assertEqual(payload['total'], experience['total_count'])
        self.assertEqual(len(payload['events']), 1)
        self.assertEqual(payload['events'][0]['title'], 'Веду')
        self.assertEqual(payload['events'][0]['role'], 'team_lead')

    def test_json_escapes_script_close(self):
        """`<` в названии меро экранируется, чтобы не сломать <script type=json>."""
        from django.template import Context, Template
        user = f.make_user()
        evil = f.make_event(title='</script> hack')
        shift = f.make_shift(evil, days_from_now=-3)
        f.make_participation(user, shift, status='attended')
        experience = build_experience(user)
        tmpl = Template('{% load custom_tags %}{% experience_copy_json experience "http://x" %}')
        rendered = tmpl.render(Context({'experience': experience}))
        self.assertNotIn('</script>', rendered)
        self.assertIn('\\u003c', rendered)


class ExperienceBlockRenderTests(TestCase):
    def test_owner_sees_copy_picker_with_events(self):
        user = f.make_user()
        event = f.make_event(title='Меро для опыта')
        shift = f.make_shift(event, days_from_now=-3)
        f.make_participation(user, shift, status='attended')
        self.client.force_login(user)
        r = self.client.get(reverse('profile_detail', args=[user.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-experience-copy')
        self.assertContains(r, 'Скопировать опыт')
        # Ссылка открытия модалки выбора «топ» + меро попало в JSON-конфиг выбора.
        self.assertContains(r, 'data-experience-pick-open')
        self.assertContains(r, 'выбрать топ мероприятий')
        self.assertContains(r, '"title": "Меро для опыта"')

    def test_no_copy_block_without_system_experience(self):
        """Нет системного опыта — нет и блока копирования (нечего перечислять)."""
        user = f.make_user()
        self.client.force_login(user)
        r = self.client.get(reverse('profile_detail', args=[user.id]))
        self.assertNotContains(r, 'data-experience-copy')
