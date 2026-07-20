"""Доступ к данным: инфраструктура очередей бота — исходящие сообщения (`BotOutbox`)
и отложенное снятие inline-кнопок (`PendingButtonRemoval`).

Это не бизнес-данные ВЦ, а транспорт уведомлений; вынесено в контроллер, чтобы весь
доступ к БД (для будущего логирования) был в одном слое.
"""
from typing import Optional, List

from django.utils import timezone

from blog.models import BotOutbox, PendingButtonRemoval


# --- Исходящие сообщения (веб-процесс кладёт, процесс бота разбирает) ---
def create_outbox(chat_id, text: str, apply_event=None) -> BotOutbox:
    return BotOutbox.objects.create(chat_id=str(chat_id), text=text, apply_event=apply_event)


def fetch_pending_outbox(batch: int, max_attempts: int) -> List[BotOutbox]:
    return list(
        BotOutbox.objects.filter(status='pending', attempts__lt=max_attempts).order_by('created_at')[:batch]
    )


def mark_outbox_sent(outbox_id: int) -> None:
    BotOutbox.objects.filter(pk=outbox_id).update(status='sent', sent_at=timezone.now())


def get_outbox(outbox_id: int) -> Optional[BotOutbox]:
    return BotOutbox.objects.filter(pk=outbox_id).first()


def save_outbox(item: BotOutbox, update_fields) -> None:
    """Сохраняет изменённые поля записи outbox (счётчик попыток/статус/ошибка).
    Бизнес-правило «после N попыток → failed» остаётся в сервисе бота."""
    item.save(update_fields=list(update_fields))


# --- Отложенное снятие inline-кнопок («остывание» через TTL) ---
def create_button_removal(chat_id, message_id: int, remove_at) -> PendingButtonRemoval:
    return PendingButtonRemoval.objects.create(chat_id=str(chat_id), message_id=message_id, remove_at=remove_at)


def fetch_due_button_removals(batch: int) -> List[PendingButtonRemoval]:
    return list(
        PendingButtonRemoval.objects.filter(remove_at__lte=timezone.now()).order_by('remove_at')[:batch]
    )


def delete_button_removal(removal_id: int) -> None:
    PendingButtonRemoval.objects.filter(pk=removal_id).delete()
