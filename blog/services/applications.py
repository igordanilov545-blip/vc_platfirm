"""Обработка заявок: матчинг с профилем, approve/reject, авто-создание participations."""
from django.db import transaction
from django.utils import timezone

from blog.models import User, Application, Event, Participation


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
    """approve/reject заявки. При approve — авто-создание participations по сменам,
    выбранным в заявке (`selected_shifts`, чипы на веб-форме — правило 4). Если смены
    не выбраны (заявка из Excel-импорта, там выбора нет) — на все смены мероприятия."""
    application.status = new_status
    application.assigned_at = timezone.now()
    application.assigned_by = processed_by
    application.save(update_fields=['status', 'assigned_at', 'assigned_by'])

    if new_status == 'approved' and application.user:
        shifts = application.selected_shifts.all() or application.event.shifts.all()
        for shift in shifts:
            duration_hours = max(0, round((shift.end_time - shift.start_time).total_seconds() / 3600))
            Participation.objects.get_or_create(
                user=application.user,
                event_day=shift,
                # По умолчанию считаем, что волонтёр пришёл и отработал полную смену —
                # часы сразу равны длительности смены, без ручного "перетыкивания" (см.
                # events.md: тим-лидер меняет статус только если по факту было иначе).
                defaults={'status': 'attended', 'hours': duration_hours, 'full_shift': True},
            )

    # Автоматика только ЗАКРЫВАЕТ набор на смену при достижении порога (правило 10) —
    # никогда не открывает его обратно. Открытие/закрытие вручную (кнопка «Набор закрыт»
    # на смене) не должно откатываться следующей обработкой заявки.
    from blog.services.stats import recruit_status_for_shift
    for shift in application.event.shifts.filter(recruit_status='open'):
        if recruit_status_for_shift(shift) == 'closed':
            shift.recruit_status = 'closed'
            shift.save(update_fields=['recruit_status'])

    from blog.services.notifications import notify_application_status
    notify_application_status(application)

    return application


def event_closing_checklist(event: Event) -> dict:
    """Список условий для завершения мероприятия (cjm-event-lifecycle.md, этап 8).

    Возвращает словарь с булевыми флагами по каждому условию и человекочитаемыми
    пояснениями — используется и для показа кнопки «Завершить», и на экране проверки.
    """
    today = timezone.now().date()

    shifts = list(event.shifts.all())
    all_days_past = bool(shifts) and all(s.day < today for s in shifts)

    new_applications = event.applications.filter(status='new')
    no_pending_applications = not new_applications.exists()

    # Заявки, одобренные, но не привязанные к профилю пользователя — по ним
    # невозможно проставить явку (Participation привязан к User), поэтому
    # завершение мероприятия ими тоже блокируется — их нужно либо привязать
    # к профилю (или переимпортировать), либо перевести в резерв.
    approved_without_user = event.applications.filter(status='approved', user__isnull=True)
    no_approved_without_user = not approved_without_user.exists()

    people_helped_filled = event.people_helped is not None

    ready = (
        event.event_status != 'finished'
        and all_days_past
        and no_pending_applications
        and no_approved_without_user
    )

    return {
        'ready': ready,
        'already_finished': event.event_status == 'finished',
        'all_days_past': all_days_past,
        'has_days': bool(shifts),
        'no_pending_applications': no_pending_applications,
        'pending_applications_count': new_applications.count(),
        'no_approved_without_user': no_approved_without_user,
        'approved_without_user_count': approved_without_user.count(),
        'people_helped_filled': people_helped_filled,
    }
