"""Management-команды с бизнес-эффектом (close_season, recalc_stats,
dedupe_applications) — testing-audit.md отмечал их как непокрытые, при том что
close_season/recalc_stats напрямую трогают часовые агрегаты волонтёров по всей базе:
тихая поломка здесь означает неверную статистику у всех разом.
"""
import io

from django.core.management import call_command
from django.test import TestCase

from blog.models import Application, ChurnLog, Season
from . import factories as f


class RecalcStatsCommandTests(TestCase):
    def test_recalc_fixes_stale_aggregate(self):
        user = f.make_user()
        event = f.make_event()
        shift = f.make_shift(event, days_from_now=-1)
        f.make_participation(user, shift, status='attended', hours=5)
        # Симулируем «застрявший» кэш (реальный баг, который чинила эта команда).
        user.total_hours = 0
        user.save(update_fields=['total_hours'])

        out = io.StringIO()
        call_command('recalc_stats', stdout=out)

        user.refresh_from_db()
        self.assertEqual(user.total_hours, 5)
        self.assertIn('Пересчитана статистика', out.getvalue())


class CloseSeasonCommandTests(TestCase):
    def setUp(self):
        self.season = f.make_season(days_ago_start=10, days_ahead_end=5)

    def test_close_season_snapshots_churn_and_resets(self):
        f.make_const('churn_carryover_min_seasons', 2)
        user = f.make_user()
        user.churn_score = 4
        user.save(update_fields=['churn_score'])

        out = io.StringIO()
        call_command('close_season', stdout=out)

        user.refresh_from_db()
        self.assertEqual(user.churn_score, 0, 'при первом закрытии сезона (нет истории) churn обнуляется')
        self.assertTrue(ChurnLog.objects.filter(user=user, reason='season_reset').exists())
        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.end_season)

    def test_close_season_creates_next_open_season(self):
        call_command('close_season', stdout=io.StringIO())
        self.season.refresh_from_db()
        self.assertTrue(Season.objects.filter(start_season__gt=self.season.end_season).exists())

    def test_close_specific_season_by_id(self):
        out = io.StringIO()
        call_command('close_season', '--id', str(self.season.id), stdout=out)
        self.assertIn('закрыт', out.getvalue())

    def test_unknown_season_id_raises(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('close_season', '--id', '999999', stdout=io.StringIO())

    def test_no_current_season_raises(self):
        Season.objects.all().delete()
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('close_season', stdout=io.StringIO())


class DedupeApplicationsCommandTests(TestCase):
    def setUp(self):
        self.event = f.make_event()

    def test_dry_run_does_not_delete(self):
        volunteer = f.make_user(telegram_username='dup_tg')
        f.make_application(self.event, user=volunteer, status='new', telegram_username='dup_tg')
        f.make_application(self.event, user=volunteer, status='new', telegram_username='dup_tg')
        self.assertEqual(Application.objects.filter(event=self.event).count(), 2)

        out = io.StringIO()
        call_command('dedupe_applications', '--dry-run', stdout=out)

        self.assertEqual(Application.objects.filter(event=self.event).count(), 2)
        self.assertIn('DRY-RUN', out.getvalue())

    def test_real_run_keeps_one_and_prefers_processed(self):
        volunteer = f.make_user(telegram_username='dup_tg2')
        new_app = f.make_application(self.event, user=volunteer, status='new', telegram_username='dup_tg2')
        approved_app = f.make_application(self.event, user=volunteer, status='approved', telegram_username='dup_tg2')

        call_command('dedupe_applications', stdout=io.StringIO())

        remaining = Application.objects.filter(event=self.event, user=volunteer)
        self.assertEqual(remaining.count(), 1, 'должна остаться ровно одна заявка из группы дублей')
        self.assertEqual(remaining.first().id, approved_app.id, 'обработанная заявка должна иметь приоритет над новой')
        self.assertFalse(Application.objects.filter(id=new_app.id).exists())

    def test_no_duplicates_nothing_deleted(self):
        f.make_application(self.event, status='new')
        f.make_application(self.event, status='new')  # разные люди — не дубли
        before = Application.objects.count()
        call_command('dedupe_applications', stdout=io.StringIO())
        self.assertEqual(Application.objects.count(), before)
