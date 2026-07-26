"""Технический демо-аккаунт витрины достижений + статистики.

    python manage.py create_all_achievements_account

Создаёт (идемпотентно) волонтёра `all_achivments` (веб-логин/пароль all_achivments) и:
  1. строит РЕАЛЬНУЮ историю участий за ~последний год — мероприятия в разные месяцы
     (пара месяцев намеренно пустые), разные категории/организации/локации, с явкой и
     часами → отсюда «сами собой» вытекают достижения по часам/меро/категориям/
     организациям и наполняется страница «Моя статистика»;
  2. доначисляет ВСЕ оставшиеся достижения (скорость отклика, курсы, точечные и т.п.),
     чтобы витрина была полной.

Повторный запуск досинхронизирует новые достижения. Это обычный волонтёр (без ролей),
достижения/история — технические (создаются напрямую), не «настоящая» активность.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from blog.models import (
    User, Event, EventShift, EventCategory, EventCategoryMap,
    Organization, Location, Participation,
)
from blog.services.achievements import ALL_ACHIEVEMENTS_LOGIN, grant_all_achievements
from blog.services.stats import recalc_user_aggregates
from blog.services.achievements import recalc_user_achievements


# Месяцы назад, в которых у витрины есть активность (0 = текущий). 2 и 5 месяцев назад —
# намеренно ПУСТЫЕ, чтобы на странице статистики были видны и «тихие» периоды.
_ACTIVE_MONTHS_AGO = [0, 1, 3, 4, 6, 7, 8, 10, 11]


class Command(BaseCommand):
    help = 'Создаёт/синхронизирует техаккаунт-витрину all_achivments (история за год + все достижения).'

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        user, created = User.objects.get_or_create(
            telegram_id='demo:all_achivments',
            defaults={
                'telegram_username': ALL_ACHIEVEMENTS_LOGIN,
                'first_name': 'Все', 'last_name': 'Достижения',
                'phone': '+7 900 000-00-00', 'status': 'active',
                'registration_status': 'registered',
            },
        )
        if user.login != ALL_ACHIEVEMENTS_LOGIN:
            user.login = ALL_ACHIEVEMENTS_LOGIN
        if not user.has_usable_password() or not user.check_password(ALL_ACHIEVEMENTS_LOGIN):
            user.set_password(ALL_ACHIEVEMENTS_LOGIN)
            user.web_credentials_set_at = now
        user.save()
        # created_at имеет auto_now_add — get_or_create/save его не бэкдейтит. Ставим «год
        # назад» точечным update(), чтобы стаж витрины выглядел правдоподобно.
        User.objects.filter(pk=user.pk).update(created_at=now - datetime.timedelta(days=365))

        self._build_history(user, now)

        # История создана — пересчитываем агрегаты и достижения от РЕАЛЬНОЙ активности,
        # затем доначисляем всё остальное (тир-достижения без активности: отклики/курсы).
        recalc_user_aggregates(user)
        recalc_user_achievements(user)
        granted = grant_all_achievements(user)

        state = 'создан' if created else 'обновлён'
        self.stdout.write(self.style.SUCCESS(
            f'[OK] Техаккаунт all_achivments {state}: id={user.id}, '
            f'история за год построена, доначислено достижений={granted}'
        ))

    def _build_history(self, user, now):
        """Идемпотентно создаёт демо-меро витрины (по префиксу title) с участиями в
        разные месяцы. Категории/организации/локации переиспользуем/создаём."""
        cats = self._ensure_categories(['Спорт', 'Экология', 'Культура', 'Образование'])
        orgs = self._ensure_orgs(['Беговое сообщество', 'ЭкоЦентр', 'Городской музей'])
        locs = self._ensure_locations(['Парк Горького', 'Кампус ВШЭ', 'Набережная'])

        combos = [
            ('Спорт', 'Беговое сообщество', 'Парк Горького', 5),
            ('Экология', 'ЭкоЦентр', 'Набережная', 4),
            ('Культура', 'Городской музей', 'Кампус ВШЭ', 6),
            ('Образование', 'ЭкоЦентр', 'Кампус ВШЭ', 3),
        ]
        for i, months_ago in enumerate(_ACTIVE_MONTHS_AGO):
            cat_name, org_name, loc_name, hours = combos[i % len(combos)]
            day = (now - datetime.timedelta(days=30 * months_ago + 3)).date()
            title = f'[Витрина] {cat_name} · {day.isoformat()}'
            event, ev_created = Event.objects.get_or_create(
                title=title,
                defaults={
                    'description': 'Демо-мероприятие витрины достижений.',
                    'organization': orgs[org_name],
                    'event_status': 'finished',
                    'people_helped': 20 + i * 5,
                    'published_at': now - datetime.timedelta(days=30 * months_ago + 10),
                    'post_published_at': now - datetime.timedelta(days=30 * months_ago + 10),
                },
            )
            if not ev_created:
                continue
            EventCategoryMap.objects.get_or_create(event=event, category=cats[cat_name])
            start = timezone.make_aware(datetime.datetime.combine(day, datetime.time(10, 0)))
            shift = EventShift.objects.create(
                event=event, day=day, start_time=start,
                end_time=start + datetime.timedelta(hours=hours),
                location=locs[loc_name], volunteer_needed=5, recruit_status='closed',
            )
            Participation.objects.create(
                user=user, event_day=shift, status='attended', hours=hours,
            )

    def _ensure_categories(self, names):
        out = {}
        for n in names:
            out[n], _ = EventCategory.objects.get_or_create(name=n)
        return out

    def _ensure_orgs(self, names):
        out = {}
        for n in names:
            out[n] = Organization.objects.filter(name=n).first() or Organization.objects.create(name=n)
        return out

    def _ensure_locations(self, names):
        out = {}
        for n in names:
            out[n] = Location.objects.filter(name=n).first() or Location.objects.create(name=n)
        return out
