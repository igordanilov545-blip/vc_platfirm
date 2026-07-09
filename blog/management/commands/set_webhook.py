"""Регистрирует (или снимает) webhook Telegram-бота.

    python manage.py set_webhook            # поставить webhook на WEBAPP_URL
    python manage.py set_webhook --delete   # снять webhook (вернуться к polling локально)
    python manage.py set_webhook --info     # показать текущее состояние webhook

На проде (Beget) вызывается один раз после деплоя — Telegram начинает слать апдейты
на наш Django-эндпоинт /tg/webhook/<secret>/. Требует HTTPS-адрес в WEBAPP_URL.
"""
import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tg_bot.bot import create_bot


class Command(BaseCommand):
    help = 'Ставит/снимает webhook Telegram-бота (см. tg_bot/webhook.py).'

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true', help='Снять webhook.')
        parser.add_argument('--info', action='store_true', help='Показать состояние webhook.')

    def handle(self, *args, **options):
        asyncio.run(self._run(options))

    async def _run(self, options):
        bot = create_bot()
        try:
            if options['info']:
                info = await bot.get_webhook_info()
                self.stdout.write(f'URL: {info.url or "(не задан)"}')
                self.stdout.write(f'Ожидает апдейтов: {info.pending_update_count}')
                if info.last_error_message:
                    self.stdout.write(self.style.WARNING(
                        f'Последняя ошибка: {info.last_error_date} {info.last_error_message}'))
                return

            if options['delete']:
                await bot.delete_webhook(drop_pending_updates=False)
                self.stdout.write(self.style.SUCCESS('Webhook снят. Можно использовать long polling.'))
                return

            if not settings.WEBAPP_URL.startswith('https://'):
                raise CommandError(
                    f'WEBAPP_URL должен быть https-адресом, сейчас: "{settings.WEBAPP_URL}". '
                    'Telegram принимает webhook только по HTTPS.')
            if not settings.TG_WEBHOOK_SECRET:
                raise CommandError('TG_WEBHOOK_SECRET не задан в .env.')

            url = f'{settings.WEBAPP_URL.rstrip("/")}/tg/webhook/{settings.TG_WEBHOOK_SECRET}/'
            await bot.set_webhook(
                url=url,
                secret_token=settings.TG_WEBHOOK_SECRET,
                drop_pending_updates=True,
                allowed_updates=['message', 'callback_query', 'my_chat_member'],
            )
            self.stdout.write(self.style.SUCCESS(f'Webhook установлен: {url}'))
        finally:
            await bot.session.close()
