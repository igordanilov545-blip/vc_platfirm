"""Диспетчер уведомлений в Telegram-бота (Этап 8, architecture.md разд. 4).

Веб-приложение не ходит в Telegram API напрямую: события кладутся в очередь
`bot_outbox`, а процесс бота (`python manage.py run_bot`) отправляет их
с ретраями. Так падение Telegram API не влияет на веб-запросы.
"""
from django.db.models import Exists, OuterRef

from data_base import data_controller as dc
from blog.models import User  # только для аннотаций типов


def _has_telegram_chat(user: User) -> bool:
    """У пользователя есть реальный Telegram-чат (а не служебный `web:*` id)."""
    return bool(user.telegram_id) and user.telegram_id.lstrip('-').isdigit()


def enqueue(chat_id: str, text: str, apply_event=None):
    return dc.create_outbox(chat_id, text, apply_event=apply_event)


def notify_user(user: User, text: str, apply_event=None):
    """Уведомление конкретному пользователю, если он приходил в бота. Если передан
    `apply_event`, к сообщению прикрепляется кнопка «Подать заявку» на это меро."""
    if user and _has_telegram_chat(user):
        enqueue(user.telegram_id, text, apply_event=apply_event)


def notify_event_staff(event, text: str):
    """Новая заявка → тим-лидерам ИМЕННО ЭТОГО мероприятия и всем активным менеджерам,
    у кого не выключен тумблер `notify_applications` (db.md, правило 7c).

    Активность роли проверяется через `Exists` (наличие строки в managers/team_leaders с
    `revoked_at IS NULL`), а НЕ через `manager_roles__revoked_at__isnull=True`: последнее в
    LEFT JOIN истинно и для пользователей БЕЗ роли вовсе (у них revoked_at = NULL из-за
    отсутствия связанной записи) — из-за этого раньше уведомление уходило всем подряд.
    """
    recipients = {}

    # Тим-лидеры именно этого меро (event_staff.staff_role='team_lead' на данном event).
    staff_users = dc.users_qs().filter(
        staff_assignments__event=event, staff_assignments__staff_role='team_lead',
        notify_applications=True,
    ).distinct()
    for user in staff_users:
        recipients[user.id] = user

    # Активные менеджеры: есть строка managers с revoked_at IS NULL.
    manager_users = dc.users_qs().filter(notify_applications=True).filter(
        Exists(dc.managers_qs().filter(user=OuterRef('pk'), revoked_at__isnull=True))
    )
    for user in manager_users:
        recipients[user.id] = user

    for user in recipients.values():
        notify_user(user, text)


def notify_application_changed(application, change_text: str):
    """Заявка изменена повторным Excel-импортом (содержание отличается от того, что
    уже было) → тим-лидерам меро и активным менеджерам, аналогично новой заявке."""
    text = f'✏️ <b>Заявка изменена</b> на «{application.event.title}»\n{change_text}'
    notify_event_staff(application.event, text)


def notify_application_submitted(application, unknown_age: bool = False):
    """Новая заявка → тим-лидерам/менеджерам. Если заявка автоматически ушла в резерв
    из-за несоответствия требованиям меро (application.auto_reject_reason) — причина
    указывается прямо в уведомлении. `unknown_age` — отдельная пометка (не блокирует
    заявку сама по себе): у меро есть требование «18+», а дата рождения неизвестна."""
    text = (
        f'📥 <b>Новая заявка</b> на «{application.event.title}»\n'
        f'{application.first_name} {application.last_name or ""}'.strip()
        + (f' (@{application.telegram_username.lstrip("@")})' if application.telegram_username else '')
    )
    if application.auto_reject_reason:
        text += f'\n\n⚠️ <b>Автоматически отправлена в резерв:</b> {application.auto_reject_reason}.'
    if unknown_age:
        text += '\n\n❓ Возраст волонтёра неизвестен (дата рождения не указана в профиле) — проверьте вручную.'
    notify_event_staff(application.event, text)


def notify_application_status(application):
    """Смена статуса заявки → волонтёру."""
    if not application.user:
        return
    if application.status == 'approved':
        text = (
            f'✅ Ваша заявка на «{application.event.title}» <b>одобрена</b>!\n'
            'Детали и дни смен — в боте: /myapps'
        )
    elif application.status == 'rejected':
        text = (
            f'ℹ️ Ваша заявка на «{application.event.title}» переведена в <b>резерв</b>.\n'
            'Если места освободятся, мы с вами свяжемся.'
        )
    else:
        return
    notify_user(application.user, text)


