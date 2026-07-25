"""Система достижений (achievements.md, этап «Ядро + auto»): движок пересчёта, выдача
series/single, идемпотентность, агрегат holders, скорость отклика, отображение в профиле.

База достижений приходит из seed-миграции 0034 — тесты опираются на её коды.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from blog.models import (
    AchievementDefinition, UserAchievement, EventCategoryMap, EventFeedback,
)
from blog.services.achievements import (
    recalc_user_achievements, build_profile_achievements, progress_for,
    _fastest_response_minutes,
)
from data_base import data_controller as dc
from . import factories as f


def _series_steps(user, code):
    return set(
        UserAchievement.objects.filter(user=user, achievement__code=code)
        .values_list('series_value', flat=True)
    )


def _codes(user):
    return set(
        UserAchievement.objects.filter(user=user)
        .values_list('achievement__code', flat=True)
    )


def _attend(user, event, hours=4, days_ago=3):
    shift = f.make_shift(event, days_from_now=-days_ago)
    f.make_participation(user, shift, status='attended', hours=hours)
    return shift


class SeedTests(TestCase):
    def test_base_definitions_seeded(self):
        # Ключевые коды из seed-миграции присутствуют и активны.
        for code in ['hours_total', 'events_total', 'first_event', 'profile_complete', 'response_1min']:
            self.assertTrue(AchievementDefinition.objects.filter(code=code, is_active=True).exists(), code)


class SeriesGrantTests(TestCase):
    def test_hours_series_grants_passed_steps_only(self):
        user = f.make_user()
        # 60 часов: ступени 10/50 взяты, 100 — нет (шаги из seed: 10,50,100,250…).
        event = f.make_event()
        _attend(user, event, hours=60)
        dc.recompute_achievement_stat  # noqa: ensure attr exists
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(user)  # дергает recalc достижений внутри

        hours_steps = set(
            UserAchievement.objects.filter(user=user, achievement__code='hours_total')
            .values_list('series_value', flat=True)
        )
        self.assertEqual(hours_steps, {10, 50})

    def test_series_row_per_step(self):
        """Решение этапа: у series — строка на КАЖДУЮ взятую ступень."""
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=250)
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(user)
        rows = UserAchievement.objects.filter(user=user, achievement__code='hours_total').count()
        self.assertEqual(rows, 4)  # 10,50,100,250

    def test_idempotent(self):
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=60)
        recalc_user_achievements(user)
        before = UserAchievement.objects.filter(user=user).count()
        recalc_user_achievements(user)
        recalc_user_achievements(user)
        after = UserAchievement.objects.filter(user=user).count()
        self.assertEqual(before, after)


class SingleGrantTests(TestCase):
    def test_first_event(self):
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=1)
        recalc_user_achievements(user)
        self.assertIn('first_event', _codes(user))

    def test_profile_complete(self):
        user = f.make_user()  # фабрика создаёт полный профиль (ФИО/TG/телефон)
        recalc_user_achievements(user)
        self.assertIn('profile_complete', _codes(user))

    def test_incomplete_profile_no_achievement(self):
        user = f.make_user(phone=None)
        recalc_user_achievements(user)
        self.assertNotIn('profile_complete', _codes(user))

    def test_verified_account(self):
        user = f.make_user()
        user.verified_by_manager_at = timezone.now()
        user.save(update_fields=['verified_by_manager_at'])
        recalc_user_achievements(user)
        self.assertIn('verified_account', _codes(user))


class ResponseSpeedTests(TestCase):
    def _make_app_with_response(self, user, minutes):
        event = f.make_event()
        event.post_published_at = timezone.now() - timedelta(minutes=minutes + 5)
        event.save(update_fields=['post_published_at'])
        f.make_application(
            event, user=user, status='new',
            submitted_at=event.post_published_at + timedelta(minutes=minutes),
        )
        return event

    def test_fast_response_grants_matching_tiers(self):
        user = f.make_user()
        self._make_app_with_response(user, minutes=3)  # ≤30 и ≤5, но не ≤1
        recalc_user_achievements(user)
        codes = _codes(user)
        self.assertIn('response_30min', codes)
        self.assertIn('response_5min', codes)
        self.assertNotIn('response_1min', codes)

    def test_slow_response_no_tier(self):
        user = f.make_user()
        self._make_app_with_response(user, minutes=45)
        recalc_user_achievements(user)
        self.assertNotIn('response_30min', _codes(user))


class DiversityTests(TestCase):
    def test_categories_diversity(self):
        user = f.make_user()
        cats = [f.make_category() for _ in range(2)]
        for cat in cats:
            event = f.make_event()
            EventCategoryMap.objects.create(event=event, category=cat)
            _attend(user, event, hours=1)
        recalc_user_achievements(user)
        # 2 категории → ступень 2 взята.
        steps = set(
            UserAchievement.objects.filter(user=user, achievement__code='categories_diversity')
            .values_list('series_value', flat=True)
        )
        self.assertIn(2, steps)

    def test_same_category_across_events_counted_once(self):
        """Одна и та же категория на двух меро = 1 уникальная категория (не 2)."""
        from blog.models import AchievementDefinition
        user = f.make_user()
        cat = f.make_category()
        for _ in range(2):
            event = f.make_event()
            EventCategoryMap.objects.create(event=event, category=cat)
            _attend(user, event, hours=1)
        self.assertEqual(
            progress_for(user, AchievementDefinition.objects.get(code='categories_diversity')),
            1,
        )

    def test_event_with_two_categories_counts_both(self):
        from blog.models import AchievementDefinition
        user = f.make_user()
        event = f.make_event()
        for _ in range(2):
            EventCategoryMap.objects.create(event=event, category=f.make_category())
        _attend(user, event, hours=1)
        self.assertEqual(
            progress_for(user, AchievementDefinition.objects.get(code='categories_diversity')),
            2,
        )


class StatTests(TestCase):
    def test_holders_count_recomputed(self):
        event = f.make_event()
        users = [f.make_user() for _ in range(3)]
        for u in users:
            _attend(u, event, hours=1)
            recalc_user_achievements(u)
        definition = AchievementDefinition.objects.get(code='first_event')
        stat = dc.recompute_achievement_stat(definition)
        self.assertEqual(stat.holders_count, 3)

    def test_series_holder_counted_once(self):
        """Держатель series с несколькими ступенями считается как один человек."""
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=250)
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(user)  # обновляет total_hours → эвалуатор видит 250
        definition = AchievementDefinition.objects.get(code='hours_total')
        stat = dc.recompute_achievement_stat(definition)
        self.assertEqual(stat.holders_count, 1)


class ProfileDisplayTests(TestCase):
    def test_common_shown_even_if_unearned(self):
        user = f.make_user()
        groups = build_profile_achievements(user, viewer_is_owner=True)
        all_codes = {c['code'] for g in groups for c in g['items']}
        # Общее незакрытое достижение показывается как цель.
        self.assertIn('hours_total', all_codes)

    def test_earned_card_has_date_and_flag(self):
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=1)
        recalc_user_achievements(user)
        groups = build_profile_achievements(user, viewer_is_owner=True)
        card = next(c for g in groups for c in g['items'] if c['code'] == 'first_event')
        self.assertTrue(card['earned'])
        self.assertIsNotNone(card['earned_at'])

    def test_hidden_unearned_not_shown(self):
        """Скрытое достижение до получения в профиле НЕ показывается (в отличие от общих)."""
        AchievementDefinition.objects.create(
            code='secret_x', kind='single', visibility='hidden', group='Секреты',
            title='Тайна', description='?', source_type='auto',
        )
        user = f.make_user()
        groups = build_profile_achievements(user, viewer_is_owner=True)
        all_codes = {c['code'] for g in groups for c in g['items']}
        self.assertNotIn('secret_x', all_codes)

    def test_hidden_earned_shown_with_holders_count_not_percent(self):
        """Скрытое полученное показывается; у него абсолютное число держателей, а не %."""
        d = AchievementDefinition.objects.create(
            code='secret_y', kind='single', visibility='hidden', group='Секреты',
            title='Тайна 2', description='?', source_type='auto',
        )
        user = f.make_user()
        dc.grant_achievement(user, d, series_value=None)
        dc.recompute_achievement_stat(d)
        groups = build_profile_achievements(user, viewer_is_owner=True)
        card = next(c for g in groups for c in g['items'] if c['code'] == 'secret_y')
        self.assertTrue(card['earned'])
        self.assertIsNone(card['holders_percent'])
        self.assertEqual(card['holders_count'], 1)

    def test_series_card_next_step_and_max(self):
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=60)
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(user)
        groups = build_profile_achievements(user, viewer_is_owner=True)
        card = next(c for g in groups for c in g['items'] if c['code'] == 'hours_total')
        self.assertEqual(card['current_step'], 50)          # взято 10 и 50 → текущая 50
        self.assertEqual(card['next_step_value'], 100)      # следующая невзятая
        self.assertEqual(card['max_step'], 1000)

    def test_series_all_steps_done_no_next(self):
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=1000)
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(user)
        groups = build_profile_achievements(user, viewer_is_owner=True)
        card = next(c for g in groups for c in g['items'] if c['code'] == 'hours_total')
        self.assertEqual(card['current_step'], 1000)
        self.assertIsNone(card['next_step_value'])

    def test_earned_sorted_before_locked(self):
        """Внутри группы полученные карточки идут выше незакрытых."""
        user = f.make_user()  # profile_complete получит (полный профиль) — earned;
        recalc_user_achievements(user)  # verified_account — нет (locked) в группе «Профиль»
        groups = build_profile_achievements(user, viewer_is_owner=True)
        profile_grp = next(g for g in groups if g['group'] == 'Профиль')
        earned_flags = [c['earned'] for c in profile_grp['items']]
        # Все earned=True идут раньше любого earned=False.
        self.assertEqual(earned_flags, sorted(earned_flags, reverse=True))

    def test_percent_none_when_no_denominator(self):
        """Нет живых держателей (никто не участвовал) → процент None, без деления на ноль."""
        user = f.make_user()  # без участий — denominator=0
        groups = build_profile_achievements(user, viewer_is_owner=True)
        card = next(c for g in groups for c in g['items'] if c['code'] == 'hours_total')
        self.assertIsNone(card['holders_percent'])

    def test_holders_percent_present_for_common(self):
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=1)
        recalc_user_achievements(user)
        dc.recompute_achievement_stat(AchievementDefinition.objects.get(code='first_event'))
        groups = build_profile_achievements(user, viewer_is_owner=True)
        card = next(c for g in groups for c in g['items'] if c['code'] == 'first_event')
        self.assertIsNotNone(card['holders_percent'])


class ProfilePageRenderTests(TestCase):
    def test_own_profile_shows_achievements_block(self):
        from django.urls import reverse
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=1)
        recalc_user_achievements(user)
        self.client.force_login(user)
        r = self.client.get(reverse('profile_detail', args=[user.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Достижения')
        self.assertContains(r, 'data-achievement')
        # Полученное «Первое мероприятие» — earned-класс; незакрытые общие — тоже видны.
        self.assertContains(r, 'achievement--earned')
        self.assertContains(r, 'achievement--locked')
        # Попап «как получить» с data-полями (иконка/описание/дата/держатели) отрендерен.
        self.assertContains(r, 'data-achievement-popup')
        self.assertContains(r, 'data-ach-desc')
        self.assertContains(r, 'data-ach-earned')

    def test_manager_sees_volunteer_achievements(self):
        """Менеджер на чужом профиле тоже видит блок достижений волонтёра."""
        from django.urls import reverse
        manager = f.make_manager()
        volunteer = f.make_user()
        event = f.make_event()
        _attend(volunteer, event, hours=1)
        recalc_user_achievements(volunteer)
        self.client.force_login(manager)
        r = self.client.get(reverse('profile_detail', args=[volunteer.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Достижения')
        self.assertContains(r, 'achievement--earned')


class EvaluatorTests(TestCase):
    """Прямая проверка каждого эвалуатора прогресса — граничные значения."""

    def _def(self, code):
        return AchievementDefinition.objects.get(code=code)

    def test_events_total_counts_distinct_events_not_shifts(self):
        """Две смены ОДНОГО меро = 1 мероприятие (а не 2)."""
        user = f.make_user()
        event = f.make_event()
        for _ in range(2):
            sh = f.make_shift(event, days_from_now=-3)
            f.make_participation(user, sh, status='attended', hours=2)
        self.assertEqual(progress_for(user, self._def('events_total')), 1)

    def test_events_total_two_events(self):
        user = f.make_user()
        for _ in range(2):
            _attend(user, f.make_event(), hours=1)
        self.assertEqual(progress_for(user, self._def('events_total')), 2)

    def test_only_attended_counts(self):
        """Неявка/уважительная не идут в прогресс мероприятий."""
        user = f.make_user()
        event = f.make_event()
        sh = f.make_shift(event, days_from_now=-3)
        f.make_participation(user, sh, status='absent_unexcused', hours=0)
        self.assertEqual(progress_for(user, self._def('events_total')), 0)

    def test_organizations_diversity(self):
        user = f.make_user()
        for _ in range(2):
            org = f.make_organization()
            _attend(user, f.make_event(organization=org), hours=1)
        self.assertEqual(progress_for(user, self._def('organizations_diversity')), 2)

    def test_organizations_diversity_ignores_null(self):
        user = f.make_user()
        _attend(user, f.make_event(), hours=1)  # без организации
        self.assertEqual(progress_for(user, self._def('organizations_diversity')), 0)

    def test_locations_diversity(self):
        user = f.make_user()
        event = f.make_event()
        for _ in range(2):
            loc = f.make_location()
            sh = f.make_shift(event, days_from_now=-3, location=loc)
            f.make_participation(user, sh, status='attended', hours=1)
        self.assertEqual(progress_for(user, self._def('locations_diversity')), 2)

    def test_organization_loyalty_max_per_org(self):
        """Лояльность = максимум мероприятий с ОДНОЙ организацией."""
        user = f.make_user()
        org_a = f.make_organization()
        org_b = f.make_organization()
        for _ in range(3):
            _attend(user, f.make_event(organization=org_a), hours=1)
        _attend(user, f.make_event(organization=org_b), hours=1)
        self.assertEqual(progress_for(user, self._def('organization_loyalty')), 3)

    def test_organization_loyalty_zero_without_orgs(self):
        user = f.make_user()
        _attend(user, f.make_event(), hours=1)
        self.assertEqual(progress_for(user, self._def('organization_loyalty')), 0)

    def test_team_lead_events(self):
        user = f.make_user()
        for _ in range(2):
            event = f.make_event()
            f.assign_team_leader(event, user)
        self.assertEqual(progress_for(user, self._def('team_lead_events')), 2)

    def test_feedbacks_and_applications_totals(self):
        user = f.make_user()
        e1, e2 = f.make_event(), f.make_event()
        EventFeedback.objects.create(event=e1, author=user, rating=8)
        EventFeedback.objects.create(event=e2, author=user, rating=9)
        f.make_application(e1, user=user)
        self.assertEqual(progress_for(user, self._def('feedbacks_total')), 2)
        self.assertEqual(progress_for(user, self._def('applications_total')), 1)

    def test_people_helped_sums_attended_events(self):
        user = f.make_user()
        e1 = f.make_event(people_helped=100)
        e2 = f.make_event(people_helped=50)
        _attend(user, e1, hours=1)
        _attend(user, e2, hours=1)
        self.assertEqual(progress_for(user, self._def('people_helped')), 150)

    def test_people_helped_ignores_non_attended(self):
        user = f.make_user()
        e1 = f.make_event(people_helped=100)
        sh = f.make_shift(e1, days_from_now=-3)
        f.make_participation(user, sh, status='absent_excused', hours=0)
        self.assertEqual(progress_for(user, self._def('people_helped')), 0)

    def test_registered_single(self):
        user = f.make_user(registration_status='registered')
        self.assertTrue(progress_for(user, self._def('registered')))
        guest = f.make_user(registration_status='guest')
        self.assertFalse(progress_for(guest, self._def('registered')))

    def test_first_application_and_feedback(self):
        user = f.make_user()
        self.assertFalse(progress_for(user, self._def('first_application')))
        event = f.make_event()
        f.make_application(event, user=user)
        self.assertTrue(progress_for(user, self._def('first_application')))
        self.assertFalse(progress_for(user, self._def('first_feedback')))
        EventFeedback.objects.create(event=event, author=user, rating=7)
        self.assertTrue(progress_for(user, self._def('first_feedback')))

    def test_first_team_lead(self):
        user = f.make_user()
        self.assertFalse(progress_for(user, self._def('first_team_lead')))
        f.make_team_leader(user=user)
        self.assertTrue(progress_for(user, self._def('first_team_lead')))


class SeasonScopedTests(TestCase):
    def test_season_hours_and_events_granted_within_season(self):
        """Часы/меро за сезон дают достижения, когда есть активный сезон, покрывающий даты."""
        from blog.services.stats import recalc_user_aggregates
        f.make_season(days_ago_start=30, days_ahead_end=30)  # активный сезон вокруг сегодня
        user = f.make_user()
        _attend(user, f.make_event(), hours=12, days_ago=3)  # попадает в сезон
        recalc_user_aggregates(user)
        codes = _codes(user)
        self.assertIn('hours_season', codes)   # ступень 10 взята
        self.assertIn('events_season', codes)  # ступень 1 взята

    def test_out_of_season_participation_not_in_season_series(self):
        """Участие вне активного сезона не идёт в сезонные достижения."""
        from blog.services.stats import recalc_user_aggregates
        f.make_season(days_ago_start=5, days_ahead_end=30)  # сезон начался 5 дней назад
        user = f.make_user()
        _attend(user, f.make_event(), hours=12, days_ago=20)  # 20 дней назад — до сезона
        recalc_user_aggregates(user)
        self.assertNotIn('hours_season', _codes(user))


class ResponseSpeedEdgeTests(TestCase):
    def _app(self, user, delay_minutes, post_offset_minutes=60):
        event = f.make_event()
        event.post_published_at = timezone.now() - timedelta(minutes=post_offset_minutes)
        event.save(update_fields=['post_published_at'])
        f.make_application(
            event, user=user, status='new',
            submitted_at=event.post_published_at + timedelta(minutes=delay_minutes),
        )
        return event

    def test_no_post_published_at_no_metric(self):
        """Заявка без post_published_at не участвует в расчёте скорости отклика."""
        user = f.make_user()
        event = f.make_event()  # post_published_at = None
        f.make_application(event, user=user, submitted_at=timezone.now())
        self.assertIsNone(_fastest_response_minutes(user))

    def test_negative_delay_ignored(self):
        """Заявка раньше поста (аномалия) игнорируется, не даёт «мгновенный» отклик."""
        user = f.make_user()
        event = f.make_event()
        event.post_published_at = timezone.now()
        event.save(update_fields=['post_published_at'])
        f.make_application(
            event, user=user,
            submitted_at=event.post_published_at - timedelta(minutes=10),
        )
        self.assertIsNone(_fastest_response_minutes(user))

    def test_picks_minimum_across_applications(self):
        user = f.make_user()
        self._app(user, delay_minutes=20)
        self._app(user, delay_minutes=2)
        self.assertAlmostEqual(_fastest_response_minutes(user), 2, delta=0.01)

    def test_exact_boundary_counts(self):
        """Ровно на границе (5 минут) — достижение выдаётся (<=)."""
        user = f.make_user()
        self._app(user, delay_minutes=5)
        recalc_user_achievements(user)
        self.assertIn('response_5min', _codes(user))


class EngineBranchTests(TestCase):
    def test_manual_grant_skipped_by_engine(self):
        """Ручные достижения (курсы) движок не выдаёт автоматически."""
        AchievementDefinition.objects.create(
            code='course_x', kind='single', visibility='hidden', group='Курсы',
            title='Курс', description='?', source_type='manual_grant',
        )
        user = f.make_user()
        recalc_user_achievements(user)
        self.assertNotIn('course_x', _codes(user))

    def test_inactive_definition_skipped(self):
        d = AchievementDefinition.objects.get(code='first_event')
        d.is_active = False
        d.save(update_fields=['is_active'])
        user = f.make_user()
        _attend(user, f.make_event(), hours=1)
        recalc_user_achievements(user)
        self.assertNotIn('first_event', _codes(user))

    def test_unknown_code_skipped(self):
        """auto-достижение с кодом без эвалуатора движок пропускает (не падает)."""
        AchievementDefinition.objects.create(
            code='no_evaluator', kind='single', visibility='common', group='X',
            title='Без эвалуатора', source_type='auto',
        )
        user = f.make_user()
        # Не должно бросить исключение.
        recalc_user_achievements(user)
        self.assertNotIn('no_evaluator', _codes(user))

    def test_returns_newly_granted(self):
        user = f.make_user()
        _attend(user, f.make_event(), hours=1)
        newly = recalc_user_achievements(user)
        codes = {ua.achievement.code for ua in newly}
        self.assertIn('first_event', codes)
        # Повторный вызов — ничего нового.
        self.assertEqual(recalc_user_achievements(user), [])

    def test_stat_updated_after_grant(self):
        """После выдачи движок пересчитывает holders_count затронутых достижений."""
        user = f.make_user()
        _attend(user, f.make_event(), hours=1)
        recalc_user_achievements(user)
        d = AchievementDefinition.objects.get(code='first_event')
        self.assertEqual(d.stat.holders_count, 1)


class HookIntegrationTests(TestCase):
    """Достижения доначисляются в реальных пользовательских потоках (через вьюхи/сервисы)."""

    def test_application_create_grants_first_application(self):
        from django.urls import reverse
        user = f.make_user()
        event = f.make_event()
        f.make_shift(event, days_from_now=3)
        self.client.force_login(user)
        r = self.client.post(
            reverse('application_create'),
            {'event': event.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertIn(r.status_code, (200, 302))
        self.assertIn('first_application', _codes(user))

    def test_feedback_grants_first_feedback(self):
        from django.urls import reverse
        user = f.make_user()
        event = f.make_event()
        _attend(user, event, hours=2)  # участник — может оставить отзыв
        self.client.force_login(user)
        self.client.post(reverse('event_feedback_add', args=[event.id]), {'rating': 8, 'comment': 'ок'})
        self.assertIn('first_feedback', _codes(user))

    def test_verification_grants_verified_account(self):
        from blog.services.moderation import verify_user_for_pgas
        manager = f.make_manager()
        user = f.make_user()
        verify_user_for_pgas(user, actor=manager, snapshot={})
        self.assertIn('verified_account', _codes(user))

    def test_role_assignment_grants_first_team_lead(self):
        from blog.services.roles import assign_role
        manager = f.make_manager()
        user = f.make_user()
        assign_role('team_lead', [user], assigned_by=manager)
        self.assertIn('first_team_lead', _codes(user))

    def test_attendance_recalc_grants_hours_and_events(self):
        """Пересчёт агрегатов (явка/часы) доначисляет часовые/мероприятийные достижения."""
        from blog.services.stats import recalc_user_aggregates
        user = f.make_user()
        _attend(user, f.make_event(), hours=10)
        recalc_user_aggregates(user)
        codes = _codes(user)
        self.assertIn('first_event', codes)
        self.assertIn('hours_total', codes)   # ступень 10 взята
        self.assertIn('events_total', codes)  # ступень 1 взята
