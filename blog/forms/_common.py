"""Общие импорты для доменных модулей пакета blog.forms.

Доменные файлы начинают с `from ._common import *` — получают `forms`, утилиты
времени и все модели, чтобы не дублировать шапку. `__all__` включает и имена без
подчёркивания (модели/утилиты) — для `import *`.
"""
from datetime import datetime, time

from django import forms
from django.utils import timezone

from blog.models import (
    Event, EventComment, EventShift, Participation, Application, UserComment, EventFeedback,
    Const, Manager, Season, Organization, Organizer, User, EventStaff, Location,
    EventCategory, EventCategoryMap, TeamLeader, ExternalExperience,
    EventRequirement, EventRequirementMap, UserRequirementException,
)

__all__ = [
    'datetime', 'time', 'forms', 'timezone',
    'Event', 'EventComment', 'EventShift', 'Participation', 'Application', 'UserComment',
    'EventFeedback', 'Const', 'Manager', 'Season', 'Organization', 'Organizer', 'User',
    'EventStaff', 'Location', 'EventCategory', 'EventCategoryMap', 'TeamLeader',
    'ExternalExperience', 'EventRequirement', 'EventRequirementMap', 'UserRequirementException',
]
