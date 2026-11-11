"""Общие импорты для доменных модулей пакета tg_bot.services.

Доменные файлы начинают с `from ._common import *`. Здесь — то, что нужно многим:
data_controller (dc), утилиты Django/времени, общие сервисы, логгер.

Все модели (бизнес и инфраструктура бота — очереди `BotOutbox`/`PendingButtonRemoval`,
Django-`Session`) идут через `dc` (data_controller): весь доступ к БД собран в одном
слое, включая транспорт уведомлений и техническую аналитику.
"""
import re
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone

from data_base import data_controller as dc
from blog.services import roles as roles_service
from blog.services.applications import process_application
from blog.services.notifications import notify_application_submitted
from blog.logging_utils import get_bot_logger, actor

logger = get_bot_logger('tg_bot.services')

__all__ = [
    're', 'timedelta', 'close_old_connections', 'timezone',
    'dc', 'roles_service', 'process_application',
    'notify_application_submitted', 'actor', 'logger',
]
