"""Сервисы бота: домен «outbox». Часть пакета tg_bot.services (см. README.md).

Инфраструктура очередей бота: исходящие сообщения (BotOutbox) и отложенное
снятие inline-кнопок (PendingButtonRemoval).

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403


BUTTON_TTL_SECONDS = 300  # 5 минут — inline-кнопки "остывают" (tg-bot.md §0.2)

def schedule_button_removal(chat_id, message_id: int):
    """Ставит в очередь снятие inline-клавиатуры сообщения через `BUTTON_TTL_SECONDS`.
    Вызывается сразу после отправки любого сообщения с inline-кнопками, срок жизни
    которых ограничен (подать заявку, одобрить/резерв, оценка меро и т.п.) — чтобы
    пользователь не мог нажать на кнопку многомесячной давности с уже неактуальным
    состоянием. Обходчик — `tg_bot/notifier.py::_process_button_removals`."""
    close_old_connections()
    from blog.models import PendingButtonRemoval
    PendingButtonRemoval.objects.create(
        chat_id=str(chat_id),
        message_id=message_id,
        remove_at=timezone.now() + timedelta(seconds=BUTTON_TTL_SECONDS),
    )

def fetch_due_button_removals(batch: int = 50) -> list:
    close_old_connections()
    from blog.models import PendingButtonRemoval
    return list(
        PendingButtonRemoval.objects.filter(remove_at__lte=timezone.now())
        .order_by('remove_at')[:batch]
    )

def delete_button_removal(removal_id: int):
    close_old_connections()
    from blog.models import PendingButtonRemoval
    PendingButtonRemoval.objects.filter(pk=removal_id).delete()

MAX_ATTEMPTS = 5

def fetch_pending_outbox(batch: int = 20) -> list:
    close_old_connections()
    return list(
        BotOutbox.objects.filter(status='pending', attempts__lt=MAX_ATTEMPTS)
        .order_by('created_at')[:batch]
    )

def mark_outbox_sent(outbox_id: int):
    close_old_connections()
    BotOutbox.objects.filter(pk=outbox_id).update(
        status='sent', sent_at=timezone.now()
    )

def mark_outbox_failed(outbox_id: int, error: str):
    close_old_connections()
    item = BotOutbox.objects.filter(pk=outbox_id).first()
    if not item:
        return
    item.attempts += 1
    item.last_error = str(error)[:1000]
    if item.attempts >= MAX_ATTEMPTS:
        item.status = 'failed'
    item.save(update_fields=['attempts', 'last_error', 'status'])
