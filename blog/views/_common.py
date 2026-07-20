"""Общий фундамент вьюх: shared-импорты, AJAX-хелперы, капча-2FA, healthz.

Доменные модули пакета `blog.views` начинают с `from ._common import *`, чтобы не
дублировать импорты и переиспользовать хелперы (`is_ajax`, `modal_form_response`,
captcha-2FA). Бизнес-логики здесь нет — только инфраструктура слоя представления.

См. `blog/views/README.md` — путеводитель «с чем работаешь → какой файл».
"""
import datetime
import random
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.core.validators import URLValidator
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from blog.decorators import manager_required, tech_admin_required
from blog.logging_utils import get_web_logger, actor
from data_base import data_controller as dc

# --- Модели (доменные вьюхи берут нужные им из общего набора) ---
from blog.models import (
    Application, ApplicationShiftDecision, Const, DobroRuSharedLink, Event, EventCategory,
    EventComment, EventShift, EventFeedback, EventStaff,
    EventRequirement, UserRequirementException,
    Location, Manager, Organization, Organizer, Participation, Season, TeamLeader, User,
    ButtonClickEvent, SystemDowntime, WebPageView, WebSession,
)

# --- Формы ---
from blog.forms import (
    ApplicationCancelForm, ApplicationForm, CategoryForm, ConstForm, EventCommentForm,
    EventShiftForm, EventFeedbackForm, EventForm,
    ExcelImportForm, ExternalExperienceForm, LocationForm, LoginForm, OrganizationForm,
    OrganizerForm, ProfileCompletionForm,
    ProfileForm, ParticipationForm, QuickCategoryForm, QuickLocationForm,
    QuickOrganizationForm, QuickOrganizerForm,
    QuickRequirementForm, QuickVolunteerForm, RegisterForm, RequirementForm,
    RequirementEditForm, RequirementExceptionForm,
    RoleUsersForm, SeasonForm, UserCommentForm,
)

# --- Сервисы ---
from blog.services import import_applications as import_service
from blog.services import notifications as notifications_service
from blog.services import reports as reports_service
from blog.services import report_exports
from blog.services.applications import (
    can_cancel_application, cancel_application, event_closing_checklist, process_application,
)
from blog.services import roles as roles_service
from blog.services.roles import (
    account_is_complete, account_missing_fields, can_process_applications,
    has_extended_access_to_profile, is_manager, is_team_leader, role_label,
)
from blog.services.stats import recalc_user_aggregates
from blog.services import charts as charts_service
from blog.services import event_timeline as event_timeline_service
from blog.services import organization_report as organization_report_service
from blog.services import person_report as person_report_service
from blog.services import volunteers_report as volunteers_report_service
from blog.services import report_builders as report_builders_service
from blog.services.docx_report import docx_response

logger = get_web_logger('blog.views')

# Готовые значения для datalist поля «Нужно волонтёров» (EventShiftForm) — можно
# выбрать число из списка или ввести своё вручную.
VOLUNTEER_NEEDED_OPTIONS = range(1, 201)


