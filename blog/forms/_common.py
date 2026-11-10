"""Общие импорты для доменных модулей пакета blog.forms.

Доменные файлы начинают с `from ._common import *` — получают `forms`, утилиты
времени и все модели, чтобы не дублировать шапку. `__all__` включает и имена без
подчёркивания (модели/утилиты) — для `import *`.
"""
from datetime import datetime, time

from django import forms
from django.utils import timezone

from data_base import data_controller as dc
from blog.models import (
    Event, EventComment, EventShift, Participation, Application, UserComment, EventFeedback,
    Const, Season, Organization, Organizer, User, Location,
    EventCategory, PositionTemplate, EventPerk, ExternalExperience, EventRequirement, UserRequirementException,
    ThankYouLetterTemplate, LetterFont,
)

# Модели остаются в импорте только для `ModelForm.Meta.model`, аннотаций и схемы полей
# форм (типы виджетов/полей). Любой доступ к данным (queryset'ы полей, запись M2M-связей,
# валидационные проверки) — через `dc` (data_controller), см. coding-principles §1–2.
__all__ = [
    'datetime', 'time', 'forms', 'timezone', 'dc',
    'Event', 'EventComment', 'EventShift', 'Participation', 'Application', 'UserComment',
    'EventFeedback', 'Const', 'Season', 'Organization', 'Organizer', 'User',
    'Location', 'EventCategory', 'PositionTemplate', 'EventPerk', 'ExternalExperience', 'EventRequirement', 'UserRequirementException',
    'ThankYouLetterTemplate', 'LetterFont',
]
