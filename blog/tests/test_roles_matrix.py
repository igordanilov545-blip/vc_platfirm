"""ACL-матрица тим-лидера (blog/services/roles.py) — testing-audit.md отмечал это
как самый крупный пробел: фабрика make_team_leader существовала, но ни один тест её
не использовал. Контекстные права ТЛ — «легко ошибиться, тихие последствия»
(coding-principles.md §4): действует только на СВОИХ мероприятиях и только пока меро
НЕ завершено; расширенный доступ к чужому профилю — только если целевой волонтёр
подал заявку/участвует именно в этом меро.
"""
from django.test import TestCase, override_settings
from django.urls import reverse

from blog.services.roles import (
    can_process_applications, has_extended_access_to_profile, has_manager_access,
    is_manager, is_team_leader_of_event, role_label, role_slug,
)
from . import factories as f


class TeamLeaderOwnVsForeignEventTests(TestCase):
    """is_team_leader_of_event / can_process_applications — ТЛ действует только на
    мероприятиях, где он назначен team_lead."""

    def setUp(self):
        self.tl = f.make_team_leader()
        self.own_event = f.make_event()
        f.assign_team_leader(self.own_event, self.tl)
        self.foreign_event = f.make_event()

    def test_is_team_leader_of_own_event(self):
        self.assertTrue(is_team_leader_of_event(self.tl, self.own_event.id))

    def test_is_not_team_leader_of_foreign_event(self):
        self.assertFalse(is_team_leader_of_event(self.tl, self.foreign_event.id))

    def test_can_process_applications_own_event(self):
        self.assertTrue(can_process_applications(self.tl, self.own_event.id))

    def test_cannot_process_applications_foreign_event(self):
        self.assertFalse(can_process_applications(self.tl, self.foreign_event.id))

    def test_plain_volunteer_cannot_process_anywhere(self):
        volunteer = f.make_user()
        self.assertFalse(can_process_applications(volunteer, self.own_event.id))


@override_settings(ANALYTICS_ADMIN_TG_IDS=['444'])
class TechAdminGetsManagerAccessTests(TestCase):
    """Тех.админ (ANALYTICS_ADMIN_TG_IDS) получает фактические права менеджера ВЕЗДЕ
    (has_manager_access), но его видимая роль (is_manager/role_label/role_slug) не
    меняется — он остаётся тем, кем был (волонтёр/ТЛ/менеджер). Права ≠ отображаемая
    роль — не путать has_manager_access с is_manager (roles.py, has_manager_access
    docstring)."""

    def test_plain_volunteer_tech_admin_gets_manager_access(self):
        volunteer = f.make_user(telegram_id='444')
        self.assertTrue(has_manager_access(volunteer))
        # но реальная роль/ярлык остаются волонтёрскими
        self.assertFalse(is_manager(volunteer))
        self.assertEqual(role_label(volunteer), 'Волонтёр')
        self.assertEqual(role_slug(volunteer), 'volunteer')

    def test_team_leader_tech_admin_gets_manager_access_keeps_tl_label(self):
        tl = f.make_team_leader(telegram_id='444')
        self.assertTrue(has_manager_access(tl))
        self.assertFalse(is_manager(tl))
        self.assertEqual(role_label(tl), 'Тим-лидер')
        self.assertEqual(role_slug(tl), 'team_leader')

    def test_can_process_applications_on_any_event_without_role(self):
        volunteer = f.make_user(telegram_id='444')
        event = f.make_event()
        self.assertTrue(can_process_applications(volunteer, event.id))

    def test_extended_profile_access_to_any_volunteer_without_role(self):
        volunteer = f.make_user(telegram_id='444')
        other = f.make_user()
        self.assertTrue(has_extended_access_to_profile(volunteer, other))

    def test_regular_user_without_tg_id_unaffected(self):
        volunteer = f.make_user()
        self.assertFalse(has_manager_access(volunteer))

    def test_manager_context_flag_true_for_tech_admin_on_dashboard(self):
        volunteer = f.make_user(telegram_id='444')
        self.client.force_login(volunteer)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['is_manager'])
        # роль в UI по-прежнему «Волонтёр», не «Менеджер»
        self.assertEqual(r.context['role_label'], 'Волонтёр')

    def test_manager_only_view_accessible_to_tech_admin_volunteer(self):
        volunteer = f.make_user(telegram_id='444')
        self.client.force_login(volunteer)
        r = self.client.get(reverse('user_list'))
        self.assertEqual(r.status_code, 200)


