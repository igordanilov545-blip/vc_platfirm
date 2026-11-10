"""Тонкий CRUD поэтапной миграции старых баз, версий ФиП, пула позиций и
расхождений анкет. Бизнес-правила — в blog/services/legacy_migration.py и
profile_conflicts.py; здесь только запись и аудит в канал vc.db."""
from django.utils import timezone

from blog.models import (
    Application, ApplicationShiftDecision, EventShift, EventStaff, FapDocument, LegacyBase,
    LegacyBaseColumn, LegacyBasePerson, LegacyLoadedCell, LegacyValueMapping, Participation,
    PositionTemplate, ProfileConflict,
)
from ._base import logger, actor


# --- Пул позиций --------------------------------------------------------------

def position_templates_qs():
    return PositionTemplate.objects.all()


def ensure_position_template(category, name, operator=None):
    obj, created = PositionTemplate.objects.get_or_create(category=category, name=name[:255])
    if created:
        logger.info('INSERT position_templates: template=%s category=%s by=%s', obj.pk, category.pk, actor(operator))
    return obj


def delete_position_template(template, operator):
    logger.info('DELETE position_templates: template=%s by=%s', template.pk, actor(operator))
    template.delete()


# --- Базы ---------------------------------------------------------------------

def legacy_bases_qs():
    return LegacyBase.objects.all()


def legacy_base_columns_qs():
    return LegacyBaseColumn.objects.all()


def legacy_base_people_qs():
    return LegacyBasePerson.objects.all()


def create_legacy_base(*, year, file_name, content, content_hash, parsed, operator):
    base = LegacyBase.objects.create(year=year, file_name=file_name[:255], content=content,
                                     content_hash=content_hash, parsed=parsed, uploaded_by=operator)
    logger.info('INSERT legacy_bases: base=%s year=%s rows=%s by=%s', base.pk, year, len(parsed.get('rows', [])), actor(operator))
    return base


def create_legacy_base_column(base, *, index, header, title_hint, day, value_counts):
    return LegacyBaseColumn.objects.create(base=base, index=index, header=header, title_hint=title_hint[:255],
                                           day=day, value_counts=value_counts)


def save_legacy_column(column, operator, **fields):
    for name, value in fields.items():
        setattr(column, name, value)
    column.save(update_fields=list(fields))
    logger.info('UPDATE legacy_base_columns: column=%s fields=%s by=%s', column.pk, sorted(fields), actor(operator))
    return column


def mark_base_people_loaded(base, operator):
    base.people_loaded_at = timezone.now()
    base.save(update_fields=['people_loaded_at'])
    logger.info('UPDATE legacy_bases people loaded: base=%s by=%s', base.pk, actor(operator))


def record_legacy_base_person(base, row_number, user):
    obj, created = LegacyBasePerson.objects.get_or_create(base=base, row_number=row_number, defaults={'user': user})
    if created:
        logger.info('INSERT legacy_base_people: base=%s row=%s user=%s', base.pk, row_number, user.pk)
    return obj


# --- ФиП ----------------------------------------------------------------------

def fap_documents_qs():
    return FapDocument.objects.all()


def create_fap_document(group, *, file_name, content, content_hash, operator):
    last = FapDocument.objects.filter(event_group=group).order_by('-version').first()
    document = FapDocument.objects.create(event_group=group, version=(last.version + 1) if last else 1,
                                          file_name=file_name[:255], content=content, content_hash=content_hash,
                                          uploaded_by=operator)
    logger.info('INSERT fap_documents: document=%s group=%s version=%s by=%s', document.pk, group.pk, document.version, actor(operator))
    return document


def mark_fap_applied(document, warnings, operator):
    document.applied_at = timezone.now()
    document.warnings = list(warnings)
    document.save(update_fields=['applied_at', 'warnings'])
    logger.info('UPDATE fap_documents applied: document=%s by=%s', document.pk, actor(operator))


# --- Сопоставление значений --------------------------------------------------

def legacy_value_mappings_qs():
    return LegacyValueMapping.objects.all()


def save_value_mapping(group, value_key, raw_value, *, position, role, skip, operator):
    existing = LegacyValueMapping.objects.filter(event_group=group, value_key=value_key).first()
    if existing and existing.position_id == (position.pk if position else None) and existing.role == role and existing.skip == skip:
        # Без изменений updated_at не трогаем: иначе загруженная колонка ложно «изменена».
        return existing
    obj, created = LegacyValueMapping.objects.update_or_create(
        event_group=group, value_key=value_key,
        defaults={'raw_value': raw_value[:500], 'position': position, 'role': role, 'skip': skip})
    logger.info('%s legacy_value_mappings: mapping=%s group=%s position=%s role=%s skip=%s by=%s',
                'INSERT' if created else 'UPDATE', obj.pk, group.pk, position.pk if position else None, role, skip, actor(operator))
    return obj


