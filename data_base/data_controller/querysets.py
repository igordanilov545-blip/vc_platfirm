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
    Event, EventShift, Participation, Application, ApplicationShiftDecision, EventStaff, User,
    EventFeedback, Manager, TeamLeader, Season, DobroRuSharedLink,
    Location, Organization, Organizer, EventCategory, EventCategoryMap, EventPerk, EventRequirement,
    UserRequirementException, Incident, ChurnHistory, ApplicationChangeLog,
    UserComment, OrganizerInteractionLog,
    WebSession, WebPageView, ButtonClickEvent, BotSessionPing,
)


def events_qs():
    return Event.objects.all()


def event_shifts_qs():
    return EventShift.objects.all()


def participations_qs():
    return Participation.objects.all()


def applications_qs():
    return Application.objects.all()


def application_shift_decisions_qs():
    return ApplicationShiftDecision.objects.all()


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
    """Тематические категории забегов (kind=category): достижения, отчёты, чипы формы."""
    return EventCategory.objects.filter(kind='category')


def event_functions_qs():
    """Функции из ФиП (kind=function): у позиции одна, к ней привязан пул ролей."""
    return EventCategory.objects.filter(kind='function')


def event_category_maps_qs():
    """Связи позиция → функция пула (ленивый queryset)."""
    return EventCategoryMap.objects.all()


def event_perks_qs():
    return EventPerk.objects.all()


def requirements_qs():
    return EventRequirement.objects.all()


def seasons_qs():
    return Season.objects.all()


def user_requirement_exceptions_qs():
    return UserRequirementException.objects.all()


def incidents_qs():
    return Incident.objects.all()


def churn_history_qs():
    return ChurnHistory.objects.all()


def application_change_logs_qs():
    return ApplicationChangeLog.objects.all()


def user_comments_qs():
    return UserComment.objects.all()


def organizer_interactions_qs():
    return OrganizerInteractionLog.objects.all()


# --- Техническая аналитика (техадмин-дашборд нагрузки) ---
def web_sessions_qs():
    return WebSession.objects.all()


def web_page_views_qs():
    return WebPageView.objects.all()


def button_click_events_qs():
    return ButtonClickEvent.objects.all()


def bot_session_pings_qs():
    return BotSessionPing.objects.all()


def get_current_season():
    """Текущий сезон (последний начавшийся) или None — для сезонных срезов отчётов."""
    return Season.objects.filter(start_season__lte=timezone.localdate()).order_by('-start_season').first()
