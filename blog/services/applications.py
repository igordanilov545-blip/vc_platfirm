"""Обработка заявок: матчинг с профилем, approve/reject, авто-создание participations."""
import datetime

from django.db import transaction
from django.utils import timezone

from data_base import data_controller as dc
from blog.models import User, Application, Event  # только для аннотаций типов
from blog.logging_utils import get_web_logger, actor

logger = get_web_logger(__name__)


def application_shifts(application: Application):
    """Смены заявки: выбранные чипами, либо все смены меро (Excel-импорт/бот)."""
    return list(application.selected_shifts.all()) or list(application.event.shifts.all())


def ensure_shift_decisions(application: Application):
    """Гарантирует, что у заявки есть ApplicationShiftDecision на каждую её смену
    (создаёт недостающие со статусом 'new') — вызывается лениво при первом обращении
    к разбивке по сменам, чтобы не плодить миграции данных при каждом новом поле."""
    shifts = application_shifts(application)
    existing_shift_ids = set(application.shift_decisions.values_list('shift_id', flat=True))
    for shift in shifts:
        if shift.id not in existing_shift_ids:
            dc.ensure_shift_decision(application, shift, default_status=application.status)
    return application.shift_decisions.select_related('shift').all()


def _recompute_application_status(application: Application):
    """Статус заявки в целом — производный от решений по сменам: 'new', пока хоть
    одна смена не решена; 'approved', если все решённые смены одобрены; иначе
    'rejected'. Нужен только для сводных списков (напр. „Необработанные заявки“),
    реальный источник истины — ApplicationShiftDecision по каждой смене."""
    statuses = set(application.shift_decisions.values_list('status', flat=True))
    if not statuses or 'new' in statuses:
        new_status = 'new'
    elif statuses == {'approved'}:
        new_status = 'approved'
    else:
        new_status = 'rejected'
    if application.status != new_status:
        application.status = new_status
        application.save(update_fields=['status'])


def find_matching_user(telegram_username=None, phone=None, first_name=None, last_name=None):
    """Матчинг заявки с профилем (db.md, бизнес-правило 5):
    (1) telegram_username -> (2) phone -> (3) ФИО. Доступ к данным — через контроллер."""
    return dc.find_matching_user(
        telegram_username=telegram_username, phone=phone,
        first_name=first_name, last_name=last_name,
    )


@transaction.atomic
def process_application(application: Application, new_status: str, processed_by: User):
    """approve/reject заявки. При approve — авто-создание participations по сменам,
    выбранным в заявке (`selected_shifts`, чипы на веб-форме — правило 4). Если смены
    не выбраны (заявка из Excel-импорта, там выбора нет) — на все смены мероприятия."""
    application.status = new_status
    application.assigned_at = timezone.now()
    application.assigned_by = processed_by
    application.save(update_fields=['status', 'assigned_at', 'assigned_by'])
    logger.info(
        'Заявка обработана целиком: application=%s event=%s status=%s by=%s subject=%s',
        application.id, application.event_id, new_status,
        actor(processed_by), actor(application.user) if application.user_id else 'user=?',
    )

    shifts = list(application.selected_shifts.all() or application.event.shifts.all())
    if new_status == 'approved' and application.user:
        for shift in shifts:
            # Одобрение даёт место на смене, но не подтверждает физическое присутствие.
            dc.get_or_create_participation(
                application.user, shift,
                defaults={'status': 'pending', 'hours': 0, 'full_shift': False},
            )
        # Одобрение создаёт нейтральные участия без часов; агрегаты синхронизируем
        # и здесь, и после фактической отметки, не выдавая достижения за одно одобрение.
        from blog.services.stats import recalc_user_aggregates
        recalc_user_aggregates(application.user)
    elif new_status == 'rejected' and application.user:
        # Отклонение/резерв заявки целиком → убираем участия по её сменам, чтобы
        # отклонённый волонтёр исчез из таблицы явки (показываем только одобренных).
        deleted = dc.delete_participations(application.user, shifts)
        if deleted:
            from blog.services.stats import recalc_user_aggregates
            recalc_user_aggregates(application.user)

    # Синхронизируем решения по сменам (ApplicationShiftDecision) с общим статусом
    # заявки: process_application меняет статус заявки целиком, поэтому и все её
    # per-shift решения должны прийти в тот же статус (иначе таблица набора по сменам
    # разойдётся с фактическим решением по заявке).
    for shift in shifts:
        dc.set_shift_decision(application, shift, new_status, assigned_by=processed_by)

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


