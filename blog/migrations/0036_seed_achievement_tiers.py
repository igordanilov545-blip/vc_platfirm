"""Проставляет уровень сложности (tier) single-достижениям базового набора
(achievements.py TIERS). series-достижениям явный tier не нужен — там уровень каждой
карточки-ступени = её порядковый номер (см. build_profile_achievements).

Идемпотентно: только выставляет поле tier по коду. Уникальные уровни ('event'/'course')
появятся вместе с точечными/курсовыми достижениями на следующих этапах.
"""
from django.db import migrations


# code → tier (строкой, как хранится в поле). 1 — «база» (профиль/первые шаги),
# растёт до 6 — «откликнуться за минуту».
SINGLE_TIERS = {
    'registered': '1',
    'first_event': '1',
    'first_application': '1',
    'profile_complete': '1',
    'first_feedback': '1',
    'first_team_lead': '2',
    'verified_account': '2',
    'response_30min': '4',
    'response_5min': '5',
    'response_1min': '6',
}


def seed(apps, schema_editor):
    AchievementDefinition = apps.get_model('blog', 'AchievementDefinition')
    for code, tier in SINGLE_TIERS.items():
        AchievementDefinition.objects.filter(code=code).update(tier=tier)


def unseed(apps, schema_editor):
    AchievementDefinition = apps.get_model('blog', 'AchievementDefinition')
    AchievementDefinition.objects.filter(code__in=SINGLE_TIERS).update(tier='')


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0035_achievementdefinition_tier'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
