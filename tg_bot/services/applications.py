"""Сервисы бота: домен «applications». Часть пакета tg_bot.services (см. README.md).

Заявки и явка в боте: подача/отмена/редактирование своей заявки, оценка,
обработка заявок ТЛ/менеджером, массовая явка, ссылки на веб.

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403
from .users import get_user, is_guest


def apply_to_event(user_id: int, event_id: int, shift_ids: list = None):
    """Подача заявки из бота (tg-bot.md §4.2–4.3, bot-update.md §2.1.E). Каждый вызов —
    независимая заявка на конкретное меро; несколько заявок на разные меро подаются
    отдельными вызовами. `shift_ids` — id выбранных `EventShift` (чипы выбора смен);
    если не переданы/пусты — заявка подаётся на все открытые смены меро (старое
    поведение, совместимость с прямой подачей без выбора).
    Возвращает (application|None, код ошибки|None). При `already_applied` объект
    существующей заявки кладётся в `application`, чтобы хендлер мог сразу предложить
    посмотреть/изменить/отменить её (db.md правило 7d), не делая второй запрос."""
    close_old_connections()
    user = get_user(user_id)
    event = next((e for e in dc.get_events() if e.id == event_id), None)
    if not event:
        return None, 'not_found'
    open_shifts = list(event.shifts.filter(recruit_status='open'))
    if not open_shifts:
        return None, 'closed'
    if user.status == 'blacklisted':
        return None, 'blacklisted'
    if is_guest(user):
        return None, 'need_registration'
    existing = dc.get_user_application_for_event(user_id, event_id)
    if existing:
        return existing, 'already_applied'

    shifts = [s for s in open_shifts if s.id in shift_ids] if shift_ids else open_shifts

    # Требования меро (db.md правило 6) — та же логика, что и на веб-подаче: если
    # волонтёр не соответствует хотя бы одному, заявка сразу уходит в резерв, без
    # особого сообщения пользователю (обычное «заявка отправлена»).
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
    dc.set_application_shifts(application, shifts)
    notify_application_submitted(application, unknown_age=req_check['unknown_age'])
    logger.info(
        'Заявка подана из бота: application=%s event=%s by=%s%s',
        application.id, event_id, actor(user),
        f' auto_reject={application.auto_reject_reason!r}' if application.auto_reject_reason else '',
    )
    return application, None

def my_active_applications(user_id: int) -> list:
    """Только активные заявки волонтёра на ещё актуальные меро (new/approved,
    tg-bot.md §4.4, bot-update.md §2.2.E) — заявки на уже прошедшие мероприятия сюда
    не попадают (фильтр внутри `get_user_active_applications`). `shifts_summary` —
    какие смены заявки уже решены (✅/❌ по каждой), `post_link` — пост меро, если есть."""
    close_old_connections()
    apps = dc.get_user_active_applications(user_id)
    result = []
    for a in apps:
        shifts = list(a.selected_shifts.all())
        shifts_summary = None
        if shifts:
            decisions = {d.shift_id: d.status for d in a.shift_decisions.all()}
            parts = []
            for s in sorted(shifts, key=lambda s: s.day):
                status = decisions.get(s.id, 'new')
                icon = '✅' if status == 'approved' else ('❌' if status == 'rejected' else '⬜')
                parts.append(f'{icon} {s.day.strftime("%d.%m")}')
            shifts_summary = ' · '.join(parts)
        result.append({
            'id': a.id,
            'event_title': a.event.title,
            'status': a.status,
            'status_display': a.get_status_display(),
            'created_at': a.created_at,
            'shifts_summary': shifts_summary,
            'post_link': a.event.post_in_chanel_link or None,
        })
    return result

def get_own_application(user_id: int, application_id: int):
    """Заявка пользователя по id, только если она принадлежит ему — используется в
    хендлерах редактирования/отмены (tg-bot.md §4.3.2–4.3.3), чтобы не дать подделать
    callback_data и подействовать на чужую заявку."""
    close_old_connections()
    return dc.get_own_application(user_id, application_id)

def application_cancel_eligibility(user_id: int, application_id: int):
    """(можно_отменить, причина_отказа|None, late_cancel_hours) — обёртка над общим
    правилом `blog.services.applications.can_cancel_application` с проверкой владения."""
    from blog.services.applications import can_cancel_application
    close_old_connections()
    application = get_own_application(user_id, application_id)
    if not application:
        return False, 'not_found', None
    return can_cancel_application(application)

def cancel_own_application(user_id: int, application_id: int, reason: str):
    """Отмена своей заявки с обязательной причиной (tg-bot.md §4.3.3). Возвращает
    (application|None, код_ошибки|None). Права/срок повторно проверяются здесь —
    хендлер не должен полагаться только на состояние экрана, вызванное раньше."""
    from blog.services.applications import can_cancel_application, cancel_application
    close_old_connections()
    application = get_own_application(user_id, application_id)
    if not application:
        return None, 'not_found'
    can_cancel, reason_code, _ = can_cancel_application(application)
    if not can_cancel:
        return None, reason_code
    cancel_application(application, reason)
    return application, None

def edit_own_application(user_id: int, application_id: int, shift_ids: list):
    """Изменение смен активной заявки (bot-update.md §2.2.F, db.md правило 7d): создаёт
    НОВУЮ запись `applications` с новыми `selected_shifts` и статусом `new` — старая
    заявка остаётся в истории без изменений (дубли разрешены, см. правило 3). Плюс
    запись в `ApplicationChangeLog` (как при повторном Excel-импорте), чтобы ТЛ увидел
    изменение на странице меро. Возвращает (новая_заявка|None, код_ошибки|None)."""
    close_old_connections()
    old = get_own_application(user_id, application_id)
    if not old or old.status not in ('new', 'approved'):
        return None, 'not_found'
    user = get_user(user_id)
    shifts = dc.get_shifts_by_ids(shift_ids, event=old.event) if shift_ids else []

    from blog.services.requirements import check_application_requirements
    req_check = check_application_requirements(old.event, user)

    new_application = dc.create_application(
        event=old.event,
        user=user,
        first_name=old.first_name,
        last_name=old.last_name,
        middle_name=old.middle_name,
        telegram_username=old.telegram_username,
        phone=old.phone,
        functions=old.functions,
        role_in_event=old.role_in_event,
        submitted_at=timezone.now(),
        status='rejected' if req_check['auto_reject'] else 'new',
        auto_reject_reason='; '.join(req_check['reasons']) if req_check['auto_reject'] else None,
    )
    dc.set_application_shifts(new_application, shifts)
    notify_application_submitted(new_application, unknown_age=req_check['unknown_age'])

    name = f'{old.first_name} {old.last_name or ""}'.strip()
    dc.create_application_change_log(
        event=old.event, application=new_application, kind='changed',
        text=f'{name} изменил(а) смены заявки через бота.',
    )
    return new_application, None

def submit_feedback(user_id: int, event_id: int, rating: int, comment: str = None):
    """Оценка мероприятия после участия (tg-bot.md §4.6)."""
    close_old_connections()
    user = get_user(user_id)
    event = next((e for e in dc.get_events() if e.id == event_id), None)
    if not event:
        return None, 'not_found'
    if dc.has_feedback(user_id, event_id):
        return None, 'already_rated'
    feedback = dc.create_feedback(author=user, event=event, rating=rating, comment=comment)
    return feedback, None

def event_pending_applications(user_id: int, event_id: int):
    """Заявки на рассмотрении по конкретному меро — с проверкой контекстных прав."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.can_process_applications(user, event_id):
        return None, 'forbidden'
    apps = dc.get_applications(status_filter='new', event_id=event_id)
    return apps, None

