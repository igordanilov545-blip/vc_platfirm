"""Один проход диспетчера исходящих уведомлений (для cron на shared-хостинге).

    python manage.py process_notifications

На Beget нельзя держать постоянный фоновый цикл (см. tg_bot/notifier.run_notifier_loop),
поэтому его тело вызывается по расписанию из cron-задачи панели Beget (раз в минуту):
разбирает bot_outbox, шлёт проактивные запросы оценок, снимает просроченные кнопки.

Локально/на VPS вместо этого используется `run_bot` (polling + постоянный notifier-цикл).
"""
import asyncio

from django.core.management.base import BaseCommand

from tg_bot.bot import create_bot
from tg_bot.notifier import (
    _process_outbox_batch,
    _process_feedback_requests,
    _process_button_removals,
)
from blog.logging_utils import get_bot_logger

logger = get_bot_logger(__name__)


class Command(BaseCommand):
    help = 'Один проход диспетчера уведомлений (outbox/оценки/снятие кнопок) — для cron.'

    def handle(self, *args, **options):
        asyncio.run(self._run())

    async def _run(self):
        bot = create_bot()
        try:
            await _process_outbox_batch(bot)
            await _process_feedback_requests(bot)
            await _process_button_removals(bot)
        except Exception:
            logger.exception('Ошибка в process_notifications.')
        finally:
            await bot.session.close()
