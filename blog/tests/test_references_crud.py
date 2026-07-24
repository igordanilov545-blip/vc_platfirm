"""CRUD справочников: локации, организации, организаторы, требования, категории,
плюшки — и их quick-create JSON-эндпоинты.

Единый паттерн для всех справочников (agent-workflow.md §4): создание/редактирование
через modal_form_response (AJAX POST -> JSON redirect), список — AJAX partial /
редирект на хаб настроек, удаление — POST-редирект. Тесты держат под контролем сам
факт, что запись реально появляется/меняется/пропадает в БД (не только код ответа),
и что действие доступно только менеджеру.
"""
from django.test import TestCase
from django.urls import reverse

from blog.models import (
    Location, Organization, Organizer, EventCategory, EventPerk,
    EventRequirement, UserRequirementException,
)
from . import factories as f


def _ajax(client, method, url, data=None):
    kw = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
    if method == 'post':
        return client.post(url, data or {}, **kw)
    return client.get(url, **kw)


class LocationCrudTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_create_location(self):
        r = _ajax(self.client, 'post', reverse('location_create'), {'name': 'Новая локация', 'map_link': ''})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Location.objects.filter(name='Новая локация').exists())

    def test_edit_location(self):
        loc = f.make_location('Старое имя')
        r = _ajax(self.client, 'post', reverse('location_edit', args=[loc.id]), {'name': 'Новое имя', 'map_link': ''})
        self.assertEqual(r.status_code, 200)
        loc.refresh_from_db()
        self.assertEqual(loc.name, 'Новое имя')

    def test_list_redirects_direct_ajax_returns_partial(self):
        direct = self.client.get(reverse('location_list'))
        self.assertEqual(direct.status_code, 302)
        partial = _ajax(self.client, 'get', reverse('location_list'))
        self.assertEqual(partial.status_code, 200)

    def test_volunteer_cannot_create_location(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = _ajax(self.client, 'post', reverse('location_create'), {'name': 'x'})
        self.assertEqual(r.status_code, 403)


class OrganizationCrudTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_create_organization(self):
        r = _ajax(self.client, 'post', reverse('organization_create'), {
            'name': 'Новая организация', 'description': '', 'comment': '',
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Organization.objects.filter(name='Новая организация').exists())

    def test_edit_organization(self):
        org = f.make_organization('Старая')
        r = _ajax(self.client, 'post', reverse('organization_edit', args=[org.id]), {
            'name': 'Новая', 'description': '', 'comment': '',
        })
        self.assertEqual(r.status_code, 200)
        org.refresh_from_db()
        self.assertEqual(org.name, 'Новая')

    def test_detail_page(self):
        org = f.make_organization('Детали орг')
        r = self.client.get(reverse('organization_detail', args=[org.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Детали орг')

    def test_organizers_linked_on_save(self):
        org = f.make_organization()
        organizer = f.make_organizer()
        r = self.client.post(reverse('organization_edit', args=[org.id]), {
            'name': org.name, 'description': '', 'comment': '', 'organizers': [organizer.id],
        })
        self.assertIn(r.status_code, (200, 302))
        from data_base import data_controller as dc
        self.assertIn(organizer, dc.organizers_for_organization(org))


class OrganizerCrudTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_create_organizer(self):
        r = _ajax(self.client, 'post', reverse('organizer_create'), {
            'first_name': 'Иван', 'last_name': 'Иванов', 'phone': '', 'email': '',
            'telegram_username': '', 'VK_username': '', 'whatsapp': '', 'comments': '',
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Organizer.objects.filter(first_name='Иван', last_name='Иванов').exists())

    def test_detail_page(self):
        organizer = f.make_organizer(first_name='Пётр')
        r = self.client.get(reverse('organizer_detail', args=[organizer.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Пётр')


class CategoryCrudTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_create_edit_delete(self):
        r = _ajax(self.client, 'post', reverse('category_create'), {'name': 'Новая категория'})
        self.assertEqual(r.status_code, 200)
        cat = EventCategory.objects.get(name='Новая категория')

        r = _ajax(self.client, 'post', reverse('category_edit', args=[cat.id]), {'name': 'Переименовано'})
        self.assertEqual(r.status_code, 200)
        cat.refresh_from_db()
        self.assertEqual(cat.name, 'Переименовано')

        r = self.client.post(reverse('category_delete', args=[cat.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(EventCategory.objects.filter(id=cat.id).exists())


class PerkCrudTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_create_edit_delete(self):
        r = _ajax(self.client, 'post', reverse('perk_create'), {'name': 'Новая плюшка'})
        self.assertEqual(r.status_code, 200)
        perk = EventPerk.objects.get(name='Новая плюшка')

        r = _ajax(self.client, 'post', reverse('perk_edit', args=[perk.id]), {'name': 'Другая плюшка'})
        self.assertEqual(r.status_code, 200)
        perk.refresh_from_db()
        self.assertEqual(perk.name, 'Другая плюшка')

        r = self.client.post(reverse('perk_delete', args=[perk.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(EventPerk.objects.filter(id=perk.id).exists())


class RequirementCrudTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_create_edit_delete(self):
        r = _ajax(self.client, 'post', reverse('requirement_create'), {'title': 'Опыт вождения', 'description': ''})
        self.assertEqual(r.status_code, 200)
        req = EventRequirement.objects.get(title='Опыт вождения')

        r = _ajax(self.client, 'post', reverse('requirement_edit', args=[req.id]), {
            'title': '18+ обновлено', 'description': 'd', 'check_type': 'manual',
        })
        self.assertEqual(r.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.title, '18+ обновлено')

        r = self.client.post(reverse('requirement_delete', args=[req.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(EventRequirement.objects.filter(id=req.id).exists())

    def test_exception_add_and_remove(self):
        req = f.make_requirement()
        volunteer = f.make_user()
        r = self.client.post(reverse('requirement_exception_add', args=[req.id]), {
            'user': volunteer.id, 'reason': 'причина',
        })
        self.assertEqual(r.status_code, 302)
        exc = UserRequirementException.objects.get(user=volunteer, requirement=req)

        r = self.client.post(reverse('requirement_exception_remove', args=[exc.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(UserRequirementException.objects.filter(id=exc.id).exists())

    def test_exception_add_unknown_user_shows_error_not_crash(self):
        req = f.make_requirement()
        r = self.client.post(reverse('requirement_exception_add', args=[req.id]), {
            'user': 999999, 'reason': '',
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(UserRequirementException.objects.filter(requirement=req).exists())


class QuickCreateTests(TestCase):
    """quick-create/* — JSON-эндпоинты для inline-создания справочников из формы меро."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_quick_create_location(self):
        r = self.client.post(reverse('quick_create_location'), {'name': 'Быстрая локация', 'map_link': ''})
        self.assertEqual(r.status_code, 200)
        self.assertIn('id', r.json())
        self.assertTrue(Location.objects.filter(name='Быстрая локация').exists())

    def test_quick_create_organization(self):
        r = self.client.post(reverse('quick_create_organization'), {'name': 'Быстрая орг', 'description': ''})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Organization.objects.filter(name='Быстрая орг').exists())

    def test_quick_create_organizer(self):
        r = self.client.post(reverse('quick_create_organizer'), {
            'first_name': 'Аня', 'last_name': 'Быстрова', 'phone': '', 'telegram_username': '',
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Organizer.objects.filter(first_name='Аня').exists())

    def test_quick_create_category(self):
        r = self.client.post(reverse('quick_create_category'), {'name': 'Быстрая категория'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EventCategory.objects.filter(name='Быстрая категория').exists())

    def test_quick_create_perk(self):
        r = self.client.post(reverse('quick_create_perk'), {'name': 'Быстрая плюшка'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EventPerk.objects.filter(name='Быстрая плюшка').exists())

    def test_quick_create_requirement(self):
        r = self.client.post(reverse('quick_create_requirement'), {'title': 'Быстрое требование', 'description': ''})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EventRequirement.objects.filter(title='Быстрое требование').exists())

    def test_quick_create_volunteer(self):
        from blog.models import User
        r = self.client.post(reverse('quick_create_volunteer'), {
            'first_name': 'Толя', 'last_name': 'Новый', 'phone': '+79990001122', 'telegram_username': '',
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.filter(first_name='Толя', last_name='Новый').exists())

    def test_quick_create_volunteer_requires_contact(self):
        r = self.client.post(reverse('quick_create_volunteer'), {
            'first_name': 'Без', 'last_name': 'Контактов', 'phone': '', 'telegram_username': '',
        })
        self.assertEqual(r.status_code, 400)

    def test_quick_create_invalid_returns_400(self):
        r = self.client.post(reverse('quick_create_location'), {'name': ''})
        self.assertEqual(r.status_code, 400)
        self.assertIn('errors', r.json())

    def test_quick_create_get_not_allowed(self):
        r = self.client.get(reverse('quick_create_location'))
        self.assertEqual(r.status_code, 405)

    def test_quick_create_forbidden_for_volunteer(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.post(reverse('quick_create_location'), {'name': 'x'})
        self.assertEqual(r.status_code, 403)
