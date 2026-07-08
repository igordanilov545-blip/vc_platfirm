"""Общие UI-хелперы бота: отправка сообщений с "остывающими" inline-кнопками
(tg-bot.md §0.2) — единая точка, чтобы каждый хендлер не дублировал постановку
в очередь `PendingButtonRemoval`.
"""
from asgiref.sync import sync_to_async

from aiogram.types import InlineKeyboardMarkup, Message

from tg_bot import services


async def answer_with_expiring_keyboard(message: Message, text: str, reply_markup: InlineKeyboardMarkup, **kwargs):
    """Отправляет сообщение с inline-клавиатурой и планирует её автоматическое снятие
    через `services.BUTTON_TTL_SECONDS` (5 минут). Использовать вместо голого
    `message.answer(..., reply_markup=inline_kb)` для любых временных inline-кнопок
    (подать заявку, одобрить/резерв, оценка, редактировать/отменить заявку и т.п.).

    Постоянные reply-клавиатуры (нижнее меню) сюда не относятся — только inline.
    """
    sent = await message.answer(text, reply_markup=reply_markup, **kwargs)
    await sync_to_async(services.schedule_button_removal)(sent.chat.id, sent.message_id)
    return sent
