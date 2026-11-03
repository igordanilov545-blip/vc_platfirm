"""Тонкий CRUD загрузки старой базы; все изменения аудируются."""
from blog.models import EventGroup, Event, EventShift, LegacyImportIdentity, LegacyImportShift, Application, ApplicationShiftDecision, UserComment, Participation
from ._base import logger, actor


def legacy_identities_qs():
    return LegacyImportIdentity.objects.all()


def legacy_shifts_qs():
    return LegacyImportShift.objects.all()


def create_legacy_identity(key, user, reported_age, operator):
    row, created = LegacyImportIdentity.objects.get_or_create(key=key, defaults={'user': user, 'reported_age': reported_age})
    if created:
        logger.info('INSERT legacy_import_identities: user=%s by=%s', user.pk, actor(operator))
    return row


def complete_legacy_user(user, fields, operator):
    for name, value in fields.items():
        setattr(user, name, value)
    user.save(update_fields=list(fields))
    logger.info('UPDATE new legacy user: user=%s fields=%s by=%s', user.pk, sorted(fields), actor(operator))


def create_legacy_group(title, operator):
    group = EventGroup.objects.create(title=title)
    group.managers.add(operator)
    logger.info('INSERT event_groups via legacy: group=%s by=%s', group.pk, actor(operator))
    return group


def create_legacy_position(group, title, operator):
    event = Event.objects.create(event_group=group, title=title, event_status='passed')
    logger.info('INSERT events via legacy: event=%s group=%s by=%s', event.pk, group.pk, actor(operator))
    return event


def create_legacy_shift(event, day, at, source_key, header, operator):
    shift = EventShift.objects.create(event=event, day=day, start_time=at, end_time=at, recruit_status='closed', volunteer_needed=0)
    LegacyImportShift.objects.create(key=source_key, shift=shift, source_header=header)
    logger.info('INSERT event_shifts via legacy: shift=%s event=%s by=%s', shift.pk, event.pk, actor(operator))
    return shift


def ensure_legacy_application(user, event, shift, description, operator):
    app = Application.objects.filter(user=user, event=event).order_by('-pk').first()
    created = app is None
    if created:
        app = Application.objects.create(user=user, event=event, **{
            'first_name': user.first_name or '', 'last_name': user.last_name or '', 'telegram_username': user.telegram_username,
            'phone': user.phone, 'status': 'approved', 'functions': description, 'assigned_by': operator,
        })
    if created:
        logger.info('INSERT applications via legacy: application=%s user=%s event=%s by=%s', app.pk, user.pk, event.pk, actor(operator))
    if not app.selected_shifts.filter(pk=shift.pk).exists():
        app.selected_shifts.add(shift)
        logger.info('LINK applications via legacy: application=%s shift=%s by=%s', app.pk, shift.pk, actor(operator))
    return app


def ensure_legacy_comment(user, source, text, operator):
    row, created = UserComment.objects.get_or_create(target_user=user, source=source, text=text, defaults={'author': operator})
    if created:
        logger.info('INSERT user_comments via legacy: comment=%s user=%s source=%s by=%s', row.pk, user.pk, source, actor(operator))
    return row


def ensure_legacy_participation(user, shift, operator):
    row, created = Participation.objects.get_or_create(user=user, event_day=shift, defaults={'status': 'attended', 'hours': 0, 'full_shift': False})
    if created:
        logger.info('INSERT participations via legacy: participation=%s user=%s shift=%s by=%s', row.pk, user.pk, shift.pk, actor(operator))
    return row, created


def ensure_legacy_decision(application, shift, operator):
    row, created = ApplicationShiftDecision.objects.get_or_create(application=application, shift=shift, defaults={'status': 'approved', 'assigned_by': operator})
    if created:
        logger.info('INSERT application_shift_decisions via legacy: decision=%s shift=%s by=%s', row.pk, shift.pk, actor(operator))
    return row
