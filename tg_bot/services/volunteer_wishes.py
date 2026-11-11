"""Табличка желающих из бота (documentation/volunteer-wishes.md).

Тонкая обёртка: разбор сообщения, ACL и запись — в blog/services/volunteer_wishes.py,
общем с вебом. Здесь только поиск пользователя по id и тексты ответа."""
from ._common import *  # noqa: F401,F403
from .users import get_user
from blog.services import volunteer_wishes as wishes_service


def can_add_volunteer_wishes(user_id: int) -> bool:
    close_old_connections()
    return wishes_service.can_manage_wishes(get_user(user_id))


def add_volunteer_wishes(user_id: int, text: str):
    """(строки, ошибка): 'forbidden' — не ТЛ/менеджер, 'no_people' — никого не нашли."""
    close_old_connections()
    return wishes_service.add_wishes_from_message(get_user(user_id), text, source='bot')


def undo_volunteer_wishes(user_id: int, batch_id: str):
    """«Отменить запись» — удалить строки одного сообщения (только автор)."""
    close_old_connections()
    return wishes_service.delete_wish_batch(get_user(user_id), batch_id)


def volunteer_wishes_summary(rows) -> str:
    lines = [f'✅ Записал в табличку желающих ({len(rows)}):']
    lines += [f'• {wishes_service.describe_wish(row)}' for row in rows]
    lines.append('\nНа странице мероприятия на сайте они появятся сами — по названию или датам.')
    return '\n'.join(lines)


def volunteer_wishes_web_link(user_id: int):
    """Ссылка с автологином на общую табличку (как attendance_web_link); None без HTTPS."""
    close_old_connections()
    from django.conf import settings
    from blog.services.web_auth import issue_auth_token

    base = (settings.WEBAPP_URL or '').rstrip('/')
    if not base.startswith('https://'):
        return None
    token = issue_auth_token(get_user(user_id))
    return f'{base}/auth/tg/{token.token}/?next=/wishes/%3Fstatus%3Dmine'
