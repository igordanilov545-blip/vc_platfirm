"""Сервисы бота: домен «web_auth». Часть пакета tg_bot.services (см. README.md).

Веб-доступ и Telegram-верификация: одноразовая ссылка входа, подтверждение/
отклонение верификации по токену.

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403
from .users import get_user


def issue_web_login_link(user_id: int) -> str:
    """Одноразовая ссылка входа в веб через бота (deep-link `?start=weblogin`).
    Возвращает абсолютный URL `/auth/tg/<token>/`, действующий 5 минут."""
    close_old_connections()
    from django.conf import settings
    from blog.services.web_auth import issue_auth_token

    user = get_user(user_id)
    token = issue_auth_token(user)
    base = (settings.WEBAPP_URL or '').rstrip('/')
    return f'{base}/auth/tg/{token.token}/'

def verify_token_requester(token: str):
    """ФИО пользователя, инициировавшего подтверждение Telegram по токену (для текста
    «<ФИО> сейчас пытается подтвердить телеграм»). Возвращает (имя|None, ошибка|None)."""
    close_old_connections()
    from blog.services.telegram_verify import get_pending_token
    obj = get_pending_token(token)
    if obj is None:
        return None, 'invalid'
    u = obj.user
    name = (f'{u.last_name or ""} {u.first_name or ""}'.strip()) or u.telegram_username or f'#{u.id}'
    return name, None

def confirm_telegram_verification(token: str, telegram_id, telegram_username: str = None):
    """«Да, это я» из бота: верифицирует и привязывает telegram_id. (user, ошибка|None)."""
    close_old_connections()
    from blog.services.telegram_verify import confirm_verify_token
    return confirm_verify_token(token, telegram_id, telegram_username)

def reject_telegram_verification(token: str):
    """«Нет, это не я» из бота: гасит токен и разлогинивает инициатора. (user, ошибка|None)."""
    close_old_connections()
    from blog.services.telegram_verify import reject_verify_token
    return reject_verify_token(token)
