"""Диспетчер уведомлений в Telegram-бота (Этап 8, architecture.md разд. 4).

Веб-приложение не ходит в Telegram API напрямую: события кладутся в очередь
`bot_outbox`, а процесс бота (`python manage.py run_bot`) отправляет их
с ретраями. Так падение Telegram API не влияет на веб-запросы.
"""
from blog.models import BotOutbox, EventStaff, Manager, User


def _has_telegram_chat(user: User) -> bool:
    """У пользователя есть реальный Telegram-чат (а не служебный `web:*` id)."""
    return bool(user.telegram_id) and user.telegram_id.lstrip('-').isdigit()


def enqueue(chat_id: str, text: str) -> BotOutbox:
    return BotOutbox.objects.create(chat_id=str(chat_id), text=text)


def notify_user(user: User, text: str):
    """Уведомление конкретному пользователю, если он приходил в бота."""
    if user and _has_telegram_chat(user):
        enqueue(user.telegram_id, text)


def notify_event_staff(event, text: str):
    """Новая заявка → тим-лидерам мероприятия и всем активным менеджерам,
    у кого не выключен тумблер `notify_applications` (db.md, правило 7c)."""
    recipients = {}
    staff_users = User.objects.filter(
        staff_assignments__event=event, staff_assignments__staff_role='team_lead',
        notify_applications=True,
    )
    for user in staff_users:
        recipients[user.id] = user
    manager_users = User.objects.filter(
        manager_roles__revoked_at__isnull=True, notify_applications=True,
    ).distinct()
    for user in manager_users:
        recipients[user.id] = user

    for user in recipients.values():
        notify_user(user, text)


def notify_application_submitted(application):
    text = (
        f'📥 <b>Новая заявка</b> на «{application.event.title}»\n'
        f'{application.first_name} {application.last_name or ""}'.strip()
        + (f' (@{application.telegram_username.lstrip("@")})' if application.telegram_username else '')
    )
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


def notify_feedback_request(user: User, event):
    """Просьба оценить мероприятие после участия (tg-bot.md §4.6)."""
    text = (
        f'🙏 Спасибо, что был(а) на «{event.title}»!\n\n'
        'Оцени мероприятие от 1 до 10 и, если хочешь, оставь комментарий — это помогает '
        'организаторам стать лучше.'
    )
    notify_user(user, text)


def broadcast_new_event(event):
    """Новое опубликованное мероприятие → всем подписанным активным волонтёрам."""
    first_shift = event.shifts.order_by('day').first()
    when = f'\n📆 Ближайший день: {first_shift.day.strftime("%d.%m.%Y")}' if first_shift else ''
    where = f'\n📍 {event.location.name}' if event.location else ''
    text = (
        f'🆕 <b>Новое мероприятие: {event.title}</b>{when}{where}\n\n'
        f'{(event.description or "")[:300]}\n\n'
        'Подать заявку: /events'
    )
    subscribers = User.objects.filter(status='active', notify_new_events=True)
    for user in subscribers:
        notify_user(user, text)
