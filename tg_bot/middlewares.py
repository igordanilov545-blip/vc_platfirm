"""Middleware диспетчера aiogram — единая точка перехвата апдейтов для аналитики
(см. tg_bot/bot.py create_dispatcher). Пишет BotSessionPing (онлайн-график) на каждый
апдейт и ButtonClickEvent(source='bot') на callback-кнопки и команды.
"""
from aiogram import BaseMiddleware
from asgiref.sync import sync_to_async
from django.db import close_old_connections

from blog.logging_utils import get_bot_logger

logger = get_bot_logger(__name__)


def _record_activity(telegram_id, action_key):
    close_old_connections()
    from blog.models import BotSessionPing, ButtonClickEvent, User
    from blog.services import roles as roles_service

    user = User.objects.filter(telegram_id=str(telegram_id)).first()
    BotSessionPing.objects.create(user=user)
    if action_key:
        ButtonClickEvent.objects.create(
            source='bot',
            user=user,
            role_snapshot=roles_service.role_slug(user) if user else 'volunteer',
            action_key=action_key[:150],
        )


def _normalize_action_key(event):
    """Сводит callback_data/текст сообщения к стабильному ключу для группировки на
    дашборде: параметризованные callback_data (`apply:123`, `rate:5:9`) теряют
    динамический хвост (id/значение), reply-кнопки/команды учитываются как есть.
    Список известных ключей для дашборда — `blog.services.analytics.BOT_ACTION_REGISTRY`,
    держать в синхроне при добавлении новых кнопок в `tg_bot/keyboards.py`."""
    callback_data = getattr(event, 'data', None)
    if callback_data:
        prefix = callback_data.split(':', 1)[0]
        return f'cb:{prefix}'
    text = getattr(event, 'text', None)
    if not text:
        return None
    if text.startswith('/'):
        return f'cmd:{text.split()[0]}'
    return f'menu:{text}'


class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            telegram_id = event.from_user.id if event.from_user else None
            action_key = _normalize_action_key(event)
            if telegram_id is not None:
                await sync_to_async(_record_activity)(telegram_id, action_key)
        except Exception:
            logger.exception('Сбой ActivityMiddleware (аналитика бота)')
        return await handler(event, data)
