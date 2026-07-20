"""Доступ к данным: заявки, привязка смен, участия (явка), запросы фидбека.

Доменный инвариант (coding-principles §6): решение по заявке — на КАЖДУЮ смену
(`ApplicationShiftDecision`); `Application.status` — производный агрегат. Здесь только
CRUD; пересчёт агрегатов и ACL — в `blog/services/applications.py`.
"""
from typing import Optional, List

from django.db.models import Q
from django.utils import timezone

from blog.models import Application, EventShift, Event, User, Participation
from ._base import logger, actor


def create_application(
    event: Event,
    first_name: str,
    last_name: str,
    user: Optional[User] = None,
    middle_name: Optional[str] = None,
    telegram_username: Optional[str] = None,
    phone: Optional[str] = None,
    functions: Optional[str] = None,
    shifts: Optional[str] = None,
    role_in_event: Optional[str] = None,
    user_status: Optional[str] = None,
    submitted_at=None,
    status: str = 'new',
    auto_reject_reason: Optional[str] = None,
) -> Application:
    application = Application.objects.create(
        event=event,
        user=user,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        telegram_username=telegram_username,
        phone=phone,
        functions=functions,
        shifts=shifts,
        role_in_event=role_in_event,
        user_status=user_status,
        submitted_at=submitted_at or timezone.now(),
        status=status,
        auto_reject_reason=auto_reject_reason,
    )
    logger.info(
        'INSERT applications: application=%s event=%s status=%s applicant=%s',
        application.id, event.id, status, actor(user) if user else 'user=?',
    )
    return application


def set_application_shifts(application: Application, shifts: List[EventShift]) -> Application:
    """Привязывает заявку к выбранным сменам меро (M2M `selected_shifts`, чипы на
    веб-форме — тот же паттерн для бота) + человекочитаемая сводка в `Application.shifts`
    (обратная совместимость с Excel-импортом, где выбора смен нет)."""
    application.selected_shifts.set(shifts)
    if shifts:
        application.shifts = ', '.join(s.day.isoformat() for s in sorted(shifts, key=lambda s: s.day))
    else:
        application.shifts = 'Все смены'
    application.save(update_fields=['shifts'])
    return application


def get_applications(
    status_filter: Optional[str] = None,
    applicant_name: Optional[str] = None,
    event_id: Optional[int] = None,
) -> List[Application]:
    qs = Application.objects.select_related('event', 'user').order_by('-created_at')
    if status_filter:
        qs = qs.filter(status=status_filter)
    if applicant_name:
        qs = qs.filter(first_name__icontains=applicant_name) | qs.filter(last_name__icontains=applicant_name)
    if event_id:
        qs = qs.filter(event_id=event_id)
    return list(qs)


def count_applications(status_filter: Optional[str] = None) -> int:
    """Число заявок (опц. по статусу) — для сводок дашборда. Вынесено в контроллер,
    чтобы веб не ходил в ORM напрямую (coding-principles §1)."""
    qs = Application.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)
    return qs.count()


def count_events_with_open_recruitment() -> int:
    """Число мероприятий, у которых хотя бы одна смена с открытым набором."""
    return Event.objects.filter(shifts__recruit_status='open').distinct().count()


def get_user_active_applications(user_id: int) -> List[Application]:
    """Активные заявки волонтёра — только new/approved (tg-bot.md §4.4), и только на
    мероприятия, которые ещё идут или предстоят (`compute_status` in upcoming/ongoing).
    Заявки на уже прошедшие/завершённые меро не показываются — волонтёру нечего с ними
    делать, они провисели бы в списке бесконечно."""
    apps = (
        Application.objects.filter(user_id=user_id, status__in=['new', 'approved'])
        .select_related('event')
        .prefetch_related('event__shifts')
        .order_by('-created_at')
    )
    return [a for a in apps if a.event.compute_status() in ('upcoming', 'ongoing')]


def get_user_application_for_event(user_id: int, event_id: int) -> Optional[Application]:
    # select_related('event') обязателен: возвращённый объект используется в async-хендлере
    # бота (cb_apply), где обращение к application.event.* без предзагрузки роняет
    # SynchronousOnlyOperation.
    return Application.objects.select_related('event').filter(
        user_id=user_id, event_id=event_id, status__in=['new', 'approved']
    ).first()


def update_application_status(application: Application, status: str, assigned_by: Optional[User] = None) -> Application:
    application.status = status
    application.assigned_at = timezone.now()
    if assigned_by:
        application.assigned_by = assigned_by
    application.save(update_fields=['status', 'assigned_at', 'assigned_by'])
    logger.info(
        'UPDATE applications: application=%s status=%s by=%s subject=%s',
        application.id, status, actor(assigned_by),
        actor(application.user) if application.user_id else 'user=?',
    )
    return application


# --- PARTICIPATIONS (явка) ---
def create_participation(
    user: User,
    event_day: EventShift,
    status: str = 'attended',
    hours: int = 0,
    full_shift: bool = False,
) -> Participation:
    return Participation.objects.create(
        user=user, event_day=event_day, status=status, hours=hours, full_shift=full_shift,
    )


def get_participations(
    status_filter: Optional[str] = None,
    volunteer_name: Optional[str] = None,
    event_id: Optional[int] = None,
) -> List[Participation]:
    qs = Participation.objects.select_related('user', 'event_day')
    if status_filter:
        qs = qs.filter(status=status_filter)
    if volunteer_name:
        qs = qs.filter(Q(user__first_name__icontains=volunteer_name) | Q(user__last_name__icontains=volunteer_name))
    if event_id:
        qs = qs.filter(event_day__event_id=event_id)
    return list(qs)


def get_participations_pending_feedback(before) -> List[Participation]:
    """Присутствовавшие участники завершённых дней меро старше `before`, кому ещё
    не отправляли запрос "оцени мероприятие" (tg-bot.md §4.6)."""
    return list(
        Participation.objects.filter(
            status='attended',
            feedback_requested_at__isnull=True,
            event_day__end_time__lte=before,
        ).select_related('user', 'event_day__event')
    )


def mark_feedback_requested(participation: Participation) -> None:
    participation.feedback_requested_at = timezone.now()
    participation.save(update_fields=['feedback_requested_at'])


def update_participation_status(
    participation: Participation,
    status: str,
    hours: Optional[int] = None,
    full_shift: Optional[bool] = None,
    actor_user: Optional[User] = None,
) -> Participation:
    """`actor_user` — кто проставляет явку (тим-лидер/менеджер), для аудита в db.log.
    Субъект (чью явку меняем) берётся из самого participation."""
    update_fields = ['status']
    participation.status = status
    if hours is not None:
        participation.hours = hours
        update_fields.append('hours')
    if full_shift is not None:
        participation.full_shift = full_shift
        update_fields.append('full_shift')
    participation.save(update_fields=update_fields)
    logger.info(
        'UPDATE participations: participation=%s status=%s hours=%s by=%s subject=%s',
        participation.id, status, hours, actor(actor_user),
        actor(participation.user) if participation.user_id else 'user=?',
    )
    return participation


def mark_dobro_ru_logged(participation: Participation, logged_by: Optional[User] = None) -> Participation:
    """Ручная простановка часов на Добро.ру по участию волонтёра (db.md, правило 7e)."""
    participation.dobro_ru_logged = True
    participation.dobro_ru_logged_at = timezone.now()
    participation.dobro_ru_logged_by = logged_by
    participation.save(update_fields=['dobro_ru_logged', 'dobro_ru_logged_at', 'dobro_ru_logged_by'])
    return participation
