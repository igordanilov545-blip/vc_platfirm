"""Сигналы, держащие динамические достижения в соответствии со справочниками.

Правило: «в таблице есть объект → есть и достижение под него; объект удалили →
достижение удалили». Реализуем через post_save/post_delete на EventCategory,
Organization, Event. Логика выдачи/подсчёта — в blog/services/achievements.py; здесь
только тонкая привязка к сигналам (подключается в BlogConfig.ready).

Мероприятие: определение заводится при создании меро, но САМО достижение участникам
выдаётся при завершении меро (grant_event_participants из event_close), а не тут.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from blog.models import EventCategory, Organization, Event
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


@receiver(post_save, sender=Event)
def _event_saved(sender, instance, created, **kwargs):
    # Определение под меро заводим при создании (и обновляем title при переименовании).
    ach.ensure_event_achievement(instance)


@receiver(post_delete, sender=Event)
def _event_deleted(sender, instance, **kwargs):
    ach.remove_dynamic_achievement(f'event_{instance.id}')
