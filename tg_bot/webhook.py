"""Приём апдейтов Telegram через webhook (для shared-хостинга Beget).

На shared-тарифе Beget нельзя держать постоянный фоновый процесс (long polling
умирает вместе с SSH-сессией, systemd/supervisor нет). Зато WSGI-приложение под
Passenger живёт постоянно — поэтому входящие апдейты принимаем webhook'ом прямо в
Django, синхронно скармливая каждый апдейт диспетчеру aiogram.

Диспетчер и Bot создаются один раз на процесс (ленивая инициализация) и переиспользуются.
Секретность эндпоинта обеспечивается двумя слоями:
  1) непубличный путь `/tg/webhook/<TG_WEBHOOK_SECRET>/` (секрет из .env);
  2) заголовок `X-Telegram-Bot-Api-Secret-Token`, который Telegram присылает, если
     задать secret_token при set_webhook (см. management-команду set_webhook).
"""
import asyncio
import json

from aiogram.types import Update
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from tg_bot.bot import create_bot, create_dispatcher
from blog.logging_utils import get_bot_logger

logger = get_bot_logger(__name__)

# Ленивая инициализация на процесс: Passenger держит воркер живым, поэтому bot/dp
# создаются один раз при первом апдейте и переиспользуются между запросами.
_bot = None
_dp = None


def _get_bot_and_dp():
    global _bot, _dp
    if _bot is None or _dp is None:
        _bot = create_bot()
        _dp = create_dispatcher()
    return _bot, _dp


@csrf_exempt
def telegram_webhook(request, secret: str):
    # Слой 1: секрет в пути.
    if secret != settings.TG_WEBHOOK_SECRET:
        logger.warning('Webhook: неверный секрет в пути.')
        return HttpResponseForbidden('forbidden')

    # health-check из браузера (GET): путь с верным секретом уже подтверждён — ок.
    # Заголовок Telegram проверяем только для реальных апдейтов (POST).
    if request.method != 'POST':
        return HttpResponse('ok')

    # Слой 2: секретный заголовок от Telegram (Telegram шлёт его при set_webhook).
    if settings.TG_WEBHOOK_SECRET:
        header_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if header_token != settings.TG_WEBHOOK_SECRET:
            logger.warning('Webhook: неверный секретный заголовок Telegram.')
            return HttpResponseForbidden('forbidden')

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        logger.warning('Webhook: тело не является валидным JSON.')
        return JsonResponse({'ok': False}, status=400)

    bot, dp = _get_bot_and_dp()
    update = Update.model_validate(payload, context={'bot': bot})

    # aiogram полностью асинхронный — крутим один апдейт в собственном event loop.
    # Passenger вызывает вью синхронно, поэтому asyncio.run здесь безопасен.
    try:
        asyncio.run(dp.feed_update(bot, update))
    except Exception:
        logger.exception('Webhook: ошибка обработки апдейта.')
        # Возвращаем 200, чтобы Telegram не заваливал ретраями один и тот же
        # «ядовитый» апдейт — ошибка уже в логах bot.log.
        return JsonResponse({'ok': True})

    return JsonResponse({'ok': True})
