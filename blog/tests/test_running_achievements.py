"""Категории забегов и достижения бегового сообщества (решение пользователя 2026-11-11).

Категории («Старт», «Дистанция»…) — отдельно от функций ФиП: функция при выборе сама
проставляет свои категории по умолчанию, их можно поменять. Достижения: «был на
забеге» — на мероприятие (одной смены достаточно, роль не важна), копилка забегов и
смен, серия забегов подряд, тим-лидерские (видны только тим-лидерам) и особые факты.
"""
import json
from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import AchievementDefinition, EventCategory, EventGroup, EventStaff, UserAchievement
from blog.services.achievements import build_profile_achievements, progress_for, recalc_user_achievements
from blog.services.position_pool import assign_function, default_category_names, function_category
from . import factories as f


def _names(event, kind):
    return sorted(event.category_map.filter(category__kind=kind).values_list('category__name', flat=True))


class CategoriesTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.group = EventGroup.objects.create(title='Полумарафон')
        self.distance = EventCategory.objects.get(name='Волонтёры дистанции')
        self.day = (timezone.localdate() + timedelta(days=10)).isoformat()

    def create(self, function, **extra):
        shifts = [{'day': self.day, 'start_time': '08:00', 'end_time': '12:00', 'volunteer_needed': 5}]
        data = {'event_group': self.group.pk, 'function': function, 'shifts_json': json.dumps(shifts), **extra}
        self.client.post(reverse('event_create'), data)
        return self.group.positions.order_by('-pk').first()

    def test_functions_and_categories_are_separate_pools(self):
        self.assertEqual(self.distance.kind, 'function')
        self.assertEqual([c.name for c in self.distance.default_categories.all()], ['Дистанция'])
        start_finish = EventCategory.objects.get(name='Волонтёры старта и финиша')
        self.assertEqual(sorted(c.name for c in start_finish.default_categories.all()), ['Старт', 'Финиш'])
        self.assertTrue(AchievementDefinition.objects.filter(code=f'category_{EventCategory.objects.get(name="Дистанция").pk}').exists())
        self.assertFalse(AchievementDefinition.objects.filter(code=f'category_{self.distance.pk}').exists())

    def test_function_choice_sets_default_categories_and_manual_choice_wins(self):
        event = self.create(self.distance.pk)
        self.assertEqual(_names(event, 'function'), ['Волонтёры дистанции'])
        self.assertEqual(_names(event, 'category'), ['Дистанция'])
        medicine = EventCategory.objects.get(name='Медицина')
        event = self.create(self.distance.pk, categories=[medicine.pk])
        self.assertEqual(_names(event, 'category'), ['Медицина'])
        form = self.client.get(reverse('event_create') + f'?group={self.group.pk}')
        self.assertContains(form, 'data-default-categories="')
        self.assertContains(form, '＋ Новая категория')

    def test_new_function_gets_categories_by_words(self):
        self.assertEqual(default_category_names('Волонтёры финиша у раздевалок'), ['Финиш'])
        self.assertEqual(default_category_names('Волонтёры специальных стартов'), ['Эстафеты и спецстарты'])
        function = function_category('Медицинский пункт на старте')
        self.assertEqual(sorted(c.name for c in function.default_categories.all()), ['Медицина', 'Старт'])

    def test_imported_position_gets_categories_too(self):
        event = f.make_event(title='Волонтёр пункта освежения', event_group=self.group)
        assign_function(event)
        self.assertEqual((_names(event, 'function'), _names(event, 'category')), (['Волонтёры дистанции'], ['Дистанция']))

    def test_settings_edit_function_default_categories(self):
        medicine = EventCategory.objects.get(name='Медицина')
        self.client.post(reverse('category_edit', args=[self.distance.pk]),
                         {'name': self.distance.name, 'default_categories': [medicine.pk]})
        self.assertEqual([c.name for c in self.distance.default_categories.all()], ['Медицина'])
        self.client.post(reverse('category_create') + '?kind=category', {'name': 'Детские забеги', 'kind': 'category'})
        self.assertEqual(EventCategory.objects.get(name='Детские забеги').kind, 'category')


