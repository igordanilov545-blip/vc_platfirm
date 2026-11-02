"""Запуск Telegram-бота (long polling) + диспетчера уведомлений (Этап 8).

    python manage.py run_bot
"""
import asyncio
from contextlib import suppress

from django.core.management.base import BaseCommand, CommandError

from tg_bot.bot import create_bot, create_dispatcher
from tg_bot.notifier import run_notifier_loop
from blog.logging_utils import get_bot_logger

# Логирование настроено централизованно в settings.LOGGING (канал vc.bot → logs/bot.log).
# Отдельный logging.basicConfig здесь НЕ ставим — он перехватил бы корневой логгер и
# сломал разведение логов по файлам.
logger = get_bot_logger(__name__)


class Command(BaseCommand):
    help = 'Запускает Telegram-бота (long polling) и диспетчер уведомлений.'

    def handle(self, *args, **options):
        logger.info('Запуск процесса бота (run_bot).')
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            pass

    async def _run(self):
        from aiogram.types import BotCommand

        bot = create_bot()
        notifier_task = None
        try:
            info = await bot.get_webhook_info()
            if info.url:
                raise CommandError(
                    'У бота включён webhook. Для локальной разработки используйте отдельного '
                    'бота или снимите webhook: python manage.py set_webhook --delete. '
                    'Снятие webhook отключит доставку обновлений на сервер.'
                )
            dp = create_dispatcher()
            await bot.set_my_commands([
                BotCommand(command='start', description='Начать / главное меню'),
                BotCommand(command='login', description='Авторизоваться на сайте'),
                BotCommand(command='help', description='Помощь'),
            ])
            notifier_task = asyncio.create_task(run_notifier_loop(bot))
            await dp.start_polling(bot, close_bot_session=False)
        finally:
            if notifier_task is not None:
                notifier_task.cancel()
                with suppress(asyncio.CancelledError):
                    await notifier_task
            await bot.session.close()
