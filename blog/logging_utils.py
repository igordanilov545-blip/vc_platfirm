"""Единая точка получения логгеров проекта (см. documentation/logging.md).

Три канала логов, разведённых по файлам через конфиг LOGGING в settings.py:

- WEB (`vc.web`)  — веб-приложение: вьюхи, сервисы, аутентификация. → logs/web.log
- BOT (`vc.bot`)  — Telegram-бот: хендлеры, диспетчер уведомлений.   → logs/bot.log
- DB  (`vc.db`)   — прямой слой доступа к данным (data_controller).  → logs/db.log

Использование:

    from blog.logging_utils import get_web_logger
    logger = get_web_logger(__name__)   # -> 'vc.web.blog.views'
    logger.info('...')

Имя модуля добавляется как суффикс, чтобы в логе было видно источник записи,
но канал (web/bot/db) определяется префиксом и потому попадает в нужный файл.
"""
import logging

WEB = 'vc.web'
BOT = 'vc.bot'
DB = 'vc.db'


def _logger_for(channel: str, name: str | None) -> logging.Logger:
    if not name:
        return logging.getLogger(channel)
    # Отрезаем ведущие пакеты, оставляя читаемый источник (blog.views, tg_bot.services…).
    return logging.getLogger(f'{channel}.{name}')


def get_web_logger(name: str | None = None) -> logging.Logger:
    """Логгер веб-канала (→ logs/web.log). `name` обычно `__name__`."""
    return _logger_for(WEB, name)


def get_bot_logger(name: str | None = None) -> logging.Logger:
    """Логгер бот-канала (→ logs/bot.log)."""
    return _logger_for(BOT, name)


def get_db_logger(name: str | None = None) -> logging.Logger:
    """Логгер канала прямого доступа к БД (→ logs/db.log)."""
    return _logger_for(DB, name)


def actor(user) -> str:
    """Единообразная краткая метка «кто совершил действие» для логов.

    Возвращает строку вида `user=42(ivan_petrov)` — id и, если известно, логин или
    telegram-username для читаемости. ПДн (ФИО, телефон) в лог не попадают.
    `user=anonymous` — для неаутентифицированного, `user=system` — для фоновых
    процессов/задач без явного инициатора, `user=?` — если объект не передан.
    """
    if user is None:
        return 'user=?'
    # Неаутентифицированный запрос (AnonymousUser).
    if getattr(user, 'is_authenticated', True) is False:
        return 'user=anonymous'
    uid = getattr(user, 'id', None) or getattr(user, 'pk', None)
    if uid is None:
        return 'user=?'
    handle = (
        getattr(user, 'login', None)
        or getattr(user, 'telegram_username', None)
        or getattr(user, 'system_username', None)
    )
    return f'user={uid}({handle})' if handle else f'user={uid}'
