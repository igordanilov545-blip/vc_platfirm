"""Сигналы, держащие динамические достижения в соответствии со справочниками.

Правило: «в таблице есть объект → есть и достижение под него; объект удалили →
достижение удалили». Реализуем через post_save/post_delete на EventCategory,
Organization, Event. Логика выдачи/подсчёта — в blog/services/achievements.py; здесь
только тонкая привязка к сигналам (подключается в BlogConfig.ready).

Забег (мероприятие, EventGroup): определение race_<id> заводится при создании,
выдаёт его движок достижений — хватает одной смены с явкой (2026-11-11).
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from blog.models import EventCategory, EventGroup, Organization
from blog.services import achievements as ach


@receiver(post_save, sender=EventCategory)
def _category_saved(sender, instance, **kwargs):
    ach.ensure_category_achievement(instance)


@receiver(post_delete, sender=EventCategory)
def _category_deleted(sender, instance, **kwargs):
    ach.remove_dynamic_achievement(f'category_{instance.id}')


@receiver(post_save, sender=Organization)
def _organization_saved(sender, instance, **kwargs):
    ach.ensure_organization_achievement(instance)


@receiver(post_delete, sender=Organization)
def _organization_deleted(sender, instance, **kwargs):
    ach.remove_dynamic_achievement(f'organization_{instance.id}')


@receiver(post_save, sender=EventGroup)
def _race_saved(sender, instance, created, **kwargs):
    # Определение под забег — при создании (и новый title при переименовании).
    ach.ensure_race_achievement(instance)


@receiver(post_delete, sender=EventGroup)
def _race_deleted(sender, instance, **kwargs):
    ach.remove_dynamic_achievement(f'race_{instance.id}')
