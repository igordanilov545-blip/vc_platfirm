"""CRUD связи FaP, планов, назначений и зашифрованной Google-интеграции."""
from blog.models import (
    Event, EventShift, EventStaff, EventDirection, SheetPosition, SheetPositionDay, Organization,
    SheetShift, SheetTeamLeader, ZoneResponsible, EventSheetLink, GoogleSheetsConnection,
)
from ._base import logger, actor
from django.core.exceptions import ValidationError


def event_directions_qs():
    return EventDirection.objects.all()


def sheet_positions_qs():
    return SheetPosition.objects.all()


def sheet_days_qs():
    return SheetPositionDay.objects.all()


def sheet_shifts_qs():
    return SheetShift.objects.all()


def sheet_leaders_qs():
    return SheetTeamLeader.objects.all()


def zone_responsibles_qs():
    return ZoneResponsible.objects.all()


def event_sheet_links_qs():
    return EventSheetLink.objects.all()


def google_sheets_connection():
    return GoogleSheetsConnection.objects.filter(pk=1).first()


def save_google_sheets_connection(encrypted, email, operator):
    connection, _ = GoogleSheetsConnection.objects.update_or_create(pk=1, defaults={
        'credentials_encrypted': encrypted, 'client_email': email, 'updated_by': operator,
    })
    logger.info('SAVE google_sheets_connection: by=%s', actor(operator))
    return connection


def save_event_sheet_link(group, **values):
    link, _ = EventSheetLink.objects.update_or_create(event_group=group, defaults=values)
    logger.info('SAVE event_sheet_links: group=%s', group.pk)
    return link


def save_sheet_direction(group, source_key, name, order):
    obj, _ = EventDirection.objects.update_or_create(event_group=group, source_key=source_key, defaults={'name': name, 'sort_order': order})
    logger.info('SAVE event_directions: direction=%s group=%s', obj.pk, group.pk)
    return obj


def save_sheet_position(group, direction, source_key, name, order, is_lead, existing_event=None):
    obj = SheetPosition.objects.filter(source_key=source_key, event__event_group=group).first()
    if obj is None:
        event = existing_event or Event.objects.create(title=name, event_group=group, organization=Organization.objects.order_by('pk').first())
        obj = SheetPosition.objects.create(event=event, direction=direction, source_key=source_key)
    obj.direction, obj.sort_order, obj.is_team_lead_role = direction, order, is_lead
    obj.save(update_fields=['direction', 'sort_order', 'is_team_lead_role'])
    Event.objects.filter(pk=obj.event_id).update(title=name)
    logger.info('SAVE sheet_positions: position=%s event=%s', obj.pk, obj.event_id)
    return obj


def save_sheet_day(position, day, work, checks, quantities):
    obj, _ = SheetPositionDay.objects.update_or_create(position=position, day=day, defaults={
        'raw_work_time': work, 'raw_checkin_out': checks, 'quantities': quantities,
    })
    logger.info('SAVE sheet_position_days: day=%s', obj.pk)
    return obj


def save_sheet_shift(position_day, source_key, label, start, end, count, checkin, checkout, order, existing_shift=None):
    obj = SheetShift.objects.filter(source_key=source_key, position_day__position=position_day.position).first()
    if obj is None:
        shift = existing_shift or EventShift.objects.create(event=position_day.position.event, day=position_day.day, start_time=start, end_time=end, volunteer_needed=count or 0)
        obj = SheetShift.objects.create(shift=shift, position_day=position_day, source_key=source_key)
    EventShift.objects.filter(pk=obj.shift_id).update(day=position_day.day, start_time=start, end_time=end, volunteer_needed=count or 0)
    obj.position_day, obj.label, obj.planned_count = position_day, label, count
    obj.checkin, obj.checkout, obj.sort_order = checkin, checkout, order
    obj.save()
    logger.info('SAVE sheet_shifts: source=%s shift=%s', source_key, obj.shift_id)
    return obj


def sync_sheet_staff(direction, position, names, kind):
    model = SheetTeamLeader if kind == 'team_lead' else ZoneResponsible
    scope = model.objects.filter(position=position) if position is not None else model.objects.filter(direction=direction, position=None)
    existing = list(scope)
    keep = []
    for order, name in enumerate(names):
        obj = next((item for item in existing if item.display_name == name and item.pk not in keep), None)
        if obj is None:
            obj = model(direction=direction, position=position, display_name=name)
        obj.sort_order, obj.direction = order, direction
        obj.save()
        keep.append(obj.pk)
    removed = scope.exclude(pk__in=keep)
    links = list(EventStaff.objects.filter(sheet_sources__in=removed).distinct()) if kind == 'team_lead' else []
    removed.delete()
    for staff in links:
        if not staff.sheet_sources.exists():
            staff.delete()
    logger.info('SYNC sheet_staff: direction=%s position=%s kind=%s count=%s', direction.pk, position.pk if position else None, kind, len(keep))


