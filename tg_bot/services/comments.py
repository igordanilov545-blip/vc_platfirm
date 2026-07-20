"""Сервисы бота: домен «comments». Часть пакета tg_bot.services (см. README.md).

Комментарии менеджера/ТЛ о пользователе (из бота).

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403
from .users import get_user


def add_user_comment(user_id: int, target_user_id: int, text: str, event_id: int = None):
    """Внутренний комментарий волонтёру (tg-bot.md §5.4) — только по контексту правила 5."""
    close_old_connections()
    author = get_user(user_id)
    target = dc.get_user_by_id(target_user_id)
    if not target:
        return None, 'not_found'
    if not roles_service.has_extended_access_to_profile(author, target):
        return None, 'forbidden'
    event = dc.get_event_by_id(event_id) if event_id else None
    comment = dc.create_user_comment(target_user=target, author=author, text=text, event=event)
    return comment, None
