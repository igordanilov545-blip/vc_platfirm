"""Вспомогательные функции браузерного входа через Telegram (раздел 2b).

Два пути:
- Telegram Login Widget — HMAC-проверка в `blog.services.telegram_auth.validate_login_widget`,
  логин прямо на странице входа.
- Deep-link «войти через бота»: бот создаёт одноразовый `TelegramAuthToken` (TTL 5 мин)
  и присылает ссылку `/auth/tg/<token>/`; переход по ней логинит в веб-сессию.
"""
import datetime

from django.utils import timezone

from data_base import data_controller as dc
from blog.models import TelegramAuthToken, User  # только для аннотаций типов
from blog.logging_utils import get_web_logger

logger = get_web_logger(__name__)

# Время жизни одноразовой ссылки входа через бота.
AUTH_TOKEN_TTL = datetime.timedelta(minutes=5)


def issue_auth_token(user: User) -> TelegramAuthToken:
    """Создаёт одноразовый токен входа для пользователя (вызывается ботом при
    deep-link `?start=weblogin`). Старые неиспользованные токены того же
    пользователя гасим, чтобы жила только последняя ссылка."""
    dc.invalidate_user_auth_tokens(user)
    return dc.create_auth_token(user, expires_at=timezone.now() + AUTH_TOKEN_TTL)


def consume_auth_token(token: str):
    """Возвращает пользователя по валидному одноразовому токену и помечает токен
    использованным, либо None, если токен неизвестен/просрочен/уже использован."""
    obj = dc.get_auth_token(token)
    if obj is None or not obj.is_valid():
        logger.warning('Попытка входа по недействительной/просроченной ссылке из бота.')
        return None
    obj.used_at = timezone.now()
    obj.save(update_fields=['used_at'])
    logger.info('Вход по одноразовой ссылке из бота: user=%s', obj.user_id)
    return obj.user
