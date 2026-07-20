"""Сервисы бота: домен «feedback_queue». Часть пакета tg_bot.services (см. README.md).

Очередь запросов оценки мероприятия (проактивные сообщения бота).

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403


def pending_feedback_requests(delay_hours: float = 3.0) -> list:
    """Участники, кому пора отправить запрос на оценку мероприятия (tg-bot.md §4.6)."""
    close_old_connections()
    cutoff = timezone.now() - timedelta(hours=delay_hours)
    return dc.get_participations_pending_feedback(cutoff)

def mark_feedback_requested(participation_id: int):
    close_old_connections()
    participation = dc.get_participation_by_id(participation_id)
    if participation:
        dc.mark_feedback_requested(participation)
