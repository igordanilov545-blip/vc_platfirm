"""Общие импорты для доменных модулей пакета tg_bot.services.

Доменные файлы начинают с `from ._common import *`. Здесь — то, что нужно многим:
data_controller (dc), утилиты Django/времени, общие сервисы, логгер.

Бизнес-модели (User/Application/EventShift/Participation/Event/ApplicationChangeLog)
идут через `dc` (data_controller). Прямой ORM оставлен ТОЛЬКО для инфраструктуры,
специфичной боту и не относящейся к бизнес-данным ВЦ: очереди `BotOutbox`/
`PendingButtonRemoval` (в `outbox.py`) и инвалидация Django-`Session` (в `users.py`) —
аналогично тому, как техническая аналитика не идёт через бизнес-контроллер.
"""
import re
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.utils import timezone

from data_base import data_controller as dc
from blog.models import BotOutbox
from blog.services import roles as roles_service
from blog.services.applications import process_application
from blog.services.notifications import notify_application_submitted
from blog.services.stats import is_pgas_star
from blog.logging_utils import get_bot_logger, actor

logger = get_bot_logger('tg_bot.services')

__all__ = [
    're', 'timedelta', 'Session', 'close_old_connections', 'timezone',
    'dc', 'BotOutbox', 'roles_service', 'process_application',
    'notify_application_submitted', 'is_pgas_star', 'actor', 'logger',
]
