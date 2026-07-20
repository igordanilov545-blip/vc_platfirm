"""Сервисы бота: домен «comments». Часть пакета tg_bot.services (см. README.md).

Комментарии менеджера/ТЛ о пользователе (из бота).

Синхронные функции; хендлеры (async) зовут их через sync_to_async. Доступ к
данным — через data_controller (dc). Общие импорты — из ._common.
"""
from ._common import *  # noqa: F401,F403


def add_user_comment(user_id: int, target_user_id: int, text: str, event_id: int = None):
    """Внутренний комментарий волонтёру (tg-bot.md §5.4) — только по контексту правила 5."""
    close_old_connections()
    from blog.models import User, Event
    author = get_user(user_id)
    target = User.objects.filter(pk=target_user_id).first()
    if not target:
        return None, 'not_found'
    if not roles_service.has_extended_access_to_profile(author, target):
        return None, 'forbidden'
    event = Event.objects.filter(pk=event_id).first() if event_id else None
    comment = dc.create_user_comment(target_user=target, author=author, text=text, event=event)
    return comment, None