class TeamLeaderFinishedEventLosesRightsTests(TestCase):
    """access-control.md различает два разных правила для завершённого меро:
    - обработка заявок (правило §57): контекст "своё меро" — не зависит от finished,
      ТЛ может доработать резерв/довыдать решения по уже прошедшему мероприятию;
    - расширенный доступ к чужому профилю (правило 5, §81-86): явно ограничен
      "event_status != 'finished'" — после завершения меро доступ пропадает.
    Не путать одно с другим — это разные ACL-правила, не два проявления одного."""

    def setUp(self):
        self.tl = f.make_team_leader()
        self.event = f.make_event(event_status='finished')
        f.assign_team_leader(self.event, self.tl)

    def test_can_still_process_applications_on_finished_own_event(self):
        self.assertTrue(can_process_applications(self.tl, self.event.id))

    def test_no_extended_profile_access_after_finish(self):
        volunteer = f.make_user()
        f.make_application(self.event, user=volunteer)
        self.assertFalse(has_extended_access_to_profile(self.tl, volunteer))


class ExtendedProfileAccessTests(TestCase):
    """has_extended_access_to_profile: владелец/менеджер — всегда; ТЛ — только если
    целевой волонтёр связан именно с ЕГО активным мероприятием (заявка/участие)."""

    def setUp(self):
        self.tl = f.make_team_leader()
        self.event = f.make_event()
        f.assign_team_leader(self.event, self.tl)

    def test_owner_always_has_access_to_self(self):
        volunteer = f.make_user()
        self.assertTrue(has_extended_access_to_profile(volunteer, volunteer))

    def test_manager_always_has_access(self):
        manager = f.make_manager()
        stranger = f.make_user()
        self.assertTrue(has_extended_access_to_profile(manager, stranger))

    def test_tl_has_access_to_applicant_of_own_event(self):
        applicant = f.make_user()
        f.make_application(self.event, user=applicant)
        self.assertTrue(has_extended_access_to_profile(self.tl, applicant))

    def test_tl_has_access_to_participant_of_own_event(self):
        shift = f.make_shift(self.event, days_from_now=-1)
        participant = f.make_user()
        f.make_participation(participant, shift, status='attended')
        self.assertTrue(has_extended_access_to_profile(self.tl, participant))

    def test_tl_no_access_to_unrelated_volunteer(self):
        """ТЛ ведёт своё меро, но целевой волонтёр никак с ним не связан —
        доступа быть не должно, даже если ТЛ технически «активен»."""
        unrelated = f.make_user()
        self.assertFalse(has_extended_access_to_profile(self.tl, unrelated))

    def test_tl_no_access_via_foreign_event(self):
        """Волонтёр подал заявку на ЧУЖОЕ (не ТЛ-шное) мероприятие — доступа нет."""
        foreign_event = f.make_event()
        applicant = f.make_user()
        f.make_application(foreign_event, user=applicant)
        self.assertFalse(has_extended_access_to_profile(self.tl, applicant))

    def test_plain_volunteer_has_no_access_to_others(self):
        viewer = f.make_user()
        target = f.make_user()
        self.assertFalse(has_extended_access_to_profile(viewer, target))


class TeamLeaderHttpFlowTests(TestCase):
    """Тот же инвариант через реальные HTTP-эндпоинты (в дополнение к unit-тестам
    выше) — application_shift_process уже используется тестами для менеджера/
    волонтёра (test_web_flows.py), здесь — недостающий сценарий ТЛ."""

    def test_tl_can_process_application_on_own_event(self):
        tl = f.make_team_leader()
        event = f.make_event()
        f.assign_team_leader(event, tl)
        shift = f.make_shift(event, days_from_now=2)
        applicant = f.make_user()
        app = f.make_application(event, user=applicant, shifts=[shift], status='new')

        self.client.force_login(tl)
        url = reverse('application_shift_process', args=[app.id, shift.id])
        r = self.client.post(url, {'status': 'approved'})
        self.assertEqual(r.status_code, 302)

        from blog.models import Participation
        self.assertTrue(Participation.objects.filter(user=applicant, event_day=shift).exists())

    def test_tl_forbidden_on_foreign_event(self):
        tl = f.make_team_leader()
        own_event = f.make_event()
        f.assign_team_leader(own_event, tl)
        foreign_event = f.make_event()
        shift = f.make_shift(foreign_event, days_from_now=2)
        applicant = f.make_user()
        app = f.make_application(foreign_event, user=applicant, shifts=[shift], status='new')

        self.client.force_login(tl)
        url = reverse('application_shift_process', args=[app.id, shift.id])
        r = self.client.post(url, {'status': 'approved'})
        self.assertEqual(r.status_code, 403)

    def test_tl_can_view_extended_profile_of_own_applicant(self):
        tl = f.make_team_leader()
        event = f.make_event()
        f.assign_team_leader(event, tl)
        applicant = f.make_user()
        f.make_application(event, user=applicant)

        self.client.force_login(tl)
        r = self.client.get(reverse('profile_detail', args=[applicant.id]))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'blog/profile_manage.html')