def bind_sheet_leader_record(assignment, user, operator):
    assignment.user = user
    assignment.save(update_fields=['user'])
    refresh_sheet_leader_staff(assignment.direction.event_group_id)
    logger.info('BIND sheet_team_leader: assignment=%s user=%s by=%s', assignment.pk, user.pk, actor(operator))


def refresh_sheet_leader_staff(group_id):
    for assignment in SheetTeamLeader.objects.filter(direction__event_group_id=group_id).select_related('direction', 'position'):
        events = [assignment.position.event_id] if assignment.position_id else list(assignment.direction.positions.values_list('event_id', flat=True))
        obsolete = list(assignment.staff_links.exclude(event_id__in=events, user_id=assignment.user_id)) if assignment.user_id else list(assignment.staff_links.all())
        for staff in obsolete:
            assignment.staff_links.remove(staff)
            if not staff.sheet_sources.exists():
                staff.delete()
        if assignment.user_id:
            for event_id in events:
                staff = EventStaff.objects.filter(event_id=event_id, user_id=assignment.user_id, staff_role='team_lead').first()
                if staff is None:
                    staff = EventStaff.objects.create(event_id=event_id, user_id=assignment.user_id, staff_role='team_lead')
                    assignment.staff_links.add(staff)
                elif staff.sheet_sources.exists():
                    assignment.staff_links.add(staff)
    logger.info('SYNC sheet_team_leader_staff: group=%s', group_id)


def delete_sheet_shift_records(queryset):
    ids = list(queryset.values_list('shift_id', flat=True))
    EventShift.objects.filter(pk__in=ids).delete()
    logger.info('DELETE sheet_shifts: shifts=%s', ids)


def delete_sheet_position_records(queryset):
    ids = list(queryset.values_list('event_id', flat=True))
    Event.objects.filter(pk__in=ids).delete()
    logger.info('DELETE sheet_positions: events=%s', ids)


def delete_empty_sheet_days(queryset):
    count, _ = queryset.delete()
    logger.info('DELETE sheet_position_days: count=%s', count)


def delete_unused_sheet_directions(group, keep_keys):
    unused = EventDirection.objects.filter(event_group=group, positions__isnull=True).exclude(source_key__in=keep_keys)
    staff = list(EventStaff.objects.filter(sheet_sources__direction__in=unused).distinct())
    unused.delete()
    for assignment in staff:
        if not assignment.sheet_sources.exists():
            assignment.delete()
    logger.info('DELETE unused_sheet_directions: group=%s', group.pk)


def consolidate_sheet_directions(group, plan):
    positions = SheetPosition.objects.filter(event__event_group=group)
    if positions.filter(event__applications__isnull=False).exists() or positions.filter(event__shifts__participations__isnull=False).exists():
        raise ValidationError('У прежних позиций есть заявки или явка. Автоматическое объединение остановлено, данные сохранены.')
    for source in plan['directions']:
        rows = list(positions.filter(direction__source_key=source['id']).select_related('event', 'direction'))
        if not rows:
            continue
        keeper = rows[0]
        old_event_ids = [row.event_id for row in rows]
        shift_keys = [s['id'] for day in source['positions'][0]['days'] for s in day['shifts']]
        kept = list(SheetShift.objects.filter(position_day__position__in=rows, source_key__in=shift_keys).select_related('shift'))
        for staff in EventStaff.objects.filter(event_id__in=old_event_ids, sheet_sources__isnull=True):
            EventStaff.objects.get_or_create(event_id=keeper.event_id, user_id=staff.user_id, staff_role=staff.staff_role)
        for shift in kept:
            day, _ = SheetPositionDay.objects.get_or_create(position=keeper, day=shift.shift.day)
            EventShift.objects.filter(pk=shift.shift_id).update(event_id=keeper.event_id)
            shift.position_day = day
            shift.save(update_fields=['position_day'])
        extra = SheetShift.objects.filter(position_day__position__in=rows).exclude(source_key__in=shift_keys)
        delete_sheet_shift_records(extra)
        for model in (SheetTeamLeader, ZoneResponsible):
            model.objects.filter(position__in=rows).update(position=None)
        Event.objects.filter(pk__in=old_event_ids).exclude(pk=keeper.event_id).delete()
        keeper.source_key, keeper.sort_order = source['id'], 0
        keeper.save(update_fields=['source_key', 'sort_order'])
        Event.objects.filter(pk=keeper.event_id).update(title=source['name'])
    logger.info('CONSOLIDATE FaP directions: group=%s', group.pk)


def create_event_function(group, name, operator=None):
    """Функция, добавленная в мероприятие вручную (та же таблица, что блоки ФиП)."""
    order = EventDirection.objects.filter(event_group=group).count()
    obj = EventDirection.objects.create(event_group=group, name=name[:500], sort_order=order)
    logger.info('INSERT event_directions manual: direction=%s group=%s by=%s', obj.pk, group.pk, actor(operator))
    return obj