def process_application_decision(user_id: int, application_id: int, approve: bool):
    """Одобрить/резерв заявки (tg-bot.md §5.2). Права: ТЛ — свои меро, менеджер — все."""
    close_old_connections()
    user = get_user(user_id)
    application = dc.get_application_by_id(application_id, with_event=True)
    if not application:
        return None, 'not_found'
    if not roles_service.can_process_applications(user, application.event_id):
        return None, 'forbidden'

    new_status = 'approved' if approve else 'rejected'
    process_application(application, new_status, processed_by=user)
    return application, None

def process_application_shift_decision(user_id: int, application_id: int, shift_id: int, approve: bool):
    """Одобрить/резерв заявки ТОЛЬКО на конкретную смену (bot-update.md §2.3.C) — если
    заявка подана на несколько смен, решение по одной не трогает остальные. Переиспользует
    веб-эталон `blog.services.applications.process_shift_decision` (создание/удаление
    Participation, ApplicationShiftDecision, пересчёт статистики, уведомление волонтёру —
    уже всё реализовано там, здесь только права и вызов)."""
    close_old_connections()
    from blog.services.applications import process_shift_decision

    user = get_user(user_id)
    application = dc.get_application_by_id(application_id, with_event=True)
    if not application:
        return None, 'not_found'
    if not roles_service.can_process_applications(user, application.event_id):
        return None, 'forbidden'
    shift = dc.get_shift_by_id(shift_id, event_id=application.event_id)
    if not shift:
        return None, 'not_found'

    new_status = 'approved' if approve else 'rejected'
    process_shift_decision(application, shift, new_status, processed_by=user)
    return application, None

