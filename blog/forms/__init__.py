"""Пакет форм платформы ВЦ (распил бывшего blog/forms.py).

Фасад обратной совместимости: весь код (в первую очередь `blog/views/_common.py`)
импортирует `from blog.forms import <ФормаForm>` — имена реэкспортируются здесь из
доменных модулей. Карта «домен → формы» — в README.md.
"""
from .auth import LoginForm, RegisterForm  # noqa: F401
from .references import (  # noqa: F401
    QuickLocationForm, LocationForm, QuickOrganizationForm, OrganizationForm,
    QuickOrganizerForm, OrganizerForm, QuickCategoryForm, CategoryForm,
    QuickRequirementForm, RequirementForm, RequirementEditForm, RequirementExceptionForm,
    ConstForm, SeasonForm,
)
from .events import (  # noqa: F401
    TeamLeadChoiceField, ManagerChoiceField, EventForm, EventShiftForm,
    EventCommentForm, EventFeedbackForm,
)
from .applications import (  # noqa: F401
    ShiftMultipleSelect, ApplicationForm, ApplicationCancelForm,
    ParticipationForm, ExcelImportForm,
)
from .profiles import (  # noqa: F401
    QuickVolunteerForm, ProfileForm, ProfileCompletionForm, ExternalExperienceForm, UserCommentForm,
)
from .roles import (  # noqa: F401
    CaptchaForm, MultipleHiddenIntegerField, RoleUsersForm,
)