def is_ajax(request) -> bool:
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def healthz(request):
    """Liveness/readiness-проба для Docker/оркестратора: 200, если процесс жив и БД
    отвечает; 503 иначе. Без аутентификации и без обращения к тяжёлым сервисам —
    только быстрый SELECT 1, чтобы healthcheck был дешёвым."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'db_unavailable'}, status=503)


def modal_form_response(request, template_name, context, *, success_redirect=None, partial_template=None):
    """Рендерит форму для AJAX-модалки/bottom sheet (`base.html`, `modal.js`).

    - AJAX + успешный POST → JSON {"redirect": url} — модалка закрывается, страница переходит.
    - AJAX + GET/невалидный POST → только partial формы (без сайдбара/base.html).
    - Не-AJAX → обычное поведение (полная страница/redirect), как без JS.

    `partial_template` — кастомный partial для форм с доп. разметкой (напр. quick-add панели
    в event_form); по умолчанию используется общий `_modal_form.html`.
    """
    if success_redirect is not None:
        if is_ajax(request):
            return JsonResponse({'redirect': success_redirect})
        return redirect(success_redirect)

    if is_ajax(request):
        return render(request, partial_template or 'blog/partials/_modal_form.html', context)
    return render(request, template_name, context)


def _safe_next(request, default='dashboard'):
    """Возвращает безопасный URL для редиректа после входа: только относительный
    путь того же сайта (защита от open-redirect), иначе — дефолтный маршрут."""
    from django.utils.http import url_has_allowed_host_and_scheme

    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return reverse(default)


def _referer_or(request, default='dashboard'):
    """Страница, с которой пришёл AJAX-запрос модалки (HTTP_REFERER) — используется как
    success_redirect для форм, открытых поверх карточки меро/профиля (заявка подана/
    изменена/отменена), чтобы после сабмита модалка закрылась ОБНОВЛЕНИЕМ ТОЙ ЖЕ
    страницы, а не переходом на dashboard: пользователь должен остаться там, где был,
    и увидеть актуальное состояние (кнопка сменилась на «Моя заявка» и т.п.).
    Referer проверяется так же строго, как next в _safe_next (защита от open-redirect)."""
    from django.utils.http import url_has_allowed_host_and_scheme

    referer = request.META.get('HTTP_REFERER')
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return referer
    return reverse(default)


# ---------------------------------------------------------------------------
# Капча-2FA: переиспользуемое подтверждение опасных действий
# ---------------------------------------------------------------------------

def _new_captcha(request, session_key='captcha_answer'):
    x = random.randint(-10, 10)
    y = random.randint(-10, 10)
    request.session[session_key] = x + y
    return f'{x} + ({y})' if y < 0 else f'{x} + {y}'


def _check_captcha(request, session_key, answer_raw):
    expected = request.session.pop(session_key, None)
    try:
        return expected is not None and int(answer_raw) == expected
    except (TypeError, ValueError):
        return False


def render_captcha_modal(request, *, session_key, action_url, confirm_text=None,
                         submit_label='Подтвердить', extra_hidden=None, title='Подтверждение',
                         reason_field=False, reason_label='Причина'):
    """Отдаёт переиспользуемое окно капчи-2FA (partials/_captcha_confirm.html) в модалку.
    Генерирует новый пример x+y и кладёт ответ в сессию под session_key. Используется
    для «двухфакторного» подтверждения опасных действий (удаление меро, редактирование
    завершённого меро, блокировка волонтёра и т.п.) — см. _captcha_confirm.html.

    `reason_field=True` добавляет обязательное текстовое поле `reason` в форму (напр.
    для блокировки волонтёра, где причина должна быть зафиксирована)."""
    context = {
        'captcha_question': _new_captcha(request, session_key),
        'action_url': action_url,
        'confirm_text': confirm_text,
        'submit_label': submit_label,
        'extra_hidden': extra_hidden or [],
        'title': title,
        'reason_field': reason_field,
        'reason_label': reason_label,
    }
    if is_ajax(request):
        return render(request, 'blog/partials/_captcha_confirm.html', context)
    # Не-AJAX (прямой переход на страницу, напр. «Редактировать завершённое меро») —
    # полностраничная версия того же окна капчи (captcha_page.html).
    return render(request, 'blog/captcha_page.html', context)


# Явный публичный интерфейс модуля для `from ._common import *` в доменных вьюхах.
# Включаем и приватные хелперы (_safe_next и т.п.): при наличии __all__ `import *`
# переносит и имена с подчёркиванием, поэтому доменным файлам не нужно тянуть их вручную.
__all__ = [
    # инфраструктура представления
    'is_ajax', 'healthz', 'modal_form_response', '_safe_next', '_referer_or',
    '_new_captcha', '_check_captcha', 'render_captcha_modal',
    'VOLUNTEER_NEEDED_OPTIONS', 'logger', 'actor',
    # data controller + декораторы
    'dc', 'manager_required', 'tech_admin_required',
    # django
    'datetime', 'random', 'Path', 'quote', 'settings', 'messages',
    'authenticate', 'auth_login', 'auth_logout', 'login_required',
    'PermissionDenied', 'ValidationError', 'Paginator', 'URLValidator',
    'Avg', 'Count', 'Q', 'FileResponse', 'Http404', 'HttpResponseForbidden',
    'JsonResponse', 'get_object_or_404', 'redirect', 'render', 'reverse',
    'timezone', 'csrf_exempt', 'require_POST',
    # модели
    'Application', 'ApplicationShiftDecision', 'Const', 'DobroRuSharedLink', 'Event',
    'EventCategory', 'EventComment', 'EventShift', 'EventFeedback', 'EventStaff',
    'EventRequirement', 'UserRequirementException', 'Location', 'Manager',
    'Organization', 'Organizer', 'Participation', 'Season', 'TeamLeader', 'User',
    'ButtonClickEvent', 'SystemDowntime', 'WebPageView', 'WebSession',
    # формы
    'ApplicationCancelForm', 'ApplicationForm', 'CategoryForm', 'ConstForm',
    'EventCommentForm', 'EventShiftForm', 'EventFeedbackForm', 'EventForm',
    'ExcelImportForm', 'ExternalExperienceForm', 'LocationForm', 'LoginForm',
    'OrganizationForm', 'OrganizerForm', 'ProfileCompletionForm', 'ProfileForm',
    'ParticipationForm', 'QuickCategoryForm', 'QuickLocationForm', 'QuickOrganizationForm',
    'QuickOrganizerForm', 'QuickRequirementForm', 'QuickVolunteerForm', 'RegisterForm',
    'RequirementForm', 'RequirementEditForm', 'RequirementExceptionForm', 'RoleUsersForm',
    'SeasonForm', 'UserCommentForm',
    # сервисы
    'import_service', 'notifications_service', 'reports_service', 'report_exports',
    'can_cancel_application', 'cancel_application', 'event_closing_checklist',
    'process_application', 'roles_service', 'account_is_complete', 'account_missing_fields',
    'can_process_applications', 'has_extended_access_to_profile', 'is_manager',
    'is_team_leader', 'role_label', 'recalc_user_aggregates', 'charts_service',
    'event_timeline_service', 'organization_report_service', 'person_report_service',
    'volunteers_report_service', 'report_builders_service', 'docx_response',
]
