"""Базовые ленивые queryset'ы для аналитики (отчёты) + скалярные срезы.

Отчёты (`blog/services/reports.py`, `report_exports.py`) строят тяжёлые агрегаты
(annotate/aggregate/сложные фильтры), которые невозможно и не нужно зашивать в
контроллер (он тонкий — coding-principles §1). Но и прямой `Model.objects` в сервисах
отчётов нарушает правило «доступ к данным — через контроллер» (agent-workflow §5).
Компромисс: контроллер отдаёт БАЗОВЫЕ ленивые queryset'ы (не list!), а бизнес-агрегация
остаётся в сервисе. Именование `*_qs`, чтобы отличать от материализующих `get_*`,
возвращающих list.
"""
from django.db.models import F
from django.utils import timezone

from blog.models import (
    Event, EventShift, Participation, Application, EventStaff, User,
    EventFeedback, Manager, TeamLeader, Season, DobroRuSharedLink,
    Location, Organization, Organizer, EventCategory, EventRequirement,
)


def events_qs():
    return Event.objects.all()


def event_shifts_qs():
    return EventShift.objects.all()


def participations_qs():
    return Participation.objects.all()


def applications_qs():
    return Application.objects.all()


def event_staff_qs():
    return EventStaff.objects.all()


def users_qs():
    return User.objects.all()


def users_ranked_qs(order: str = 'recent'):
    """Ленивый queryset пользователей для виджета выбора (data-select-remote="users"):
      - order='name'   — по алфавиту (фамилия, имя);
      - order='recent' (по умолчанию) — сначала кто был на меро недавно
        (last_event_at DESC), никогда не участвовавшие (NULL) — в самый конец.
    Срез/лимит и .count() навешивает вызывающая вьюха (users_picker_data)."""
    if order == 'name':
        return User.objects.order_by('last_name', 'first_name')
    return User.objects.order_by(F('last_event_at').desc(nulls_last=True), 'last_name', 'first_name')


def feedbacks_qs():
    return EventFeedback.objects.all()


def managers_qs():
    return Manager.objects.all()


def team_leaders_qs():
    return TeamLeader.objects.all()


def dobro_ru_shared_links_qs():
    return DobroRuSharedLink.objects.all()


# --- Справочники (list-вьюхи хаба настроек берут ленивый qs и сами сортируют/
#     навешивают select_related — тот же паттерн, что и для отчётов) ---
def locations_qs():
    return Location.objects.all()


def organizations_qs():
    return Organization.objects.all()


def organizers_qs():
    return Organizer.objects.all()


def event_categories_qs():
    return EventCategory.objects.all()


def requirements_qs():
    return EventRequirement.objects.all()


def get_current_season():
    """Текущий сезон (последний начавшийся) или None — для сезонных срезов отчётов."""
    return Season.objects.filter(start_season__lte=timezone.now().date()).order_by('-start_season').first()
