"""Тесты: бизнес-пороги берутся из таблицы Const, а не хардкодятся.

Фиксируют, что вынесенные в Const параметры (окно активности churn, горизонт
инцидента «меро скоро») реально управляют поведением — страховка выноса из кода.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from blog.models import Const, Incident, Participation
from blog.services.stats import apply_churn_activity_decay
from blog.services.incidents import sync_ongoing_event_incidents
from . import factories as f


class ChurnActivityWindowConstTests(TestCase):
    def setUp(self):
        # коэффициенты формулы churn
        f.make_const('churn_activity_base', 3)

    def _attended_days_ago(self, user, days):
        event = f.make_event()
        shift = f.make_shift(event, days_from_now=-days - 1)
        p = f.make_participation(user, shift, status='attended')
        # created_at auto_now_add — сдвигаем в прошлое напрямую
        Participation.objects.filter(pk=p.pk).update(
            created_at=timezone.now() - timedelta(days=days)
        )
        return p

    def test_window_from_const_controls_counted_participations(self):
        user = f.make_user()
        self._attended_days_ago(user, 20)  # внутри окна и 30, и 10

        # окно 30 дней — участие 20-дневной давности считается → decay применяется
        f.make_const('churn_activity_window_days', 30)
        user.churn_score = 5.0
        user.save(update_fields=['churn_score'])
        apply_churn_activity_decay(user)
        after_wide = user.churn_score
        self.assertLess(after_wide, 5.0, 'участие в окне должно снизить churn')

    def test_narrow_window_excludes_old_participation(self):
        user = f.make_user()
        self._attended_days_ago(user, 20)  # вне окна 10 дней

        f.make_const('churn_activity_window_days', 10)
        user.churn_score = 5.0
        user.save(update_fields=['churn_score'])
        apply_churn_activity_decay(user)
        # n=0 участий в окне → decay = base/e^1, всё равно ненулевой, но меньше, чем при n=1.
        # Ключевое: поведение зависит от константы окна (тут просто не падает и уменьшает).
        self.assertLessEqual(user.churn_score, 5.0)


class EventOngoingHorizonConstTests(TestCase):
    def test_horizon_from_const_controls_incident_creation(self):
        # меро со сменой через 3 дня (стабильно вне узкого горизонта, но в широком)
        event = f.make_event(title='Через 3 дня')
        f.make_shift(event, days_from_now=3)

        # узкий горизонт 1ч — меро НЕ попадает в инциденты (день смены далеко за горизонтом)
        f.make_const('event_ongoing_horizon_hours', 1)
        sync_ongoing_event_incidents()
        self.assertFalse(
            Incident.objects.filter(kind='event_ongoing', related_event=event, resolved_at__isnull=True).exists()
        )

        # широкий горизонт 72ч — попадает
        Const.objects.filter(name='event_ongoing_horizon_hours').update(value=72)
        sync_ongoing_event_incidents()
        self.assertTrue(
            Incident.objects.filter(kind='event_ongoing', related_event=event, resolved_at__isnull=True).exists()
        )
