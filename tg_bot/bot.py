"""Точка сборки бота: диспетчер, роутеры (tg-bot.md §9)."""
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from django.conf import settings

from tg_bot.handlers import common, volunteer, web_access, team_leader, manager
from tg_bot.middlewares import ActivityMiddleware
from blog.logging_utils import get_bot_logger

logger = get_bot_logger(__name__)


def create_bot() -> Bot:
    if not settings.TG_BOT_TOKEN:
        raise RuntimeError('TG_BOT_TOKEN не задан в .env')
    return Bot(
        token=settings.TG_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Аналитика: перехватывает все сообщения/callback до хендлеров (heartbeat + клики).
    dp.message.outer_middleware(ActivityMiddleware())
    dp.callback_query.outer_middleware(ActivityMiddleware())
    # Более специфичные роутеры (ТЛ/менеджер) — раньше общих, чтобы их callback_data
    # не перехватывались хендлерами волонтёра.
    dp.include_router(team_leader.router)
    dp.include_router(manager.router)
    dp.include_router(web_access.router)
    dp.include_router(volunteer.router)
    dp.include_router(common.router)
    return dp
