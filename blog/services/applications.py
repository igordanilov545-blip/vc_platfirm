"""Обработка заявок: матчинг с профилем, approve/reject, авто-создание participations."""
from django.db import transaction
from django.utils import timezone

from blog.models import User, Application, Participation


def find_matching_user(telegram_username=None, phone=None, first_name=None, last_name=None):
    """Матчинг заявки с профилем (db.md, бизнес-правило 5):
    (1) telegram_username -> (2) phone -> (3) ФИО."""
    if telegram_username:
        user = User.objects.filter(telegram_username__iexact=telegram_username.lstrip('@')).first()
        if user:
            return user
    if phone:
        user = User.objects.filter(phone=phone).first()
        if user:
            return user
    if first_name and last_name:
        user = User.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name).first()
        if user:
            return user
    return None


@transaction.atomic
def process_application(application: Application, new_status: str, processed_by: User):
    """approve/reject заявки. При approve — авто-создание participations на все дни (правило 4)."""
    application.status = new_status
    application.assigned_at = timezone.now()
    application.assigned_by = processed_by
    application.save(update_fields=['status', 'assigned_at', 'assigned_by'])

    if new_status == 'approved' and application.user:
        for day in application.event.days.all():
            Participation.objects.get_or_create(
                user=application.user,
                event_day=day,
                defaults={'status': 'attended', 'hours': 0},
            )

    from blog.services.stats import recruit_status_for_event
    application.event.recruit_status = recruit_status_for_event(application.event)
    application.event.save(update_fields=['recruit_status'])

    from blog.services.notifications import notify_application_status
    notify_application_status(application)

    return application