def notify_shift_decision_status(application, shift, new_status):
    """Смена статуса заявки НА КОНКРЕТНУЮ СМЕНУ → волонтёру (несколько смен одной
    заявки решаются независимо, см. ApplicationShiftDecision)."""
    if not application.user:
        return
    day_label = shift.day.strftime('%d.%m.%Y')
    if new_status == 'approved':
        text = (
            f'✅ Ваша заявка на «{application.event.title}» (смена {day_label}) <b>одобрена</b>!\n'
            'Детали — в боте: /myapps'
        )
    elif new_status == 'rejected':
        text = (
            f'ℹ️ Ваша заявка на «{application.event.title}» (смена {day_label}) переведена в <b>резерв</b>.\n'
            'Если места освободятся, мы с вами свяжемся.'
        )
    else:
        return
    notify_user(application.user, text)


def notify_feedback_request(user: User, event):
    """Просьба оценить мероприятие после участия (tg-bot.md §4.6)."""
    text = (
        f'🙏 Спасибо, что был(а) на «{event.title}»!\n\n'
        'Оцени мероприятие от 1 до 10 и, если хочешь, оставь комментарий — это помогает '
        'организаторам стать лучше.'
    )
    notify_user(user, text)


def notify_became_team_leader(user: User):
    """Пользователя назначили тим-лидером (bot-update.md §2.3.A, узел `became_tl`) —
    проактивная отбивка о новых функциях бота, волонтёрский функционал сохраняется."""
    text = (
        '🎉 Поздравляем, вы стали тим-лидером Волонтёрского центра!\n\n'
        'Новые функции:\n👥 /myevents — ваши мероприятия и заявки на них\n'
        '🔔 /appnotify — уведомления о заявках\n\n'
        'У вас остаётся весь функционал волонтёра: /events, /myapps, /stats, /subscribe.'
    )
    notify_user(user, text)


def notify_assigned_to_event(user: User, event):
    """Пользователя назначили тим-лидером НА КОНКРЕТНОЕ мероприятие (bot-update.md
    §2.3.A, узел `assigned_event`)."""
    first_shift = event.shifts.order_by('day').first()
    when = f' ({first_shift.day.strftime("%d.%m.%Y")})' if first_shift else ''
    text = f'📌 Вы назначены тим-лидером на «{event.title}»{when}.'
    notify_user(user, text)


def notify_manager_processed(application, manager: User):
    """Заявку обработал именно менеджер (bot-update.md §2.4.A) → тим-лидерам этого меро
    (не самому менеджеру — он и так знает, что сделал)."""
    name = f'{manager.first_name} {manager.last_name or ""}'.strip() if manager else 'Менеджер'
    status_label = 'одобрена' if application.status == 'approved' else 'резерв'
    text = (
        f'ℹ️ Заявка на «{application.event.title}» обработана менеджером {name}. '
        f'Статус: {status_label}.'
    )
    staff_users = dc.users_qs().filter(
        staff_assignments__event=application.event, staff_assignments__staff_role='team_lead',
        notify_applications=True,
    ).distinct()
    for user in staff_users:
        notify_user(user, text)


def notify_all_attended_to_managers(event, team_lead: User):
    """«Были все» от тим-лидера (bot-update.md §2.3.D) → активным менеджерам: можно
    забирать табличку часов по этому мероприятию."""
    name = f'{team_lead.first_name} {team_lead.last_name or ""}'.strip() if team_lead else 'Тим-лидер'
    text = (
        f'✅ Тим-лидер {name} отметил(а): на «{event.title}» были все. '
        'Можно забирать табличку для проставления часов.'
    )
    manager_users = dc.users_qs().filter(notify_applications=True).filter(
        Exists(dc.managers_qs().filter(user=OuterRef('pk'), revoked_at__isnull=True))
    )
    for user in manager_users:
        notify_user(user, text)


def broadcast_new_event(event):
    """Оповещение о мероприятии → подписанным активным волонтёрам, КРОМЕ тех, кто уже
    подал заявку на это меро (им напоминание не нужно). Рассылку можно делать повторно
    (напр. добор): те, кто заявился между рассылками, автоматически исключаются.

    Возвращает число адресатов, кому реально ушло уведомление."""
    first_shift = event.shifts.order_by('day').first()
    when = f'\n📆 Ближайший день: {first_shift.day.strftime("%d.%m.%Y")}' if first_shift else ''
    where = f'\n📍 {event.location.name}' if event.location else ''
    text = (
        f'🆕 <b>Новое мероприятие: {event.title}</b>{when}{where}\n\n'
        f'{(event.description or "")[:300]}\n\n'
        'Нажми кнопку ниже, чтобы сразу подать заявку 👇'
    )
    # Волонтёры, уже подавшие заявку на это меро (в любом статусе) — из рассылки исключаем.
    applied_user_ids = set(
        event.applications.filter(user__isnull=False).values_list('user_id', flat=True)
    )
    subscribers = dc.users_qs().filter(status='active', notify_new_events=True).exclude(
        id__in=applied_user_ids
    )
    sent = 0
    for user in subscribers:
        # apply_event → к сообщению прикрепится inline-кнопка «Подать заявку» на это меро.
        notify_user(user, text, apply_event=event)
        sent += 1
    return sent