@transaction.atomic
def process_shift_decision(application: Application, shift, new_status: str, processed_by: User):
    """approve/reject заявки ТОЛЬКО на конкретную смену — остальные смены той же
    заявки (если она подана на несколько) не затрагиваются. Источник истины —
    ApplicationShiftDecision; Application.status пересчитывается как производный
    агрегат для сводных списков (см. _recompute_application_status)."""
    ensure_shift_decisions(application)
    decision, _ = dc.set_shift_decision(application, shift, new_status, assigned_by=processed_by)
    logger.info(
        'Заявка обработана по смене: application=%s shift=%s status=%s by=%s subject=%s',
        application.id, shift.id, new_status, actor(processed_by),
        actor(application.user) if application.user_id else 'user=?',
    )

    if application.assigned_at is None:
        application.assigned_at = timezone.now()
        application.assigned_by = processed_by
        application.save(update_fields=['assigned_at', 'assigned_by'])

    if application.user:
        if new_status == 'approved':
            dc.get_or_create_participation(
                application.user, shift,
                defaults={'status': 'pending', 'hours': 0, 'full_shift': False},
            )
            from blog.services.stats import recalc_user_aggregates
            recalc_user_aggregates(application.user)
        elif new_status == 'rejected':
            # Отклонённая (уведённая в резерв) заявка на смену → участие удаляем: волонтёр
            # не должен оставаться в таблице явки этой смены (показываем только одобренных).
            # Другие смены той же заявки не затрагиваются — участие привязано к смене.
            deleted = dc.delete_participations(application.user, shift)
            if deleted:
                from blog.services.stats import recalc_user_aggregates
                recalc_user_aggregates(application.user)

    _recompute_application_status(application)

    from blog.services.stats import recruit_status_for_shift
    if shift.recruit_status == 'open' and recruit_status_for_shift(shift) == 'closed':
        shift.recruit_status = 'closed'
        shift.save(update_fields=['recruit_status'])

    from blog.services.notifications import notify_shift_decision_status
    notify_shift_decision_status(application, shift, new_status)

    return decision


def application_earliest_shift(application: Application):
    """Ближайшая по времени смена заявки (выбранные чипами, либо все смены меро,
    если выбор не делался — заявки из Excel-импорта/бота)."""
    shifts = application.selected_shifts.all() or application.event.shifts.all()
    starts = [s.start_time for s in shifts]
    return min(starts) if starts else None


def can_cancel_application(application: Application) -> tuple:
    """Можно ли отменить заявку самим волонтёром (db.md/tg-bot.md): только пока статус
    активен (`new`/`approved`) и до ближайшей смены осталось больше `const.late_cancel_hours`.

    Возвращает (можно: bool, причина отказа: str|None, late_cancel_hours: float).
    """
    from data_base.data_controller import get_const

    late_cancel_hours = get_const('late_cancel_hours', default=24)
    if application.status not in ('new', 'approved'):
        return False, 'inactive', late_cancel_hours

    earliest_start = application_earliest_shift(application)
    too_late = bool(
        earliest_start and earliest_start - timezone.now() < datetime.timedelta(hours=late_cancel_hours)
    )
    if too_late:
        return False, 'too_late', late_cancel_hours
    return True, None, late_cancel_hours


@transaction.atomic
def cancel_application(application: Application, reason: str) -> Application:
    """Отмена заявки самим волонтёром — причина обязательна. Вызывающий обязан
    предварительно проверить `can_cancel_application`. Событие попадает в ленту
    изменений заявок мероприятия (ApplicationChangeLog), чтобы тим-лидер увидел
    отказ на странице меро."""
    application.status = 'cancelled'
    application.cancelled_at = timezone.now()
    application.cancel_reason = reason
    application.save(update_fields=['status', 'cancelled_at', 'cancel_reason'])
    logger.info(
        'Заявка отменена волонтёром: application=%s event=%s by=%s',
        application.id, application.event_id,
        actor(application.user) if application.user_id else 'user=?',
    )

    name = f'{application.first_name} {application.last_name or ""}'.strip()
    dc.create_application_change_log(
        application.event, application, 'withdrawn',
        f'{name} отказался(-ась) от участия. Причина: {reason}',
    )
    return application


