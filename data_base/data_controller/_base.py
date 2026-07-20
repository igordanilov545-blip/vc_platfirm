"""Общая инфраструктура слоя доступа к данным.

Здесь живёт то, что нужно всем доменным модулям пакета: логгер канала `vc.db`
(→ `logs/db.log`), хелпер `actor`, а также «универсальные» generic-функции
(`get_full_table`, `create_record_generic`) и карта имён таблиц.

См. `data_base/data_controller/README.md` и `documentation/logging.md`.
"""
from typing import Any, Dict, List

from blog.logging_utils import get_db_logger, actor
from blog.models import (
    User, Manager, TeamLeader, Organization, Organizer,
    OrganizerOrganizationLink, OrganizerInteractionLog, Location, EventCategory, Event,
    EventCategoryMap, EventShift, EventStaff, Application,
    Participation, ChurnHistory, UserComment, EventFeedback, EventRequirement,
    EventRequirementMap, UserRequirementException, Season, ThankYouLetterTemplate, Const,
    DobroRuSharedLink,
)

# Канал прямого доступа к данным (→ logs/db.log). Логируем изменяющие БД операции
# этого слоя — чтения (get_*) намеренно не логируем, чтобы не зашумлять файл.
# Во всех записях по возможности указываем «кто совершил действие» (actor) и
# «над кем/чем» (subject) — это аудиторский след изменений данных.
logger = get_db_logger('data_base.data_controller')


TABLE_MODEL_MAP: Dict[str, Any] = {
    'users': User,
    'managers': Manager,
    'team_leaders': TeamLeader,
    'organizations': Organization,
    'organizers': Organizer,
    'organizer_organization_link': OrganizerOrganizationLink,
    'organizer_interaction_log': OrganizerInteractionLog,
    'locations': Location,
    'event_categories': EventCategory,
    'events': Event,
    'event_category_map': EventCategoryMap,
    'event_shifts': EventShift,
    'event_staff': EventStaff,
    'applications': Application,
    'participations': Participation,
    'churn_history': ChurnHistory,
    'user_comments': UserComment,
    'event_feedbacks': EventFeedback,
    'event_requirements': EventRequirement,
    'event_requirement_map': EventRequirementMap,
    'user_requirement_exceptions': UserRequirementException,
    'seasons': Season,
    'thank_you_letter_templates': ThankYouLetterTemplate,
    'dobro_ru_shared_links': DobroRuSharedLink,
    'const': Const,
}


def get_full_table(table_name: str) -> List[Dict[str, Any]]:
    """Возвращает все записи таблицы в виде списка словарей."""
    model = TABLE_MODEL_MAP.get(table_name.lower())
    if not model:
        raise ValueError(f"Неизвестная таблица: '{table_name}'. Доступные: {list(TABLE_MODEL_MAP.keys())}")
    return list(model.objects.all().values())


def create_record_generic(table_name: str, **data) -> Any:
    """Универсальное создание записи (использовать с осторожностью)."""
    model = TABLE_MODEL_MAP.get(table_name.lower())
    if not model:
        raise ValueError(f"Неизвестная таблица: '{table_name}'")

    if model == User:
        if 'telegram_id' not in data:
            raise ValueError("Для создания пользователя обязательно поле telegram_id")
        obj = User.objects.create_user(**data)
        logger.info('INSERT %s (generic): pk=%s', table_name, obj.pk)
        return obj

    obj = model.objects.create(**data)
    logger.info('INSERT %s (generic): pk=%s', table_name, obj.pk)
    return obj
