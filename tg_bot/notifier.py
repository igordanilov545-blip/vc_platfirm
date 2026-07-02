"""Диспетчер исходящих уведомлений (tg-bot.md §7): забирает `bot_outbox`,
отправляет с ретраями; отдельно — проактивные запросы на оценку меро (§4.6),
которым нужна inline-клавиатура, поэтому они не идут через `bot_outbox`.
"""
import asyncio
import logging

from asgiref.sync import sync_to_async

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from tg_bot import services, keyboards as kb

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
FEEDBACK_DELAY_HOURS = 3.0


async def _process_outbox_batch(bot: Bot):
    items = await sync_to_async(services.fetch_pending_outbox)()
    for item in items:
        try:
            await bot.send_message(chat_id=item.chat_id, text=item.text)
            await sync_to_async(services.mark_outbox_sent)(item.id)
        except TelegramAPIError as e:
            logger.warning('Не удалось отправить outbox #%s: %s', item.id, e)
            await sync_to_async(services.mark_outbox_failed)(item.id, str(e))


async def _process_feedback_requests(bot: Bot):
    participations = await sync_to_async(services.pending_feedback_requests)(FEEDBACK_DELAY_HOURS)
    for p in participations:
        user = p.user
        if not user.telegram_id or not user.telegram_id.lstrip('-').isdigit():
            await sync_to_async(services.mark_feedback_requested)(p.id)
            continue
        event = p.event_day.event
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f'🙏 Спасибо, что был(а) на «{event.title}»!\n\n'
                    'Оцени мероприятие от 1 до 10 и, если хочешь, оставь комментарий — '
                    'это помогает организаторам стать лучше.'
                ),
                reply_markup=kb.rating_keyboard(event.id),
            )
        except TelegramAPIError as e:
            logger.warning('Не удалось отправить запрос оценки участнику %s: %s', p.id, e)
        await sync_to_async(services.mark_feedback_requested)(p.id)


async def run_notifier_loop(bot: Bot):
    logger.info('Диспетчер уведомлений запущен.')
    while True:
        try:
            await _process_outbox_batch(bot)
            await _process_feedback_requests(bot)
        except Exception:
            logger.exception('Ошибка в цикле диспетчера уведомлений.')
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
