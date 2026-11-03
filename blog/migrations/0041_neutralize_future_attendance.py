"""Убрать прежнюю автоматическую явку у ещё не начавшихся смен."""
from django.db import migrations
from django.db.models import Sum, Count
from django.utils import timezone


def neutralize_future_attendance(apps, schema_editor):
    """Прошедшие участия и ручные корректировки часов сохраняются."""
    alias = schema_editor.connection.alias
    Participation = apps.get_model('blog', 'Participation')
    User = apps.get_model('blog', 'User')
    Season = apps.get_model('blog', 'Season')
    Const = apps.get_model('blog', 'Const')
    future = Participation.objects.using(alias).filter(
        event_day__start_time__gt=timezone.now(), status='attended', hours_overridden=False,
    )
    user_ids = list(future.values_list('user_id', flat=True).distinct())
    future.update(status='pending', hours=0, full_shift=False)
    season = Season.objects.using(alias).filter(start_season__lte=timezone.localdate()).order_by('-start_season').first()
    for user_id in user_ids:
        attended = Participation.objects.using(alias).filter(user_id=user_id, status='attended')
        total = attended.aggregate(hours=Sum('hours'), count=Count('pk'))
        current = attended.filter(event_day__day__gte=season.start_season) if season else attended.none()
        if season and season.end_season:
            current = current.filter(event_day__day__lte=season.end_season)
        seasonal = current.aggregate(hours=Sum('hours'), count=Count('pk'))
        last = attended.order_by('-event_day__day').first()
        User.objects.using(alias).filter(pk=user_id).update(
            total_hours=total['hours'] or 0, total_event_count=total['count'],
            season_hours=seasonal['hours'] or 0, season_event_count=seasonal['count'],
            last_event_at=last.created_at if last else None,
        )
    Const.objects.using(alias).get_or_create(name='qr_scanner_scoped_access', defaults={
        'value': 0, 'description': 'Сканер: 0 — оператор отмечает всех; 1 — только назначенные мероприятия.',
    })


class Migration(migrations.Migration):
    dependencies = [('blog', '0040_personal_qr_scanning_and_neutral_attendance')]
    operations = [migrations.RunPython(neutralize_future_attendance, migrations.RunPython.noop)]
