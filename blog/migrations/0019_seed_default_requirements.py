from django.db import migrations


REQUIREMENTS = [
    {
        'title': '18+',
        'description': 'Волонтёру должно быть не менее 18 лет. Проверяется автоматически по дате рождения в профиле.',
        'check_type': 'age',
    },
    {
        'title': 'Уверенное владение русским языком',
        'description': 'Волонтёр должен уверенно понимать и говорить по-русски.',
        'check_type': 'manual',
    },
    {
        'title': 'Знание английского языка',
        'description': 'Требуется для мероприятий с иностранными участниками/гостями.',
        'check_type': 'manual',
    },
    {
        'title': 'Опрятный внешний вид',
        'description': 'Требуется для представительских мероприятий.',
        'check_type': 'manual',
    },
]


def seed_requirements(apps, schema_editor):
    EventRequirement = apps.get_model('blog', 'EventRequirement')
    for item in REQUIREMENTS:
        EventRequirement.objects.get_or_create(
            title=item['title'],
            defaults={'description': item['description'], 'check_type': item['check_type']},
        )


def remove_requirements(apps, schema_editor):
    EventRequirement = apps.get_model('blog', 'EventRequirement')
    EventRequirement.objects.filter(title__in=[item['title'] for item in REQUIREMENTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0018_application_auto_reject_reason_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_requirements, remove_requirements),
    ]
