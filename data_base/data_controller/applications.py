"""Доступ к данным: заявки, привязка смен, участия (явка), запросы фидбека.

Доменный инвариант (coding-principles §6): решение по заявке — на КАЖДУЮ смену
(`ApplicationShiftDecision`); `Application.status` — производный агрегат. Здесь только
CRUD; пересчёт агрегатов и ACL — в `blog/services/applications.py`.
"""
from typing import Optional, List

from django.db.models import Q
from django.utils import timezone

from blog.models import (
    Application, ApplicationChangeLog, ApplicationShiftDecision, EventShift, Event, User, Participation,
)
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


def get_application_by_id(application_id: int, *, with_event: bool = False,
                          with_user: bool = False,
                          prefetch_shifts: bool = False) -> Optional[Application]:
    """Заявка по id или None. `with_event=True` — с предзагрузкой event (обязательно,
    если объект уходит в async-хендлер бота: обращение к application.event.* без
    предзагрузки роняет SynchronousOnlyOperation). `with_user=True` — то же для
    application.user. `prefetch_shifts=True` — подтянуть выбранные смены заявки и
    смены меро (для отрисовки кнопок по сменам в боте)."""
    qs = Application.objects.all()
    related = []
    if with_event or prefetch_shifts:
        related.append('event')
    if with_user:
        related.append('user')
    if related:
        qs = qs.select_related(*related)
    if prefetch_shifts:
        qs = qs.prefetch_related('selected_shifts', 'event__shifts')
    return qs.filter(pk=application_id).first()


def get_own_application(user_id: int, application_id: int) -> Optional[Application]:
    """Заявка по id, только если принадлежит указанному пользователю (защита от подделки
    callback_data в боте). select_related('event') — для async-хендлеров."""
    return Application.objects.select_related('event').filter(
        pk=application_id, user_id=user_id
    ).first()


def get_shift_by_id(shift_id: int, event_id: Optional[int] = None) -> Optional[EventShift]:
    """Смена по id (опц. в рамках конкретного меро) или None."""
    qs = EventShift.objects.filter(pk=shift_id)
    if event_id is not None:
        qs = qs.filter(event_id=event_id)
    return qs.first()


def get_shifts_by_ids(shift_ids, event: Optional[Event] = None) -> List[EventShift]:
    """Список смен по набору id (опц. в рамках меро)."""
    qs = EventShift.objects.filter(pk__in=shift_ids)
    if event is not None:
        qs = qs.filter(event=event)
    return list(qs)


def get_participation_by_id(participation_id: int) -> Optional[Participation]:
    return Participation.objects.filter(pk=participation_id).first()


def create_application_change_log(event: Event, application: Application, kind: str, text: str) -> ApplicationChangeLog:
    """Запись в ленту изменений заявок меро (повторный импорт/правка через бота)."""
    entry = ApplicationChangeLog.objects.create(
        event=event, application=application, kind=kind, text=text,
    )
    logger.info('INSERT application_change_logs: event=%s application=%s kind=%s',
                event.id, application.id if application else None, kind)
    return entry


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


# --- SHIFT DECISIONS ---
def ensure_shift_decision(application: Application, shift, default_status: str = 'new'):
    """Гарантирует наличие ApplicationShiftDecision для (заявка, смена). Возвращает
    (decision, created). Статус по умолчанию — общий статус заявки."""
    return ApplicationShiftDecision.objects.get_or_create(
        application=application, shift=shift, defaults={'status': default_status},
    )


def set_shift_decision(application: Application, shift, status: str, assigned_by: Optional[User] = None):
    """Проставляет решение по (заявка, смена) — update_or_create со статусом и меткой
    обработки. Возвращает (decision, created)."""
    return ApplicationShiftDecision.objects.update_or_create(
        application=application, shift=shift,
        defaults={'status': status, 'assigned_at': timezone.now(), 'assigned_by': assigned_by},
    )


def find_matching_user(telegram_username=None, phone=None, first_name=None, last_name=None) -> Optional[User]:
    """Матчинг заявки с профилем (db.md, правило 5): telegram_username → phone → ФИО.
    Возвращает найденного пользователя или None. Приоритет по порядку аргументов."""
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


# --- PARTICIPATIONS (явка) ---
def get_or_create_participation(user: User, event_day: EventShift, defaults: Optional[dict] = None):
    """get_or_create участия (user, смена). `defaults` — начальные поля при создании
    (status/hours/full_shift). Возвращает (participation, created)."""
    return Participation.objects.get_or_create(
        user=user, event_day=event_day, defaults=defaults or {},
    )


def delete_participations(user: User, event_days) -> int:
    """Удаляет участия пользователя по одной смене или списку смен. Возвращает число
    удалённых. `event_days` — EventShift или итерируемое смен."""
    from collections.abc import Iterable
    qs = Participation.objects.filter(user=user)
    if isinstance(event_days, Iterable) and not hasattr(event_days, 'pk'):
        qs = qs.filter(event_day__in=list(event_days))
    else:
        qs = qs.filter(event_day=event_days)
    deleted, _ = qs.delete()
    return deleted


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