@transaction.atomic
def create_manual_application(event: Event, user: User, created_by: User, shifts=None):
    """Ручное добавление заявки волонтёра менеджером/ТЛ (пайплайн как у веб-подачи/импорта:
    сразу создаётся Application со status='new'). `shifts` — список EventShift (если не
    задан, берутся все смены меро с открытым набором, как при обычной подаче).

    Дубли не плодим: если у волонтёра уже есть активная (new/approved) заявка на это
    меро — возвращаем её, не создавая вторую. Возвращает (application, created: bool)."""
    existing = dc.applications_qs().filter(
        event=event, user=user, status__in=['new', 'approved']
    ).first()
    if existing:
        return existing, False

    from blog.services.requirements import check_application_requirements
    req_check = check_application_requirements(event, user)

    application = dc.create_application(
        event=event,
        user=user,
        first_name=user.first_name or '',
        last_name=user.last_name,
        middle_name=user.middle_name,
        telegram_username=user.telegram_username,
        phone=user.phone,
        submitted_at=timezone.now(),
        status='rejected' if req_check['auto_reject'] else 'new',
        auto_reject_reason='; '.join(req_check['reasons']) if req_check['auto_reject'] else None,
    )
    # Смены заявки: выбранные, либо все смены меро с открытым набором.
    if shifts:
        application.selected_shifts.set(shifts)
        application.shifts = ', '.join(s.day.isoformat() for s in sorted(shifts, key=lambda s: s.day))
    else:
        all_shifts = list(event.shifts.filter(recruit_status='open').order_by('day'))
        application.selected_shifts.set(all_shifts)
        application.shifts = 'Все смены'
    application.save(update_fields=['shifts'])

    logger.info(
        'Заявка добавлена вручную: application=%s event=%s by=%s subject=%s%s',
        application.id, event.id, actor(created_by), actor(user),
        f" auto_reject={application.auto_reject_reason!r}" if application.auto_reject_reason else '',
    )
    from blog.services.notifications import notify_application_submitted
    notify_application_submitted(application, unknown_age=req_check['unknown_age'])
    return application, True


def create_volunteer_by_name(first_name: str, last_name: str = '', middle_name: str = '', phone: str = '', telegram_username: str = '') -> User:
    """Создаёт «служебного» волонтёра по ФИО (когда менеджер вписывает человека,
    которого ещё нет в системе). Telegram-id служебный (manual:<uuid>) — такому нельзя
    слать в Telegram, но по нему можно проставлять явку (Participation привязан к User),
    как у импортных заявок (db.md — у импортной заявки всегда есть User). Телефон/
    Telegram-username — опциональны, для последующего матчинга (find_matching_user)."""
    import uuid
    return dc.create_user(
        telegram_id=f"manual:{uuid.uuid4()}",
        first_name=(first_name or '').strip(),
        last_name=(last_name or '').strip(),
        middle_name=(middle_name or '').strip(),
        phone=(phone or '').strip() or None,
        telegram_username=(telegram_username or '').strip().lstrip('@') or None,
    )


def event_closing_checklist(event: Event) -> dict:
    """Список условий для завершения мероприятия (cjm-event-lifecycle.md, этап 8).

    Возвращает словарь с булевыми флагами по каждому условию и человекочитаемыми
    пояснениями — используется и для показа кнопки «Завершить», и на экране проверки.
    """
    today = timezone.localdate()

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
    no_unmarked_attendance = not dc.participations_qs().filter(event_day__event=event, status='pending').exists()
    no_open_entries = not dc.shift_attendance_qs().filter(shift__event=event, entered_at__isnull=False, exited_at=None).exists()

    ready = (
        event.event_status != 'finished'
        and all_days_past
        and no_pending_applications
        and no_approved_without_user
        and no_unmarked_attendance
        and no_open_entries
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
        'no_unmarked_attendance': no_unmarked_attendance,
        'no_open_entries': no_open_entries,
    }
