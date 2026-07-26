"""Бэкфилл динамических достижений под уже существующие категории/организации/меро.

Сигналы (blog/signals.py) заводят достижение при СОЗДАНИИ объекта — но объекты,
существовавшие до внедрения системы, их не получили. Здесь досоздаём по одному
достижению на каждый существующий объект (идемпотентно, get_or_create по code).

Ступени/оформление держим синхронно с blog.services.achievements (там же — единая
логика для новых объектов). Точечные достижения за меро — hidden, tier 'event'.
"""
from django.db import migrations


CATEGORY_STEPS = [1, 3, 5, 10, 25]
ORGANIZATION_STEPS = [1, 3, 5, 10]


def _steps(values):
    return [{'value': v, 'label': ('1 мероприятие' if v == 1 else f'{v} мероприятий')} for v in values]


def seed(apps, schema_editor):
    AchievementDefinition = apps.get_model('blog', 'AchievementDefinition')
    EventCategory = apps.get_model('blog', 'EventCategory')
    Organization = apps.get_model('blog', 'Organization')
    Event = apps.get_model('blog', 'Event')

    for cat in EventCategory.objects.all():
        AchievementDefinition.objects.get_or_create(
            code=f'category_{cat.id}',
            defaults=dict(
                kind='series', visibility='common', group='Категории',
                title=f'Волонтёр категории «{cat.name}»',
                description=f'Участвуй в мероприятиях категории «{cat.name}».',
                icon='🎯', series_steps=_steps(CATEGORY_STEPS),
                source_type='auto', is_active=True, tier='',
            ),
        )

    for org in Organization.objects.all():
        AchievementDefinition.objects.get_or_create(
            code=f'organization_{org.id}',
            defaults=dict(
                kind='series', visibility='common', group='Организации',
                title=f'Партнёр «{org.name}»',
                description=f'Участвуй в мероприятиях организации «{org.name}».',
                icon='🤝', series_steps=_steps(ORGANIZATION_STEPS),
                source_type='auto', is_active=True, tier='',
            ),
        )

    for ev in Event.objects.all():
        AchievementDefinition.objects.get_or_create(
            code=f'event_{ev.id}',
            defaults=dict(
                kind='single', visibility='hidden', group='Мероприятия',
                title=f'Участник: {ev.title}',
                description=f'Ты участвовал в мероприятии «{ev.title}».',
                icon='🎪', series_steps=None,
                source_type='auto', is_active=True, tier='event',
            ),
        )


def unseed(apps, schema_editor):
    AchievementDefinition = apps.get_model('blog', 'AchievementDefinition')
    AchievementDefinition.objects.filter(
        code__regex=r'^(category|organization|event)_\d+$'
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0037_all_achievements_account'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