def application_shifts_for_decision(application_id: int):
    """Смены конкретной заявки (выбранные чипами, либо все смены меро) — для отрисовки
    кнопок по сменам на карточке заявки у ТЛ (bot-update.md §2.3.C)."""
    close_old_connections()
    application = dc.get_application_by_id(application_id, prefetch_shifts=True)
    if not application:
        return []
    return list(application.selected_shifts.all()) or list(application.event.shifts.all())

def process_all_applications(user_id: int, event_id: int):
    """Одобрить все заявки на рассмотрении по меро одним действием (tg-bot.md §5.2, TL4).
    Права те же, что и для одиночного решения. Возвращает (список одобренных заявок, ошибка)."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.can_process_applications(user, event_id):
        return None, 'forbidden'
    apps = dc.get_applications(status_filter='new', event_id=event_id)
    approved = []
    for application in apps:
        process_application(application, 'approved', processed_by=user)
        approved.append(application)
    return approved, None

def event_ready_for_attendance(user_id: int, event_id: int):
    """Меро прошло и по нему уже можно отмечать явку (bot-update.md §2.3.D). Возвращает
    (готово: bool, ошибка|None)."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.can_process_applications(user, event_id):
        return False, 'forbidden'
    event = dc.get_event_by_id(event_id)
    if not event:
        return False, 'not_found'
    return event.compute_status() in ('passed', 'finished'), None

def mark_all_attended(user_id: int, event_id: int):
    """«Были все» (bot-update.md §2.3.D) — все одобренные участия по меро становятся
    `attended`, пересчёт статистики + уведомление менеджерам, что можно забирать
    табличку часов. Возвращает (число обновлённых участий, код ошибки|None)."""
    close_old_connections()
    from blog.services.stats import recalc_user_aggregates
    from blog.services.notifications import notify_all_attended_to_managers

    user = get_user(user_id)
    if not roles_service.can_process_applications(user, event_id):
        return None, 'forbidden'
    event = dc.get_event_by_id(event_id)
    if not event:
        return None, 'not_found'

    participations = dc.get_participations(event_id=event_id)
    affected_users = set()
    for p in participations:
        if p.status != 'attended':
            dc.update_participation_status(p, 'attended', actor_user=user)
        affected_users.add(p.user)
    for u in affected_users:
        recalc_user_aggregates(u)
    notify_all_attended_to_managers(event, user)
    logger.info('Явка «были все» из бота: event=%s count=%s by=%s', event_id, len(participations), actor(user))
    return len(participations), None

def attendance_web_link(user_id: int, event_id: int) -> str:
    """Ссылка с автологином на страницу меро для простановки явки «были не все»
    (bot-update.md §2.3.D) — переиспользует одноразовый токен веб-входа из бота
    (`web_auth.issue_auth_token`), с `next` на страницу конкретного мероприятия."""
    close_old_connections()
    from urllib.parse import quote
    from django.conf import settings
    from blog.services.web_auth import issue_auth_token

    user = get_user(user_id)
    token = issue_auth_token(user)
    base = (settings.WEBAPP_URL or '').rstrip('/')
    next_path = quote(f'/events/{event_id}/')
    return f'{base}/auth/tg/{token.token}/?next={next_path}'

def all_applications(user_id: int, limit: int = 20):
    """Все заявки по всем мероприятиям (tg-bot.md §6.1) — только для менеджера."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.is_manager(user):
        return None, 'forbidden'
    apps = dc.get_applications()[:limit]
    return apps, None

def notify_manager_processed_application(user_id: int, application):
    """Оповещение ТЛ меро, что заявку обработал именно менеджер (bot-update.md §2.4.A) —
    вызывается после успешной обработки, только если обработавший — менеджер (не ТЛ)."""
    close_old_connections()
    user = get_user(user_id)
    if not roles_service.is_manager(user):
        return
    from blog.services.notifications import notify_manager_processed
    notify_manager_processed(application, user)
