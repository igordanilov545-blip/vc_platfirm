"""Провижнит техаккаунт-витрину `all_achivments` при миграции — чтобы он существовал в
ЛЮБОЙ среде (локально/CI/прод) без ручного запуска команды.

Создаёт волонтёра с веб-входом all_achivments / all_achivments и выдаёт ему ВСЕ
достижения из справочника (каждую ступень series + каждое single/hidden/manual).
Идемпотентно. Пароль ставим через make_password (методов AbstractBaseUser у историч.
модели нет). Дальнейшую досинхронизацию новых достижений делает команда
create_all_achievements_account (см. achievements.grant_all_achievements).
"""
from django.contrib.auth.hashers import make_password
from django.db import migrations
from django.utils import timezone


LOGIN = 'all_achivments'


def _steps(series_steps):
    out = []
    for s in (series_steps or []):
        try:
            out.append(int(s['value']))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def seed(apps, schema_editor):
    User = apps.get_model('blog', 'User')
    AchievementDefinition = apps.get_model('blog', 'AchievementDefinition')
    UserAchievement = apps.get_model('blog', 'UserAchievement')
    AchievementStat = apps.get_model('blog', 'AchievementStat')

    user, _ = User.objects.get_or_create(
        telegram_id='demo:all_achivments',
        defaults={
            'telegram_username': LOGIN,
            'first_name': 'Все',
            'last_name': 'Достижения',
            'phone': '+7 900 000-00-00',
            'status': 'active',
            'registration_status': 'registered',
        },
    )
    # Веб-вход (идемпотентно, без методов AbstractBaseUser).
    changed = False
    if user.login != LOGIN:
        user.login = LOGIN
        changed = True
    if not (user.password or '').startswith(('pbkdf2_', 'argon2', 'bcrypt')):
        user.password = make_password(LOGIN)
        user.web_credentials_set_at = timezone.now()
        changed = True
    if changed:
        user.save()

    touched = set()
    for d in AchievementDefinition.objects.filter(is_active=True):
        targets = _steps(d.series_steps) if d.kind == 'series' else [None]
        for sv in targets:
            _, created = UserAchievement.objects.get_or_create(
                user=user, achievement=d, series_value=sv,
            )
            if created:
                touched.add(d.id)

    # Пересчёт агрегата держателей затронутых достижений.
    from django.db.models import Count, Min, Max
    for aid in touched:
        agg = UserAchievement.objects.filter(achievement_id=aid).aggregate(
            holders=Count('user', distinct=True), first=Min('granted_at'), last=Max('granted_at'),
        )
        AchievementStat.objects.update_or_create(
            achievement_id=aid,
            defaults={
                'holders_count': agg['holders'] or 0,
                'first_granted_at': agg['first'],
                'last_granted_at': agg['last'],
            },
        )


def unseed(apps, schema_editor):
    # Аккаунт не удаляем (мог накопить данные/сессии) — только чистим его достижения.
    User = apps.get_model('blog', 'User')
    UserAchievement = apps.get_model('blog', 'UserAchievement')
    user = User.objects.filter(login=LOGIN).first()
    if user:
        UserAchievement.objects.filter(user=user).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0036_seed_achievement_tiers'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