class RaceAchievementsTests(TestCase):
    def setUp(self):
        self.user = f.make_user()

    def race(self, title, days_ago, positions=1):
        group = EventGroup.objects.create(title=title)
        shifts = []
        for _ in range(positions):
            event = f.make_event(event_group=group)
            shifts.append(f.make_shift(event, days_from_now=-days_ago))
        return group, shifts

    def attend(self, shift, hours=4):
        return f.make_participation(self.user, shift, status='attended', hours=hours)

    def definition(self, code):
        return AchievementDefinition.objects.get(code=code)

    def test_one_shift_gives_race_badge_and_positions_do_not_multiply_races(self):
        group, shifts = self.race('Осенний полумарафон', 10, positions=2)
        for shift in shifts:
            self.attend(shift)
        recalc_user_achievements(self.user)
        self.assertTrue(UserAchievement.objects.filter(user=self.user, achievement__code=f'race_{group.pk}').exists())
        self.assertEqual(progress_for(self.user, self.definition('events_total')), 1)
        self.assertEqual(progress_for(self.user, self.definition('shifts_total')), 2)

    def test_team_lead_of_past_race_counts_without_attendance_mark(self):
        group, shifts = self.race('Ночной забег', 5)
        EventStaff.objects.create(event=shifts[0].event, user=self.user, staff_role='team_lead')
        self.assertTrue(progress_for(self.user, self.definition(f'race_{group.pk}')))
        self.assertEqual(progress_for(self.user, self.definition('team_lead_events')), 1)

    def test_streak_of_races_in_a_row(self):
        races = [self.race(f'Забег {i}', days, 1) for i, days in enumerate((40, 30, 20, 10))]
        for _, shifts in (races[0], races[2], races[3]):
            self.attend(shifts[0])
        self.assertEqual(progress_for(self.user, self.definition('race_streak')), 2)

    def test_team_lead_achievements_are_seen_only_by_team_leads(self):
        titles = {c['title'] for g in build_profile_achievements(self.user) for c in g['items']}
        self.assertNotIn('Тим-лидер забегов', titles)
        self.assertIn('Копилка забегов', titles)
        _, shifts = self.race('Забег', 3)
        EventStaff.objects.create(event=shifts[0].event, user=self.user, staff_role='team_lead')
        titles = {c['title'] for g in build_profile_achievements(self.user) for c in g['items']}
        self.assertIn('Тим-лидер забегов', titles)

    def test_special_facts(self):
        _, (shift,) = self.race('Рассветный забег', 3)
        early = timezone.make_aware(datetime.combine(shift.day, time(6, 0)))
        shift.start_time, shift.end_time = early, early + timedelta(hours=3)
        shift.save()
        self.attend(shift)
        self.assertTrue(progress_for(self.user, self.definition('early_bird')))
        group, (first,) = self.race('Двухдневный', 8)
        second = f.make_shift(first.event, days_from_now=-7)
        self.attend(first)
        self.assertFalse(progress_for(self.user, self.definition('all_days')))
        self.attend(second)
        self.assertTrue(progress_for(self.user, self.definition('all_days')))
        self.assertFalse(progress_for(self.user, self.definition('double_shift')))
        same_day = f.make_shift(first.event, days_from_now=-8)
        self.attend(same_day)
        self.assertTrue(progress_for(self.user, self.definition('double_shift')))

    def test_full_course_needs_start_distance_and_finish(self):
        for name in ('Волонтёры старта', 'Волонтёры дистанции', 'Волонтёры финиша'):
            self.assertFalse(progress_for(self.user, self.definition('full_course')))
            _, (shift,) = self.race(name, 3)
            assign_function(shift.event, category=EventCategory.objects.get(name=name))
            self.attend(shift)
        self.assertTrue(progress_for(self.user, self.definition('full_course')))
