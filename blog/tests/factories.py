"""Фабрики валидных доменных объектов для тестов.

Минималистичные хелперы (без зависимости от factory_boy): создают объекты с
обязательными полями, остальное — дефолты моделей. Даты смен по умолчанию — в будущем
(upcoming), чтобы можно было подавать заявки.
"""
from datetime import timedelta

from django.utils import timezone

from blog.models import (
    User, Manager, TeamLeader, Organization, Organizer, Location,
    EventCategory, EventRequirement, Event, EventShift, EventStaff,
    Application, ApplicationShiftDecision, Participation, Season, Const,
)

_counter = {'n': 0}


def _uniq():
    _counter['n'] += 1
    return _counter['n']


def make_user(**kw):
    """Пользователь. telegram_id — единственное обязательное поле модели."""
    n = _uniq()
    defaults = dict(
        telegram_id=str(1000 + n),
        telegram_username=f'user{n}',
        first_name=f'Имя{n}',
        last_name=f'Фамилия{n}',
        phone=f'+7900000{n:04d}',
        system_username=f'user{n}',
        registration_status='member',
        status='active',
    )
    defaults.update(kw)
    return User.objects.create_user(**defaults)


def make_manager(user=None, **kw):
    """Пользователь-менеджер. Возвращает User (с активной ролью Manager)."""
    user = user or make_user(**kw)
    Manager.objects.create(user=user)
    # Менеджер всегда и тим-лидер (как в data_controller.create_manager).
    if not TeamLeader.objects.filter(user=user, revoked_at__isnull=True).exists():
        TeamLeader.objects.create(user=user)
    return user


def make_team_leader(user=None, **kw):
    user = user or make_user(**kw)
    TeamLeader.objects.create(user=user)
    return user


def make_location(name=None):
    return Location.objects.create(name=name or f'Локация {_uniq()}')


def make_organization(name=None):
    return Organization.objects.create(name=name or f'Организация {_uniq()}')


def make_organizer(**kw):
    n = _uniq()
    defaults = dict(first_name=f'Орг{n}', last_name=f'Оргов{n}')
    defaults.update(kw)
    return Organizer.objects.create(**defaults)


def make_category(name=None):
    return EventCategory.objects.create(name=name or f'Категория {_uniq()}')


def make_requirement(title=None, description=''):
    return EventRequirement.objects.create(
        title=title or f'Требование {_uniq()}', description=description
    )


def make_event(title=None, published=True, **kw):
    """Мероприятие. По умолчанию опубликованное (published_at выставлен)."""
    n = _uniq()
    defaults = dict(title=title or f'Мероприятие {n}', event_status='upcoming')
    defaults.update(kw)
    event = Event.objects.create(**defaults)
    if published and event.published_at is None:
        event.published_at = timezone.now()
        event.save(update_fields=['published_at'])
    return event


def make_shift(event, days_from_now=3, volunteer_needed=5, recruit_status='open', **kw):
    """Смена мероприятия. По умолчанию — через 3 дня (upcoming, набор открыт)."""
    day = timezone.localdate(timezone.now() + timedelta(days=days_from_now))
    start = timezone.now() + timedelta(days=days_from_now, hours=1)
    end = timezone.now() + timedelta(days=days_from_now, hours=5)
    defaults = dict(
        event=event, day=day, start_time=start, end_time=end,
        volunteer_needed=volunteer_needed, recruit_status=recruit_status,
    )
    defaults.update(kw)
    return EventShift.objects.create(**defaults)


def assign_team_leader(event, user):
    return EventStaff.objects.create(event=event, user=user, staff_role='team_lead')


def assign_manager(event, user):
    return EventStaff.objects.create(event=event, user=user, staff_role='manager')


def make_application(event, user=None, status='new', shifts=None, **kw):
    """Заявка + (опц.) привязка к сменам с ApplicationShiftDecision."""
    user = user if user is not None else make_user()
    defaults = dict(
        event=event, user=user,
        first_name=user.first_name or 'Имя',
        last_name=user.last_name or 'Фамилия',
        telegram_username=user.telegram_username,
        phone=user.phone,
        submitted_at=timezone.now(),
        status=status,
    )
    defaults.update(kw)
    app = Application.objects.create(**defaults)
    if shifts:
        app.selected_shifts.set(shifts)
        for sh in shifts:
            ApplicationShiftDecision.objects.create(application=app, shift=sh, status=status if status != 'cancelled' else 'new')
    return app


def make_participation(user, shift, status='attended', hours=4, **kw):
    defaults = dict(user=user, event_day=shift, status=status, hours=hours)
    defaults.update(kw)
    return Participation.objects.create(**defaults)


def make_season(days_ago_start=30, days_ahead_end=60):
    today = timezone.localdate()
    return Season.objects.create(
        start_season=today - timedelta(days=days_ago_start),
        end_season=today + timedelta(days=days_ahead_end),
    )


def make_const(name, value):
    return Const.objects.create(name=name, value=value)
