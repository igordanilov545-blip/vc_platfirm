"""Табличка желающих: строка = один день, ссылка на мероприятие, без дублей.

Старые строки со списком дат `wish_dates` разбиваются на строку на каждый день;
дубли — тот же человек (аккаунт → @username → телефон → ФИО) × мероприятие (название
без регистра/ё) × день, записанные разными ТЛ или повторно, — сливаются в самую раннюю
строку. Если забрали дубль, а не оставляемую строку, статус «Забрали» переносится.
"""
import datetime
import re

import django.db.models.deletion
from django.db import migrations, models


def _norm(value):
    return re.sub(r'\s+', ' ', (value or '').lower().replace('ё', 'е')).strip()


def _person_key(row):
    if row.get('user_id'):
        return ('user', row['user_id'])
    if row.get('telegram_username'):
        return ('tg', _norm(row['telegram_username']).lstrip('@'))
    if row.get('phone'):
        return ('phone', row['phone'])
    return ('name', _norm(row.get('full_name')))


TAKEN_FIELDS = ('taken_event_group_id', 'taken_by_id', 'taken_at')


def split_and_dedupe_rows(rows):
    """Чистая функция над dict-строками (по возрастанию created_at/pk).

    Возвращает {'keep': [{source_pk, wish_date (ISO|None), taken_*}...], 'delete': {pk}}:
    первая строка с source_pk обновляет исходную запись, остальные — её копии."""
    keep, delete, seen = [], set(), {}
    for row in rows:
        dates = list(dict.fromkeys(row.get('wish_dates') or [])) or [None]
        survived = False
        for day in dates:
            key = (_person_key(row), _norm(row.get('event_hint')), day)
            if key in seen:
                kept = seen[key]
                if row.get('taken_event_group_id') and not kept.get('taken_event_group_id'):
                    for field in TAKEN_FIELDS:
                        kept[field] = row.get(field)
                continue
            item = {'source_pk': row['pk'], 'wish_date': day}
            item.update({field: row.get(field) for field in TAKEN_FIELDS})
            seen[key] = item
            keep.append(item)
            survived = True
        if not survived:
            delete.add(row['pk'])
    return {'keep': keep, 'delete': delete}


def forwards(apps, schema_editor):
    Wish = apps.get_model('blog', 'VolunteerWish')
    originals = {wish.pk: wish for wish in Wish.objects.order_by('created_at', 'pk')}
    rows = [{
        'pk': wish.pk, 'telegram_username': wish.telegram_username, 'phone': wish.phone,
        'full_name': wish.full_name, 'user_id': wish.user_id, 'event_hint': wish.event_hint,
        'wish_dates': wish.wish_dates, 'taken_event_group_id': wish.taken_event_group_id,
        'taken_by_id': wish.taken_by_id, 'taken_at': wish.taken_at,
    } for wish in originals.values()]
    plan = split_and_dedupe_rows(rows)
    updated = set()
    for item in plan['keep']:
        source = originals[item['source_pk']]
        day = datetime.date.fromisoformat(item['wish_date']) if item['wish_date'] else None
        values = {'wish_date': day, **{field: item[field] for field in TAKEN_FIELDS}}
        if source.pk not in updated:
            Wish.objects.filter(pk=source.pk).update(**values)
            updated.add(source.pk)
            continue
        clone = Wish.objects.create(
            telegram_username=source.telegram_username, phone=source.phone, full_name=source.full_name,
            user_id=source.user_id, event_hint=source.event_hint, position_hint=source.position_hint,
            raw_text=source.raw_text, batch_id=source.batch_id, source=source.source,
            added_by_id=source.added_by_id, **values,
        )
        # auto_now_add ставит «сейчас» — возвращаем исходное время записи.
        Wish.objects.filter(pk=clone.pk).update(created_at=source.created_at)
    Wish.objects.filter(pk__in=plan['delete']).delete()


def backwards(apps, schema_editor):
    Wish = apps.get_model('blog', 'VolunteerWish')
    for wish in Wish.objects.all():
        Wish.objects.filter(pk=wish.pk).update(wish_dates=[wish.wish_date.isoformat()] if wish.wish_date else [])


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0056_volunteer_wishes'),
    ]

    operations = [
        migrations.AddField(
            model_name='volunteerwish',
            name='wish_date',
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='volunteerwish',
            name='event_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='wishes', to='blog.eventgroup'),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='volunteerwish',
            name='wish_dates',
        ),
    ]