# --- Загруженные ячейки ------------------------------------------------------

def legacy_loaded_cells_qs():
    return LegacyLoadedCell.objects.all()


def record_loaded_cell(column, user, value_key, *, position, shift, application, participation, staff, operator):
    obj, created = LegacyLoadedCell.objects.update_or_create(column=column, user=user, defaults={
        'value_key': value_key, 'position': position, 'shift': shift, 'application': application,
        'participation': participation, 'staff': staff})
    logger.info('%s legacy_loaded_cells: cell=%s column=%s user=%s by=%s',
                'INSERT' if created else 'UPDATE', obj.pk, column.pk, user.pk, actor(operator))
    return obj


def delete_loaded_cell(cell, operator):
    logger.info('DELETE legacy_loaded_cells: cell=%s column=%s user=%s by=%s', cell.pk, cell.column_id, cell.user_id, actor(operator))
    cell.delete()


def set_participation_hours(participation, hours, operator):
    participation.hours = hours
    participation.save(update_fields=['hours'])
    logger.info('UPDATE participations hours via migration: participation=%s hours=%s by=%s', participation.pk, hours, actor(operator))


def delete_legacy_participation(participation, operator):
    logger.info('DELETE participations via migration: participation=%s user=%s by=%s', participation.pk, participation.user_id, actor(operator))
    participation.delete()


def unlink_legacy_application_shift(application, shift, operator):
    """Снять смену с заявки миграции; пустую заявку удалить целиком."""
    ApplicationShiftDecision.objects.filter(application=application, shift=shift).delete()
    application.selected_shifts.remove(shift)
    logger.info('UNLINK applications via migration: application=%s shift=%s by=%s', application.pk, shift.pk, actor(operator))
    if not application.selected_shifts.exists():
        logger.info('DELETE applications via migration: application=%s by=%s', application.pk, actor(operator))
        application.delete()


def ensure_event_team_lead(event, user, operator):
    staff, created = EventStaff.objects.get_or_create(event=event, user=user, staff_role='team_lead')
    if created:
        logger.info('INSERT event_staff via migration: staff=%s event=%s user=%s by=%s', staff.pk, event.pk, user.pk, actor(operator))
    return staff


def delete_event_staff(staff, operator):
    logger.info('DELETE event_staff via migration: staff=%s event=%s user=%s by=%s', staff.pk, staff.event_id, staff.user_id, actor(operator))
    staff.delete()


def create_unknown_time_shift(event, day, at, operator):
    """Смена позиции без ФиП: время неизвестно (границы равны), набор закрыт."""
    shift = EventShift.objects.create(event=event, day=day, start_time=at, end_time=at, recruit_status='closed', volunteer_needed=0)
    logger.info('INSERT event_shifts via migration: shift=%s event=%s by=%s', shift.pk, event.pk, actor(operator))
    return shift


# --- Анкеты ------------------------------------------------------------------

def profile_conflicts_qs():
    return ProfileConflict.objects.all()


def create_profile_conflict(user, field, current_value, proposed_value, source):
    obj, created = ProfileConflict.objects.get_or_create(
        user=user, field=field, proposed_value=proposed_value, resolved_at__isnull=True,
        defaults={'current_value': current_value, 'source': source[:255]})
    if created:
        logger.info('INSERT profile_conflicts: conflict=%s user=%s field=%s', obj.pk, user.pk, field)
    return obj


def resolve_profile_conflict(conflict, chosen_value):
    conflict.resolved_at = timezone.now()
    conflict.chosen_value = chosen_value
    conflict.save(update_fields=['resolved_at', 'chosen_value'])
    logger.info('UPDATE profile_conflicts resolved: conflict=%s user=%s field=%s', conflict.pk, conflict.user_id, conflict.field)


def update_user_profile_fields(user, fields, operator, reason):
    for name, value in fields.items():
        setattr(user, name, value)
    user.save(update_fields=list(fields))
    logger.info('UPDATE users via %s: user=%s fields=%s by=%s', reason, user.pk, sorted(fields), actor(operator))
    return user
