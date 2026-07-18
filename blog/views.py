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
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from blog.decorators import manager_required, tech_admin_required
from blog.forms import (
    ApplicationCancelForm, ApplicationForm, ConstForm, EventCommentForm, EventShiftForm, EventFeedbackForm, EventForm,
    ExcelImportForm, ExternalExperienceForm, LocationForm, LoginForm, OrganizationForm, OrganizerForm, ProfileCompletionForm,
    ProfileForm, ParticipationForm, QuickCategoryForm, QuickLocationForm, QuickOrganizationForm, QuickOrganizerForm,
    QuickRequirementForm, QuickVolunteerForm, RegisterForm, RequirementForm, RequirementEditForm, RequirementExceptionForm,
    RoleUsersForm, SeasonForm, UserCommentForm,
)
from blog.models import (
    Application, ApplicationShiftDecision, Const, DobroRuSharedLink, Event, EventCategory, EventComment, EventShift, EventFeedback, EventStaff,
    EventRequirement, UserRequirementException,
    Location, Manager, Organization, Organizer, Participation, Season, TeamLeader, User,
)
from blog.services import import_applications as import_service
from blog.services import notifications as notifications_service
from blog.services import reports as reports_service
from blog.services import report_exports
from blog.services.applications import (
    can_cancel_application, cancel_application, event_closing_checklist, process_application,
)
from blog.services import roles as roles_service
from blog.services.roles import (
    account_is_complete, account_missing_fields, can_process_applications, has_extended_access_to_profile,
    is_manager, is_team_leader, role_label,
)
from blog.services.stats import recalc_user_aggregates
from blog.services import charts as charts_service
from blog.services import event_timeline as event_timeline_service
from blog.services import organization_report as organization_report_service
from blog.services import person_report as person_report_service
from blog.services import volunteers_report as volunteers_report_service
from blog.services import report_builders as report_builders_service
from blog.services.docx_report import docx_response
from blog.services import analytics as analytics_service
from blog.models import ButtonClickEvent, SystemDowntime, WebPageView, WebSession
from blog.logging_utils import get_web_logger, actor

logger = get_web_logger(__name__)

# Готовые значения для datalist поля «Нужно волонтёров» (EventShiftForm) — можно
# выбрать число из списка или ввести своё вручную.
VOLUNTEER_NEEDED_OPTIONS = range(1, 201)


# ---------------------------------------------------------------------------
# AJAX-модалка/bottom sheet: общий хелпер для форм создания/редактирования
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Быстрое создание справочников прямо из формы мероприятия (без ухода со страницы)
# ---------------------------------------------------------------------------

@manager_required
def quick_create_location(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    form = QuickLocationForm(request.POST)
    if form.is_valid():
        location = form.save()
        return JsonResponse({'id': location.id, 'label': location.name})
    return JsonResponse({'errors': form.errors}, status=400)


@manager_required
def quick_create_organization(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    form = QuickOrganizationForm(request.POST)
    if form.is_valid():
        organization = form.save()
        return JsonResponse({'id': organization.id, 'label': organization.name})
    return JsonResponse({'errors': form.errors}, status=400)


@manager_required
def quick_create_organizer(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    form = QuickOrganizerForm(request.POST)
    if form.is_valid():
        organizer = form.save()
        label = f'{organizer.first_name} {organizer.last_name}'.strip()
        return JsonResponse({'id': organizer.id, 'label': label})
    return JsonResponse({'errors': form.errors}, status=400)


@manager_required
def quick_create_category(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    form = QuickCategoryForm(request.POST)
    if form.is_valid():
        category = form.save()
        return JsonResponse({'id': category.id, 'label': category.name})
    return JsonResponse({'errors': form.errors}, status=400)


@manager_required
def quick_create_volunteer(request):
    """Быстрое создание волонтёра прямо из виджета выбора (data-add-ref-picker) — новый
    пользователь сразу попадает в пул выбранных в текущей форме (напр. «Добавить
    заявки»), без отдельного одноразового сабмита всей формы (см. create_volunteer_by_name)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    from blog.services.applications import create_volunteer_by_name

    form = QuickVolunteerForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        user = create_volunteer_by_name(
            data['first_name'], data['last_name'],
            phone=data['phone'], telegram_username=data['telegram_username'],
        )
        return JsonResponse({'id': user.id, 'label': user.full_name})
    return JsonResponse({'errors': form.errors}, status=400)


@manager_required
def quick_create_requirement(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    form = QuickRequirementForm(request.POST)
    if form.is_valid():
        requirement = form.save()
        return JsonResponse({'id': requirement.id, 'label': requirement.title})
    return JsonResponse({'errors': form.errors}, status=400)


# ---------------------------------------------------------------------------
# Аутентификация
# ---------------------------------------------------------------------------

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


def _post_tg_login_redirect(request, user):
    """Куда отправить пользователя сразу после входа через Telegram. Если аккаунт
    ещё не «заполнен» (нет ФИО) — на дозаполнение профиля, сохранив исходный next,
    чтобы после заполнения вернуть человека туда, куда он шёл (напр. подача заявки)."""
    target = _safe_next(request)
    if not account_is_complete(user):
        return reverse('complete_profile') + f'?next={quote(target)}'
    return target


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    from django.conf import settings

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request,
            login=form.cleaned_data['login'],
            password=form.cleaned_data['password'],
        )
        if user is not None:
            auth_login(request, user)
            logger.info('Веб-вход по логину/паролю успешен: user=%s login=%s', user.id, user.login)
            return redirect(_safe_next(request))
        logger.warning('Неудачная попытка веб-входа: login=%r', form.cleaned_data.get('login'))
        messages.error(request, 'Неверный логин или пароль.')

    return render(request, 'blog/login.html', {
        'form': form,
        'next': request.GET.get('next', ''),
        'tg_bot_username': settings.TG_BOT_USERNAME,
        # Абсолютный URL коллбэка Login Widget — Telegram шлёт данные на data-auth-url.
        'tg_widget_auth_url': request.build_absolute_uri(reverse('telegram_login_callback')),
    })


def register_view(request):
    """Самостоятельная веб-регистрация без Telegram (см. RegisterForm docstring и
    coding-principles.md §3 — правило "аккаунт всегда через telegram_id" ослаблено:
    веб-регистрация создаёт аккаунт со служебным telegram_id `web_register:<uuid>`,
    как import:* у Excel-импорта, до подтверждения через бота.

    Если находится совпадение по ФИО/Telegram/телефону с уже существующим
    пользователем — не блокируем, создаём новый аккаунт и после входа показываем
    плашку с просьбой подтвердить личность через бота (см. dashboard, messages)."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    from blog.services.applications import find_matching_user
    import uuid as uuid_lib

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        existing = find_matching_user(
            telegram_username=data['telegram_username'], phone=data['phone'],
            first_name=data['first_name'], last_name=data['last_name'],
        )
        user = User.objects.create_user(
            telegram_id=f'web_register:{uuid_lib.uuid4()}',
            first_name=data['first_name'], last_name=data['last_name'], middle_name=data['middle_name'],
            telegram_username=data['telegram_username'], phone=data['phone'], birthday=data['birthday'],
            login=data['login'],
        )
        user.set_password(data['password'])
        user.web_credentials_set_at = timezone.now()
        user.save()
        logger.info('Веб-регистрация: создан user=%s login=%s matched_existing=%s', user.id, user.login, existing.id if existing else None)

        auth_login(request, user, backend='blog.auth_backends.WebLoginBackend')
        if existing:
            from django.conf import settings
            messages.warning(
                request,
                'Мы нашли похожий профиль в системе (по ФИО/Telegram/телефону). '
                'Чтобы объединить историю мероприятий с этим аккаунтом, подтвердите себя '
                f'через Telegram-бота: https://t.me/{settings.TG_BOT_USERNAME}',
            )
        messages.success(request, 'Регистрация завершена. Добро пожаловать!')
        return redirect('dashboard')

    return render(request, 'blog/register.html', {'form': form})


@csrf_exempt
def telegram_login_callback(request):
    """Коллбэк Telegram Login Widget (браузерный вход вне Mini App): виджет
    редиректит сюда с подписанными полями пользователя. Проверяем HMAC и логиним.

    `csrf_exempt` по тем же причинам, что и `webapp_auth`: подлинность подтверждается
    подписью Telegram, а не CSRF-токеном (у клиента ещё нет сессии)."""
    from blog.services.telegram_auth import validate_login_widget
    from data_base import data_controller as dc

    data = {k: v for k, v in request.GET.items() if k != 'next'}
    payload = validate_login_widget(data)
    if not payload or not payload.get('id'):
        logger.warning('Login Widget: не удалось подтвердить подпись Telegram.')
        messages.error(request, 'Не удалось подтвердить вход через Telegram. Попробуйте ещё раз.')
        return redirect('login')

    user, created = dc.get_or_create_user_by_telegram_id(
        payload['id'], payload.get('username'),
        first_name=payload.get('first_name'), last_name=payload.get('last_name'),
    )
    if user.status == 'blacklisted':
        logger.warning('Login Widget: вход заблокированного пользователя отклонён user=%s', user.id)
        messages.error(request, 'Доступ ограничен — обратитесь к менеджеру центра.')
        return redirect('login')

    auth_login(request, user, backend='blog.auth_backends.TelegramWebAppBackend')
    logger.info('Веб-вход через Telegram Login Widget: user=%s created=%s', user.id, created)
    return redirect(_post_tg_login_redirect(request, user))


@login_required
def profile_edit(request):
    """Личный кабинет → «Редактировать»: пользователь правит свои данные (ФИО, юзернейм
    для системы, ТГ, телефон, почта, дата рождения, о себе, ВК). Полноценная страница
    (не модалка), чтобы корректно работать и как точка дозаполнения профиля перед
    подачей заявки. Обязательные для заявки поля (ФИО, ТГ, телефон) помечены в форме.

    `next` сохраняется сквозь сабмит: если пользователь пришёл сюда с попытки подать
    заявку, после сохранения его вернёт туда же."""
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    was_complete = account_is_complete(request.user)

    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        # Если пользователь изменил верифицированные менеджером поля (ФИО/ОП/
        # факультет/год/TG) — снимаем верификацию ПГАС: справку на новых данных не
        # выдаём, менеджер должен подтвердить заново (см. pgas_certificate).
        from blog.services.pgas_certificate import revoke_verification_if_changed
        if revoke_verification_if_changed(request.user):
            messages.info(request, 'Данные изменены — верификация для справки ПГАС снята, '
                                   'потребуется повторное подтверждение менеджером.')
        if account_is_complete(request.user):
            if not was_complete:
                messages.success(request, 'Профиль заполнен — теперь можно подавать заявки.')
            else:
                messages.success(request, 'Профиль обновлён.')
            # Возврат туда, откуда пришли (напр. на страницу мероприятия для подачи заявки).
            if next_url:
                from django.utils.http import url_has_allowed_host_and_scheme
                if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                    return redirect(next_url)
            return redirect('profile_detail', user_id=request.user.id)
        else:
            missing = ', '.join(account_missing_fields(request.user))
            messages.warning(request, f'Чтобы подавать заявки, заполните: {missing}.')

    return render(request, 'blog/profile_edit.html', {
        'form': form,
        'next': next_url,
        'missing_fields': account_missing_fields(request.user),
    })


# Обратная совместимость по имени маршрута/вьюхи.
complete_profile = profile_edit


@login_required
@require_POST
def verify_telegram_start(request):
    """ЛК → «Подтвердить телеграм»: создаём одноразовый токен и уводим пользователя в
    бота по deep-link `?start=verify_<token>`. Дальнейшее — в боте (подтверждение да/нет),
    см. blog.services.telegram_verify и хендлер common.cmd_start."""
    from blog.services.telegram_verify import issue_verify_token

    bot_username = (settings.TG_BOT_USERNAME or '').lstrip('@')
    if not bot_username:
        messages.error(request, 'Бот не сконфигурирован — обратитесь к менеджеру центра.')
        return redirect('profile_edit')

    token = issue_verify_token(request.user)
    deep_link = f'https://t.me/{bot_username}?start=verify_{token.token}'
    logger.info('Запущено подтверждение Telegram из ЛК: user=%s', request.user.id)
    return redirect(deep_link)


def _build_certificate_pdf(user, events, period_label):
    """Общий хвост генерации справки: рендер загруженного .docx-шаблона (с
    сохранением оформления) → LibreOffice в PDF → «картиночный» PDF. Возвращает
    (pdf_bytes, filename). Используется и волонтёрской, и менеджерской вьюхой (одно
    правило генерации — одно место)."""
    from django.utils.text import slugify

    from blog.services.pgas_certificate import render_docx
    from blog.services.pgas_pdf import certificate_pdf_from_docx

    docx_bytes = render_docx(user, events, period_label=period_label)
    pdf_bytes = certificate_pdf_from_docx(docx_bytes)
    filename = f'pgas-{slugify(user.full_name) or user.id}.pdf'
    return pdf_bytes, filename


@login_required
@require_POST
def pgas_certificate_download(request):
    """«Получить справку на ПГАС» (волонтёр на себя). Охват — за сезон (scope=season,
    по умолчанию) или за всё время (scope=all). Условия проверяются (кнопка иначе
    недоступна, но дублируем на бэке). Пайплайн — HTML→WeasyPrint→растр в PDF-картинку
    (blog/services/pgas_pdf.py). Проверяется на проде (локально WeasyPrint нет)."""
    from blog.services.pgas_certificate import (
        collect_events, pgas_certificate_eligibility, season_range,
    )
    from blog.services.pgas_pdf import certificate_response

    result = pgas_certificate_eligibility(request.user)
    if not result['eligible']:
        messages.error(request, f'Не хватает: {", ".join(result["missing"])}.')
        return redirect('profile_detail', user_id=request.user.id)

    scope = request.POST.get('scope', 'season')
    if scope == 'all':
        events = collect_events(request.user)
        period_label = 'всё время'
    else:
        date_from, date_to = season_range()
        events = collect_events(request.user, date_from=date_from, date_to=date_to)
        period_label = 'текущий сезон'

    try:
        pdf_bytes, filename = _build_certificate_pdf(request.user, events, period_label)
    except Exception:
        logger.exception('Ошибка генерации справки ПГАС: user=%s', request.user.id)
        messages.error(request, 'Не удалось сгенерировать справку. Попробуйте позже.')
        return redirect('profile_detail', user_id=request.user.id)

    logger.info('Справка ПГАС выдана: user=%s scope=%s events=%s', request.user.id, scope, len(events))
    return certificate_response(pdf_bytes, filename)


@manager_required
def pgas_certificate_issue(request, user_id):
    """Менеджер выдаёт справку на выбранного волонтёра: диапазон дат + выбор
    мероприятий (из тех, на которых волонтёр был). GET — форма (список мероприятий
    за диапазон), POST — генерация PDF. Имя в справке — из выбранного пользователя
    (менеджер может выдать на любого)."""
    from blog.services.pgas_certificate import collect_events
    from blog.services.pgas_pdf import certificate_response

    target = get_object_or_404(User, pk=user_id)

    def _parse_date(name):
        raw = (request.POST.get(name) or request.GET.get(name) or '').strip()
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            return None

    date_from = _parse_date('date_from')
    date_to = _parse_date('date_to')

    if request.method == 'POST' and request.POST.get('generate'):
        selected_ids = [int(x) for x in request.POST.getlist('event_ids') if x.isdigit()]
        events = collect_events(
            target, date_from=date_from, date_to=date_to,
            event_ids=selected_ids or None,
        )
        if not events:
            messages.error(request, 'Не выбрано ни одного мероприятия с участием.')
            return redirect('pgas_certificate_issue', user_id=target.id)
        if date_from and date_to:
            period_label = f'{date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}'
        else:
            period_label = 'всё время'
        try:
            pdf_bytes, filename = _build_certificate_pdf(target, events, period_label)
        except Exception:
            logger.exception('Ошибка генерации справки ПГАС менеджером: target=%s', target.id)
            messages.error(request, 'Не удалось сгенерировать справку. Попробуйте позже.')
            return redirect('pgas_certificate_issue', user_id=target.id)
        logger.info('Справка ПГАС выдана менеджером: target=%s by=%s events=%s',
                    target.id, actor(request.user), len(events))
        return certificate_response(pdf_bytes, filename)

    # GET / выбор диапазона — показываем доступные мероприятия за диапазон.
    available = collect_events(target, date_from=date_from, date_to=date_to)
    return render(request, 'blog/pgas_certificate_issue.html', {
        'target': target,
        'available_events': available,
        'date_from': date_from,
        'date_to': date_to,
    })


@manager_required
def pgas_template_download(request):
    """Скачать текущий .docx-шаблон справки (чтобы менеджер отредактировал его в
    Word и загрузил обратно)."""
    from django.http import HttpResponse

    from blog.services.pgas_certificate import get_template

    template = get_template()
    response = HttpResponse(
        bytes(template.docx_file),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="{template.filename or "pgas_template.docx"}"'
    return response


@login_required
@require_POST
def pgas_request_verification(request):
    """«Запросить верификацию» — профиль полностью заполнен, не хватает только
    ручного подтверждения менеджером; создаёт инцидент в разделе «Главное»."""
    from blog.services.pgas_certificate import only_verification_missing
    from blog.services.incidents import create_incident

    if not only_verification_missing(request.user):
        messages.error(request, 'Сначала заполните профиль полностью.')
        return redirect('profile_detail', user_id=request.user.id)

    create_incident(
        'pgas_verification',
        f'«{request.user.full_name}» запросил(а) верификацию для справки ПГАС.',
        related_user=request.user,
    )
    messages.success(request, 'Заявка на верификацию отправлена менеджеру.')
    return redirect('profile_detail', user_id=request.user.id)


@manager_required
@require_POST
def pgas_verify_user(request, user_id):
    """Менеджер подтверждает верификацию волонтёра для справки ПГАС — с чужого
    профиля. Резолвит связанный инцидент `pgas_verification`, если он есть."""
    from blog.models import Incident

    from blog.services.pgas_certificate import snapshot_verified_fields

    target = get_object_or_404(User, pk=user_id)
    target.verified_by_manager_at = timezone.now()
    target.verified_by_manager_by = request.user
    # Снимок верифицированных значений — чтобы потом отследить именно их изменение
    # (перевод на другую ОП, смену ФИО и т.п.) и снять верификацию.
    target.verified_snapshot = snapshot_verified_fields(target)
    target.save(update_fields=['verified_by_manager_at', 'verified_by_manager_by', 'verified_snapshot'])

    Incident.objects.filter(
        kind='pgas_verification', related_user=target, resolved_at__isnull=True,
    ).update(resolved_at=timezone.now(), resolved_by=request.user)

    logger.info('Верификация для ПГАС подтверждена: user=%s by=%s', target.id, actor(request.user))
    messages.success(request, f'«{target.full_name}» верифицирован(а) для справки ПГАС.')
    return redirect('profile_detail', user_id=target.id)


@manager_required
@require_POST
def pgas_unverify_user(request, user_id):
    """Отзыв верификации для справки ПГАС — симметрично выдаче (без капчи: это
    возврат в исходное состояние, а не запуск нового необратимого процесса)."""
    target = get_object_or_404(User, pk=user_id)
    target.verified_by_manager_at = None
    target.verified_by_manager_by = None
    target.verified_snapshot = None
    target.save(update_fields=['verified_by_manager_at', 'verified_by_manager_by', 'verified_snapshot'])

    logger.info('Верификация для ПГАС отозвана: user=%s by=%s', target.id, actor(request.user))
    messages.success(request, f'Верификация «{target.full_name}» для справки ПГАС отозвана.')
    return redirect('profile_detail', user_id=target.id)


@manager_required
def user_blacklist(request, user_id):
    """Ручная блокировка волонтёра менеджером — двухфакторное подтверждение (капча
    x+y) и обязательная причина, как и другие необратимые/чувствительные действия
    (event_delete). Причина сохраняется в User.comment (внутреннее поле, видно только
    менеджеру). Пользователь НЕ уведомляется о блокировке."""
    target = get_object_or_404(User, pk=user_id)
    session_key = f'captcha_user_blacklist_{target.id}'

    if request.method == 'POST':
        reason = (request.POST.get('reason') or '').strip()
        if not reason:
            messages.error(request, 'Укажите причину блокировки.')
            return redirect('profile_detail', user_id=target.id)
        if not _check_captcha(request, session_key, request.POST.get('captcha_answer')):
            messages.error(request, 'Неверный ответ на пример — блокировка отменена. Попробуйте ещё раз.')
            return modal_form_response(request, None, None, success_redirect=reverse('profile_detail', args=[target.id]))

        target.status = 'blacklisted'
        target.comment = reason
        target.save(update_fields=['status', 'comment'])
        logger.info('Волонтёр внесён в чёрный список: user=%s by=%s reason=%r', target.id, actor(request.user), reason)
        messages.success(request, f'«{target.full_name}» внесён(а) в чёрный список.')
        return modal_form_response(request, None, None, success_redirect=reverse('profile_detail', args=[target.id]))

    return render_captcha_modal(
        request,
        session_key=session_key,
        action_url=reverse('user_blacklist', args=[target.id]),
        confirm_text=f'Внести «{target.full_name}» в чёрный список? Пользователь не будет уведомлён об этом.',
        submit_label='Внести в чёрный список',
        title=f'Блокировка: {target.full_name}',
        reason_field=True,
        reason_label='Причина блокировки (обязательно)',
    )


def tg_link_login(request, token):
    """Вход по одноразовой ссылке из бота (deep-link `?start=weblogin`): проверяем
    токен (не использован и не старше 5 минут), логиним и гасим токен."""
    from blog.services.web_auth import consume_auth_token

    user = consume_auth_token(str(token))
    if user is None:
        messages.error(request, 'Ссылка для входа недействительна или устарела. Запросите новую в боте.')
        return redirect('login')
    if user.status == 'blacklisted':
        messages.error(request, 'Доступ ограничен — обратитесь к менеджеру центра.')
        return redirect('login')

    auth_login(request, user, backend='blog.auth_backends.TelegramWebAppBackend')
    return redirect(_post_tg_login_redirect(request, user))


def logout_view(request):
    auth_logout(request)
    return redirect('login')


# ---------------------------------------------------------------------------
# Публичный (гостевой) контур — просмотр опубликованных мероприятий без входа
# и публичная страница волонтёрского опыта (раздел 2 и 4).
# ---------------------------------------------------------------------------

def _published_active_events():
    """Опубликованные и ещё не завершённые мероприятия (для гостевого списка и
    списка активных). Сортировка — ближайшие предстоящие/идущие сверху."""
    events = list(
        Event.objects.filter(published_at__isnull=False)
        .exclude(event_status='finished')
        .select_related('location')
        .prefetch_related('shifts')
    )
    rows = []
    for event in events:
        if event.compute_status() in ('passed', 'finished'):
            continue
        days = sorted(s.day for s in event.shifts.all())
        event.first_day = days[0] if days else None
        event.last_day = days[-1] if days else None
        rows.append(event)
    rows.sort(key=lambda e: (e.first_day is None, e.first_day or datetime.date.max))
    return rows


def public_event_list(request):
    """Гостевой список идущих/предстоящих мероприятий — без входа. Кнопка «Подать
    заявку» на карточке ведёт на вход (заявку подаёт только авторизованный)."""
    return render(request, 'blog/public_event_list.html', {
        'events': _published_active_events(),
        'is_public': True,
    })


def public_event_detail(request, token):
    """Публичная витрина мероприятия по ссылке «Поделиться» — read-only, без входа.
    Доступна только для опубликованного меро."""
    event = get_object_or_404(
        Event.objects.select_related('location', 'organization'),
        public_token=token, published_at__isnull=False,
    )
    shifts = list(event.shifts.select_related('location').order_by('day'))
    return render(request, 'blog/public_event_detail.html', {
        'event': event,
        'shifts': shifts,
        'is_public': True,
        # После входа вернуть человека на подачу заявки именно на это меро.
        'apply_next': reverse('application_create') + f'?event={event.id}',
    })


def public_experience(request, token):
    """Публичная страница волонтёрского опыта по ссылке «Скопировать опыт» — без
    входа, показывает только блок опыта (без ПДн/комментариев)."""
    from blog.services.experience import build_experience

    target = get_object_or_404(User, experience_token=token)
    return render(request, 'blog/public_experience.html', {
        'target': target,
        'experience': build_experience(target),
        'is_public': True,
    })


# ---------------------------------------------------------------------------
# Внешний опыт волонтёра (раздел «Мой опыт») — CRUD только для владельца профиля
# ---------------------------------------------------------------------------

@login_required
def external_experience_add(request):
    form = ExternalExperienceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        exp = form.save(commit=False)
        exp.user = request.user
        exp.save()
        messages.success(request, 'Внешнее мероприятие добавлено в ваш опыт.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('profile_detail', args=[request.user.id]) + '#experience',
        )
    return modal_form_response(
        request, 'blog/external_experience_form.html',
        {'form': form, 'title': 'Добавить внешнее мероприятие', 'submit_label': 'Добавить'},
    )


@login_required
def external_experience_edit(request, exp_id):
    from blog.models import ExternalExperience
    exp = get_object_or_404(ExternalExperience, pk=exp_id, user=request.user)
    form = ExternalExperienceForm(request.POST or None, instance=exp)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Запись обновлена.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('profile_detail', args=[request.user.id]) + '#experience',
        )
    return modal_form_response(
        request, 'blog/external_experience_form.html',
        {'form': form, 'title': 'Редактировать внешнее мероприятие', 'submit_label': 'Сохранить'},
    )


@login_required
def external_experience_delete(request, exp_id):
    from blog.models import ExternalExperience
    exp = get_object_or_404(ExternalExperience, pk=exp_id, user=request.user)
    if request.method == 'POST':
        exp.delete()
        messages.success(request, 'Запись удалена.')
    return redirect(reverse('profile_detail', args=[request.user.id]) + '#experience')


# ---------------------------------------------------------------------------
# TG Mini App — вход через Telegram initData вместо логина/пароля
# (architecture.md §2.1, db.md правило 8): один и тот же Django-веб, но пользователя
# логинит не форма, а подпись Telegram, проверенная на бэкенде. Дальше используется
# обычная Django-сессия — весь остальной код (шаблоны, @login_required, ACL) не меняется.
# ---------------------------------------------------------------------------

def webapp_entry(request):
    """Страница-лоадер, открываемая кнопкой Mini App в боте: достаёт `initData` из
    Telegram WebApp JS SDK на клиенте и отправляет на `webapp_auth`.

    Единственная страница, которой разрешено встраиваться в `<iframe>` (десктопный
    Telegram-клиент открывает Mini App именно так) — остальной сайт по-прежнему
    защищён от clickjacking через глобальный `XFrameOptionsMiddleware` (DENY).
    """
    response = render(request, 'blog/webapp_entry.html')
    response['X-Frame-Options'] = 'ALLOWALL'
    return response


@csrf_exempt
def webapp_auth(request):
    """Проверяет `initData`, логинит (или создаёт как гостя) пользователя по
    `telegram_id` через обычную Django-сессию — без пароля.

    `csrf_exempt` обоснован: подлинность запроса здесь подтверждается HMAC-подписью
    Telegram (`validate_init_data`), а не CSRF-токеном — на этот момент у клиента ещё
    нет сессии/csrf-cookie (это первый запрос Mini App), так что обычная CSRF-защита
    в принципе неприменима, как и для вебхуков внешних сервисов.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)

    from blog.services.telegram_auth import validate_init_data
    from data_base import data_controller as dc

    init_data = request.POST.get('init_data', '')
    payload = validate_init_data(init_data)
    if not payload or not payload.get('user') or not payload['user'].get('id'):
        logger.warning('Mini App auth: невалидный или устаревший initData.')
        return JsonResponse({'error': 'Не удалось подтвердить данные Telegram.'}, status=400)

    tg_user = payload['user']
    user, created = dc.get_or_create_user_by_telegram_id(
        tg_user['id'], tg_user.get('username'),
        first_name=tg_user.get('first_name'), last_name=tg_user.get('last_name'),
    )
    if user.status == 'blacklisted':
        logger.warning('Mini App auth: вход заблокированного пользователя отклонён user=%s', user.id)
        return JsonResponse({'error': 'Доступ ограничен — обратитесь к менеджеру центра.'}, status=403)

    auth_login(request, user, backend='blog.auth_backends.TelegramWebAppBackend')
    logger.info('Вход через Mini App: user=%s created=%s', user.id, created)
    # Флаг в сессии: запросы из Mini App разрешено встраивать в <iframe> (десктопный
    # Telegram-клиент), обычный веб-вход по логину/паролю — по-прежнему DENY против
    # clickjacking. Читается в TelegramWebAppFrameMiddleware.
    request.session['is_webapp_session'] = True
    return JsonResponse({'redirect': _post_tg_login_redirect(request, user)})


# ---------------------------------------------------------------------------
# Дашборд
# ---------------------------------------------------------------------------

def dashboard(request):
    # Гость (без входа) НЕ редиректится на логин — видит публичный список открытых
    # мероприятий с плашкой «авторизуйтесь» и статусом «Гость» (см. base.html).
    if not request.user.is_authenticated:
        return render(request, 'blog/public_event_list.html', {
            'events': _published_active_events(),
            'is_public': True,
            'show_guest_banner': True,
        })

    user = request.user
    context = {
        'role_label': role_label(user),
        'is_manager': is_manager(user),
        'is_team_leader': is_team_leader(user),
    }
    if is_manager(user):
        # Доступ к данным — через контроллер, а не прямым ORM (coding-principles §1,
        # hot_fix_1 §E — постепенный перевод веба на data_controller).
        from data_base import data_controller as dc
        context['new_applications_count'] = dc.count_applications(status_filter='new')
        context['open_events_count'] = dc.count_events_with_open_recruitment()

        from blog.services.incidents import get_open_incidents
        context['incidents'] = get_open_incidents()
    return render(request, 'blog/dashboard.html', context)


@manager_required
def incident_resolve(request, incident_id):
    """Отметить пункт «Главного» решённым — галочка сбоку у инцидента (чек-лист)."""
    from blog.services.incidents import resolve_incident
    if request.method == 'POST':
        resolve_incident(incident_id, request.user)
        messages.success(request, 'Отмечено как решённое.')
    return redirect('dashboard')


# ---------------------------------------------------------------------------
# Мероприятия (Этап 3)
# ---------------------------------------------------------------------------

@login_required
def event_list(request):
    manager_view = is_manager(request.user)
    # Волонтёр по умолчанию видит только непрошедшие меро: галка «Скрыть прошедшие»
    # предустановлена. Менеджеру — как раньше (показываем всё, галка снята). Явный
    # GET-параметр (переход по ссылке с фильтром) перекрывает дефолт в обе стороны.
    if 'hide_passed' in request.GET:
        hide_passed = request.GET.get('hide_passed') == '1'
    else:
        hide_passed = not manager_view
    events = list(
        Event.objects.select_related('location', 'organization', 'dobro_ru_shared_link')
        .prefetch_related('shifts')
    )

    # Для вида менеджера — общая картина по каждому меро одним проходом (без N+1):
    # тим-лидеры, ответственный менеджер, набор и заявки — per shift (см. event_detail —
    # та же группировка ApplicationShiftDecision по shift, здесь только для списка).
    tl_by_event = {}
    manager_by_event = {}
    decisions_by_shift = {}
    dobro_shared_usage = {}
    if manager_view:
        from collections import defaultdict
        tl_map = defaultdict(list)
        for staff in EventStaff.objects.filter(staff_role='team_lead').select_related('user'):
            tl_map[staff.event_id].append(staff.user.full_name)
        tl_by_event = tl_map

        for staff in EventStaff.objects.filter(staff_role='manager').select_related('user'):
            manager_by_event.setdefault(staff.event_id, staff.user.full_name)

        decisions = (
            ApplicationShiftDecision.objects
            .exclude(application__status='cancelled')
            .values('shift_id', 'status')
            .annotate(n=Count('id'))
        )
        for row in decisions:
            bucket = decisions_by_shift.setdefault(row['shift_id'], {'approved': 0, 'total': 0, 'processed': 0})
            bucket['total'] += row['n']
            if row['status'] == 'approved':
                bucket['approved'] += row['n']
            if row['status'] != 'new':
                bucket['processed'] += row['n']

        # Сколько разных мероприятий использует каждую общую ссылку Добро.ру —
        # чтобы отличить «эта общая ссылка используется только тут» от «шарится».
        shared_usage = (
            Event.objects.filter(dobro_ru_link_kind='shared', dobro_ru_shared_link__isnull=False)
            .values('dobro_ru_shared_link_id').annotate(n=Count('id'))
        )
        dobro_shared_usage = {r['dobro_ru_shared_link_id']: r['n'] for r in shared_usage}

    today = timezone.now().date()
    rows = []
    for event in events:
        shifts = sorted(event.shifts.all(), key=lambda s: s.day)
        first_day = shifts[0].day if shifts else None
        last_day = shifts[-1].day if shifts else None
        event.first_day = first_day
        event.last_day = last_day
        if manager_view:
            shift_rows = []
            for shift in shifts:
                bucket = decisions_by_shift.get(shift.id, {'approved': 0, 'total': 0, 'processed': 0})
                needed = shift.volunteer_needed
                if needed == 0:
                    # 0 нужно волонтёров: набор укомплектован (100%), если никого не
                    # одобрено — иначе любой approved уже перенабор (условный %, т.к.
                    # знаменатель 0; approved=1 → 200%, чтобы сразу считалось overflow).
                    recruit_percent = 100 if bucket['approved'] == 0 else 100 + bucket['approved'] * 100
                else:
                    recruit_percent = round(bucket['approved'] * 100 / needed)
                shift_rows.append({
                    'shift': shift,
                    'status': shift.compute_status(),
                    'recruit_status': shift.recruit_status,
                    'needed': needed,
                    'approved': bucket['approved'],
                    'recruit_percent': recruit_percent,
                    'recruit_overflow': recruit_percent > 100,
                    'applications_total': bucket['total'],
                    'applications_processed': bucket['processed'],
                    'applications_percent': 100 if bucket['total'] == 0 else round(bucket['processed'] * 100 / bucket['total']),
                })
            event.shift_rows = shift_rows
            # Список (не строка) — в шаблоне каждый тим-лидер выводится с новой строки
            # внутри своей ячейки, а не растягивает колонку в ширину при нескольких ТЛ.
            event.team_leads_list = tl_by_event.get(event.id, [])
            event.team_leads_str = ', '.join(event.team_leads_list) or '—'
            event.responsible_manager = manager_by_event.get(event.id, '—')

            # Добро.ру: символ статуса + подпись (см. event_list.html §дизайн). dobro_index —
            # id общей ссылки для нижнего индекса (О₁, О₂…), None — если рисовать не нужно
            # (уникальная/нет ссылки/единственное меро на эту общую ссылку).
            event.dobro_index = None
            if event.dobro_ru_link_kind == 'unique':
                event.dobro_symbol, event.dobro_caption, event.dobro_class = 'У', 'уникальная', 'unique'
            elif event.dobro_ru_link_kind == 'shared' and event.dobro_ru_shared_link_id:
                usage = dobro_shared_usage.get(event.dobro_ru_shared_link_id, 1)
                event.dobro_symbol = 'О'
                if usage > 1:
                    event.dobro_index = event.dobro_ru_shared_link_id
                event.dobro_caption = 'общая' if usage > 1 else 'общая (единств.)'
                event.dobro_class = 'shared'
            else:
                event.dobro_symbol, event.dobro_caption, event.dobro_class = '-', 'нет ссылки', 'missing'
        rows.append(event)

    # Ранжирование по дате: сначала ближайшие предстоящие/идущие (по возрастанию даты),
    # затем прошедшие меро в конце (тоже по возрастанию — недавно прошедшие выше старых).
    # Меро без смен вообще — в самом конце.
    rows.sort(key=lambda e: (
        e.first_day is None,
        e.compute_status() in ('passed', 'finished'),
        e.first_day or datetime.date.max,
    ))

    return render(request, 'blog/event_list.html', {
        'events': rows,
        'manager_view': manager_view,
        'hide_passed': hide_passed,
    })


@login_required
def event_detail(request, event_id):
    event = get_object_or_404(Event.objects.select_related('location', 'organization', 'organizer'), pk=event_id)
    event.close_recruit_if_passed()
    shifts = list(event.shifts.select_related('location').order_by('day'))
    # Пока мероприятие не началось — смены идут по возрастанию даты (ближайшая сверху).
    # Прошедшие смены уходят в конец списка, а не сортируются по дате среди актуальных —
    # так самая близкая предстоящая/идущая смена всегда наверху.
    today = timezone.now().date()
    shifts.sort(key=lambda s: (s.day < today, s.day))
    team_leads = event.staff.filter(staff_role='team_lead').select_related('user')
    # Ответственный менеджер меро — назначение EventStaff со staff_role='manager'
    # (мини-дашборд наверху страницы; меняется только через редактирование меро,
    # EventForm.manager — единая точка назначения, как и у тим-лидеров).
    event_manager_staff = event.staff.filter(staff_role='manager').select_related('user').first()
    categories = EventCategory.objects.filter(event_map__event=event).order_by('name')
    requirements = EventRequirement.objects.filter(event_map__event=event).order_by('title')
    can_manage_applications = can_process_applications(request.user, event.id)
    # Мероприятие завершено — заявки/явку менять больше нельзя нигде (ни в вебе, ни
    # через клики по таблице); данные показываются только для просмотра.
    is_finished = event.event_status == 'finished'

    # Кнопка «Подать заявку» доступна на ОПУБЛИКОВАННОЕ меро, у которого есть хотя бы
    # одна смена, что ещё не началась — даже если набор на все смены уже закрыт: такая
    # заявка примется и сразу уйдёт в резерв (см. application_create). На уже
    # закончившееся меро (все смены начались/прошли) заявку подать нельзя.
    has_open_recruitment = bool(event.published_at) and any(
        s.start_time > timezone.now() for s in shifts
    )
    my_active_application = Application.objects.filter(
        user=request.user, event=event, status__in=['new', 'approved'],
    ).first()

    context = {
        'event': event,
        'shifts': shifts,
        'team_leads': team_leads,
        'categories': categories,
        'requirements': requirements,
        'share_url': request.build_absolute_uri(
            reverse('public_event_detail', args=[event.public_token])
        ),
        'can_manage_applications': can_manage_applications,
        'can_edit_applications': can_manage_applications and not is_finished,
        'is_finished': is_finished,
        'is_manager': is_manager(request.user),
        'comments': event.comments.all(),
        'comment_form': EventCommentForm() if can_manage_applications else None,
        'has_open_recruitment': has_open_recruitment,
        'my_active_application': my_active_application,
        'event_manager': event_manager_staff.user if event_manager_staff else None,
    }

    # Лента изменений по заявкам (повторный Excel-импорт: кто изменил/отказался/появился) —
    # видна только пока меро не завершено; после завершения скрывается независимо от
    # того, есть ли непрочитанные записи (см. ApplicationChangeLog).
    if can_manage_applications and not is_finished:
        context['application_change_logs'] = event.application_change_logs.all()

    if context['is_manager'] and event.event_status != 'finished':
        context['closing_checklist'] = event_closing_checklist(event)

    if can_manage_applications:
        from blog.services.applications import ensure_shift_decisions

        needed = sum(s.volunteer_needed for s in shifts)
        pending_count = event.applications.filter(status='new').count()

        # Набор разбит по сменам (не общий плоский список — иначе заявка на несколько
        # смен визуально "дублируется" при простом листинге всех applications разом).
        # Статус решения (одобрена/резерв/новая) теперь per-shift через
        # ApplicationShiftDecision — принять/отклонить заявку на одну смену не трогает
        # её статус на другие смены той же заявки.
        for app in event.applications.exclude(status='cancelled').prefetch_related('selected_shifts', 'event__shifts'):
            ensure_shift_decisions(app)

        # Единая таблица набора + явки по сменам. Раньше это были две отдельные таблицы
        # («Набор» и «Явка»); теперь на каждую смену — одна таблица со строками-заявками,
        # где у ОДОБРЕННОЙ заявки прямо в строке отмечается явка (был/не был) и часы
        # (Participation). Порядок строк на смене:
        #   1) одобренные пришедшие, 2) одобренные не пришедшие (уходят вниз),
        #   3) новые (необработанные), 4) резерв/отклонённые (скрыты по умолчанию, показ
        #      по кнопке «показать резерв» на клиенте).
        # Порядок сортировки задаём на сервере, а строки резерва помечаем data-reserve
        # в шаблоне — скрытие/показ полностью клиентское.
        parts_by_shift_user = {}
        for p in Participation.objects.filter(event_day__in=shifts).select_related('user'):
            parts_by_shift_user[(p.event_day_id, p.user_id)] = p

        def _row_sort_key(row):
            # Меньше — выше. Одобренные-пришедшие (0) → одобренные-не пришедшие (1) →
            # новые (2) → резерв (3). Внутри группы — по фамилии/имени.
            d = row['decision']
            part = row['participation']
            if d.status == 'approved':
                group = 0 if (part and part.status == 'attended') else 1
            elif d.status == 'new':
                group = 2
            else:
                group = 3
            app = d.application
            return (group, (app.last_name or '').lower(), (app.first_name or '').lower())

        shifts_with_recruitment = []
        approved_total = 0
        for shift in shifts:
            decisions = (
                ApplicationShiftDecision.objects.filter(shift=shift)
                .exclude(application__status='cancelled')
                .select_related('application', 'application__user')
            )
            rows = []
            shift_approved = shift_pending = 0
            for decision in decisions:
                app = decision.application
                participation = parts_by_shift_user.get((shift.id, app.user_id)) if app.user_id else None
                rows.append({'decision': decision, 'participation': participation})
                if decision.status == 'approved':
                    shift_approved += 1
                elif decision.status == 'new':
                    shift_pending += 1
            rows.sort(key=_row_sort_key)
            approved_total += shift_approved
            # Процент набора смены (для мини-дашборда): если нужно 0 волонтёров —
            # считаем смену укомплектованной (100%), иначе approved/needed — БЕЗ потолка
            # в 100%, перенабор должен быть виден как есть (напр. 17/5 -> 340%).
            pct = 100 if shift.volunteer_needed == 0 else round(shift_approved * 100 / shift.volunteer_needed)
            shifts_with_recruitment.append({
                'shift': shift,
                'rows': rows,
                'approved_count': shift_approved,
                'pending_count': shift_pending,
                'needed': shift.volunteer_needed,
                'remaining': max(shift.volunteer_needed - shift_approved, 0),
                'percent': pct,
                'recruit_overflow': pct > 100,
                # Кол-во строк в резерве — чтобы показать это на кнопке «показать резерв».
                'reserve_count': sum(1 for r in rows if r['decision'].status == 'rejected'),
            })

        # Общий процент набора по меро (для мини-дашборда наверху) — тоже без потолка.
        recruit_percent = 100 if needed == 0 else round(approved_total * 100 / needed)
        context.update({
            'shifts_with_recruitment': shifts_with_recruitment,
            'needed': needed,
            'approved_count': approved_total,
            'remaining': max(needed - approved_total, 0),
            'pending_count': pending_count,
            'recruit_percent': recruit_percent,
            'recruit_overflow': recruit_percent > 100,
        })

    # 👥 Расширенная карточка — только для участников мероприятия
    # (reports.md раздел 4: подавших заявку или получивших участие).
    is_participant = (
        Application.objects.filter(user=request.user, event=event).exists()
        or Participation.objects.filter(user=request.user, event_day__event=event).exists()
    )
    if is_participant:
        volunteers_count = Participation.objects.filter(event_day__event=event).values('user').distinct().count()
        avg_rating = event.feedbacks.aggregate(avg=Avg('rating'))['avg']
        my_feedback = event.feedbacks.filter(author=request.user).first()
        context.update({
            'is_participant': True,
            'volunteers_count': volunteers_count,
            'avg_rating': avg_rating,
            'feedback_count': event.feedbacks.count(),
            'my_feedback': my_feedback,
            'feedback_form': EventFeedbackForm() if not my_feedback else None,
            # Отзывы волонтёров — видно, кто оставил (в отличие от внутренних
            # комментариев менеджеров/ТЛ, которые показываются без подписи автора).
            'feedbacks': event.feedbacks.select_related('author').order_by('-created_at'),
        })

    return render(request, 'blog/event_detail.html', context)


@login_required
def event_comment_add(request, event_id):
    """Внутренний комментарий к мероприятию (менеджеры/тим-лидеры своего меро) —
    показывается на странице меро без подписи автора, только текст и дата."""
    event = get_object_or_404(Event, pk=event_id)
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет прав оставлять комментарии к этому мероприятию.')

    if request.method == 'POST':
        form = EventCommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.event = event
            comment.author = request.user
            comment.save()
            messages.success(request, 'Комментарий добавлен.')
    return redirect('event_detail', event_id=event.id)


@login_required
def event_change_log_mark_read(request, event_id):
    """«Прочитано» по ленте изменений заявок мероприятия — полностью очищает её
    (пользователь явно подтвердил, что ознакомился)."""
    event = get_object_or_404(Event, pk=event_id)
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет прав на это действие.')
    if request.method == 'POST':
        event.application_change_logs.all().delete()
        messages.success(request, 'Изменения по заявкам отмечены как прочитанные.')
    return redirect('event_detail', event_id=event.id)


@login_required
def event_feedback_add(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    is_participant = (
        Application.objects.filter(user=request.user, event=event).exists()
        or Participation.objects.filter(user=request.user, event_day__event=event).exists()
    )
    if not is_participant:
        raise PermissionDenied('Оставить оценку могут только участники мероприятия.')

    if EventFeedback.objects.filter(event=event, author=request.user).exists():
        messages.error(request, 'Вы уже оставили оценку этому мероприятию.')
        return redirect('event_detail', event_id=event.id)

    if request.method == 'POST':
        form = EventFeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.event = event
            feedback.author = request.user
            feedback.save()
            messages.success(request, 'Спасибо за оценку!')
    return redirect('event_detail', event_id=event.id)


@manager_required
def event_create(request):
    # Создание меро из превью Excel-импорта (bot-update.md-подобный флоу для веба):
    # кнопка «Создать мероприятие «X»» на import_preview передаёт название и метку,
    # что нужно вернуться назад на превью импорта, а не на страницу меро.
    initial = {'title': request.GET.get('title')} if request.GET.get('title') else None
    from_import = request.GET.get('from_import') == '1'

    form = EventForm(request.POST or None, initial=initial, assigned_by=request.user)
    if request.method == 'POST' and form.is_valid():
        event = form.save()
        messages.success(request, 'Мероприятие создано.')
        redirect_url = reverse('import_preview') if from_import else reverse('event_detail', args=[event.id])
        return modal_form_response(request, None, None, success_redirect=redirect_url)
    return modal_form_response(
        request, 'blog/event_form.html',
        {'form': form, 'title': 'Новое мероприятие', 'submit_label': 'Создать',
         'volunteer_needed_options': VOLUNTEER_NEEDED_OPTIONS},
        partial_template='blog/partials/_event_form_body.html',
    )


@manager_required
def event_edit(request, event_id):
    """Редактирование мероприятия. Завершённое (finished) меро НЕ редактируется
    напрямую — нужно сначала открыть его обратно (event_reopen, капча x+y), после
    чего event_status временно не 'finished' и вся страница (включая эту форму,
    набор, явку) снова доступна для правок, как у обычного прошедшего меро."""
    event = get_object_or_404(Event, pk=event_id)
    if event.event_status == 'finished':
        raise PermissionDenied('Мероприятие завершено — сначала откройте его обратно кнопкой на странице меро.')

    form = EventForm(request.POST or None, instance=event, show_closing_fields=True, assigned_by=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Мероприятие обновлено.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('event_detail', args=[event.id]),
        )
    return modal_form_response(
        request, 'blog/event_form.html',
        {'form': form, 'title': f'Редактировать: {event.title}', 'submit_label': 'Сохранить'},
        partial_template='blog/partials/_event_form_body.html',
    )


@manager_required
def event_delete(request, event_id):
    """Полное удаление мероприятия менеджером — с двухфакторным подтверждением (капча
    x+y, общий компонент render_captcha_modal). Каскадом удаляются смены, заявки,
    решения по сменам, участия, комментарии и т.п. (FK on_delete=CASCADE).

    GET (AJAX) → окно капчи в модалке. POST с верной капчей → удаление. Агрегаты
    затронутых волонтёров пересчитываются после удаления (сначала собираем их id)."""
    event = get_object_or_404(Event, pk=event_id)
    session_key = f'captcha_event_delete_{event.id}'

    if request.method == 'POST':
        if not _check_captcha(request, session_key, request.POST.get('captcha_answer')):
            messages.error(request, 'Неверный ответ на пример — удаление отменено. Попробуйте ещё раз.')
            return modal_form_response(request, None, None, success_redirect=reverse('event_detail', args=[event.id]))
        affected_user_ids = list(
            Participation.objects.filter(event_day__event=event)
            .values_list('user_id', flat=True).distinct()
        )
        title = event.title
        event.delete()
        if affected_user_ids:
            from blog.services.stats import recalc_user_aggregates
            for user in User.objects.filter(id__in=affected_user_ids):
                recalc_user_aggregates(user)
        logger.info('Мероприятие удалено: event=%s title=%r by=%s', event_id, title, actor(request.user))
        messages.success(request, f'Мероприятие «{title}» удалено.')
        return modal_form_response(request, None, None, success_redirect=reverse('event_list'))

    return render_captcha_modal(
        request,
        session_key=session_key,
        action_url=reverse('event_delete', args=[event.id]),
        confirm_text=f'Удалить мероприятие «{event.title}» безвозвратно? Вместе с ним удалятся все смены, заявки и явка по нему.',
        submit_label='Удалить мероприятие',
        title=f'Удаление: {event.title}',
    )


@manager_required
def event_publish(request, event_id):
    """Публикация мероприятия: проставляет published_at — после этого открывается
    подача заявок и меро попадает в список активных. Рассылку уведомлений НЕ делает —
    это отдельная кнопка «Сделать рассылку» (см. event_broadcast)."""
    event = get_object_or_404(Event, pk=event_id)
    if request.method == 'POST':
        if event.published_at:
            messages.error(request, 'Мероприятие уже опубликовано.')
        elif event.event_status == 'finished':
            messages.error(request, 'Мероприятие уже завершено — публиковать его больше нельзя.')
        else:
            event.published_at = timezone.now()
            event.save(update_fields=['published_at'])
            logger.info('Мероприятие опубликовано: event=%s by=%s', event.id, actor(request.user))
            messages.success(request, 'Мероприятие опубликовано — подача заявок открыта.')
    return redirect('event_detail', event_id=event.id)


@manager_required
def event_broadcast(request, event_id):
    """Рассылка-оповещение о мероприятии подписанным волонтёрам (отдельно от публикации).
    Доступна только после публикации; ставит уведомления в очередь бота.

    Рассылку можно делать несколько раз (напр. для добора): уведомления уходят только
    тем, кто ещё НЕ подал заявку на это меро. Если рассылка уже была сделана ранее,
    сообщаем об этом (broadcast_sent_at показывает момент ПЕРВОЙ рассылки)."""
    event = get_object_or_404(Event, pk=event_id)
    if request.method == 'POST':
        if not event.published_at:
            messages.error(request, 'Сначала опубликуйте мероприятие — потом можно делать рассылку.')
        elif event.event_status == 'finished':
            messages.error(request, 'Мероприятие завершено — рассылка больше не нужна.')
        else:
            was_sent_before = event.broadcast_sent_at is not None
            sent = notifications_service.broadcast_new_event(event)
            logger.info(
                'Рассылка о мероприятии event=%s поставлена в очередь: адресатов=%s повторная=%s by=%s',
                event.id, sent, was_sent_before, actor(request.user),
            )
            if not was_sent_before:
                event.broadcast_sent_at = timezone.now()
                event.save(update_fields=['broadcast_sent_at'])
            if sent:
                prefix = 'Повторная рассылка' if was_sent_before else 'Рассылка'
                messages.success(
                    request,
                    f'{prefix} поставлена в очередь — уведомления уйдут {sent} '
                    'подписанным волонтёрам (кроме уже подавших заявку).'
                )
            else:
                messages.info(
                    request,
                    'Все подписанные волонтёры уже подали заявку на это мероприятие — '
                    'рассылать некому.'
                )
    return redirect('event_detail', event_id=event.id)


@login_required
def shift_toggle_recruit(request, event_id, shift_id):
    """Ручное переключение набора открыт/закрыт на конкретной смене — доступно
    менеджеру и тим-лидеру мероприятия. Не проверяет необработанные заявки — они
    просто остаются необработанными и видны в общем списке заявок."""
    event = get_object_or_404(Event, pk=event_id)
    shift = get_object_or_404(EventShift, pk=shift_id, event=event)
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет прав управлять набором этого мероприятия.')
    if event.event_status == 'finished':
        raise PermissionDenied('Мероприятие завершено — набор менять больше нельзя.')

    if request.method == 'POST':
        shift.recruit_status = 'closed' if shift.recruit_status == 'open' else 'open'
        shift.save(update_fields=['recruit_status'])
        label = 'закрыт' if shift.recruit_status == 'closed' else 'открыт'
        messages.success(request, f'Набор на смену {shift.day} {label}.')
    return redirect('event_detail', event_id=event.id)


@login_required
def shift_toggle_attendance_confirmed(request, event_id, shift_id):
    """«Можно забирать» — тим-лидер/менеджер этого меро подтверждает, что явка и часы
    по смене актуализированы. Чисто визуальный индикатор (ни на что не влияет), доступен
    только для смен, которые уже прошли — до этого момента актуализировать ещё нечего."""
    event = get_object_or_404(Event, pk=event_id)
    shift = get_object_or_404(EventShift, pk=shift_id, event=event)
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет прав управлять явкой этого мероприятия.')
    if shift.compute_status() != 'passed':
        raise PermissionDenied('Отметить «можно забирать» можно только после того, как смена прошла.')

    if request.method == 'POST':
        shift.attendance_confirmed = not shift.attendance_confirmed
        if shift.attendance_confirmed:
            shift.attendance_confirmed_at = timezone.now()
            shift.attendance_confirmed_by = request.user
        else:
            shift.attendance_confirmed_at = None
            shift.attendance_confirmed_by = None
        shift.save(update_fields=['attendance_confirmed', 'attendance_confirmed_at', 'attendance_confirmed_by'])
        label = 'можно забирать' if shift.attendance_confirmed else 'снята отметка «можно забирать»'
        messages.success(request, f'Смена {shift.day.strftime("%d.%m.%Y")}: {label}.')
    return redirect('event_detail', event_id=event.id)


@manager_required
def event_reopen(request, event_id):
    """Открыть завершённое мероприятие обратно для редактирования явки/часов/заявок
    (после ToDo: «мы не редактируем завершённое мероприятие, а открываем его обратно»).
    Требует капчу x+y — тот же двухфакторный паттерн, что раньше защищал
    редактирование общей информации завершённого меро (event_edit); теперь и общая
    форма, и явка/набор одинаково доступны, пока меро не в статусе finished, так что
    отдельная капча для явки отдельно не нужна — открытие меро её и есть.

    event_status переключается на 'passed' (а не 'upcoming'/'ongoing') — сами смены
    остались в прошлом, compute_status() и так вернёт 'passed' по датам; это лишь
    снимает единственный флаг, который блокирует редактирование (event_status ==
    'finished'). Обратно — кнопкой «Завершить обратно» (event_close), без
    повторного прохождения чеклиста «готовности» (он уже пройден при первом
    закрытии; чеклист всё равно перепроверяет актуальное состояние на всякий случай)."""
    event = get_object_or_404(Event, pk=event_id)
    if event.event_status != 'finished':
        messages.error(request, 'Мероприятие не завершено — открывать нечего.')
        return redirect('event_detail', event_id=event.id)

    captcha_key = f'captcha_event_reopen_{event.id}'
    if request.method == 'POST' and 'captcha_answer' in request.POST:
        if _check_captcha(request, captcha_key, request.POST.get('captcha_answer')):
            event.event_status = 'passed'
            event.save(update_fields=['event_status'])
            logger.info('Мероприятие открыто обратно для редактирования: event=%s by=%s', event.id, actor(request.user))
            messages.success(request, f'Мероприятие «{event.title}» снова открыто для редактирования.')
            return redirect('event_detail', event_id=event.id)
        messages.error(request, 'Неверный ответ на пример.')

    return render_captcha_modal(
        request,
        session_key=captcha_key,
        action_url=reverse('event_reopen', args=[event.id]),
        confirm_text='Мероприятие будет снова доступно для редактирования (заявки, набор, явка, часы) — не забудьте завершить его обратно, когда закончите.',
        submit_label='Открыть для редактирования',
        title=f'Открыть завершённое: {event.title}',
    )


@manager_required
def event_close(request, event_id):
    """Экран проверки перед завершением мероприятия (cjm-event-lifecycle.md, этап 8):
    показывает чеклист условий, даёт заполнить people_helped, если он ещё пуст,
    и требует явное подтверждение на самой кнопке завершения."""
    event = get_object_or_404(Event, pk=event_id)
    checklist = event_closing_checklist(event)

    if request.method == 'POST':
        if not checklist['ready']:
            messages.error(request, 'Мероприятие ещё не готово к завершению — проверьте условия ниже.')
            return redirect('event_close', event_id=event.id)

        people_helped = request.POST.get('people_helped', '').strip()
        if not people_helped.isdigit():
            messages.error(request, 'Укажите количество людей, которым помогли (обязательное поле).')
            return redirect('event_close', event_id=event.id)

        event.people_helped = int(people_helped)
        event.event_status = 'finished'
        event.save(update_fields=['people_helped', 'event_status'])
        logger.info(
            'Мероприятие завершено: event=%s people_helped=%s by=%s',
            event.id, event.people_helped, actor(request.user),
        )
        messages.success(request, f'Мероприятие «{event.title}» завершено.')
        return redirect('event_detail', event_id=event.id)

    return render(request, 'blog/event_close.html', {'event': event, 'checklist': checklist})


@manager_required
def event_dobro_toggle(request, event_id):
    """Переключение статуса «Часы на Добро.ру выставлены / не выставлены» для
    мероприятия (только менеджер). Доступно лишь после закрытия мероприятия
    (event_status='finished') — до этого простановка часов не имеет смысла.
    Мероприятия с типом учёта 'none' часы на Добро.ру не ведут — для них статус
    не выставляется."""
    event = get_object_or_404(Event, pk=event_id)
    if request.method == 'POST':
        if event.event_status != 'finished':
            messages.error(request, 'Статус часов на Добро.ру доступен только после завершения мероприятия.')
        elif event.dobro_ru_link_kind == 'none':
            messages.error(request, 'У этого мероприятия учёт часов на Добро.ру не ведётся.')
        else:
            event.dobro_ru_hours_logged = not event.dobro_ru_hours_logged
            if event.dobro_ru_hours_logged:
                event.dobro_ru_logged_by = request.user
            event.save(update_fields=['dobro_ru_hours_logged', 'dobro_ru_logged_by'])
            label = 'выставлены' if event.dobro_ru_hours_logged else 'не выставлены'
            messages.success(request, f'Часы на Добро.ру отмечены как {label}.')
    return redirect('event_detail', event_id=event.id)


@manager_required
def event_shift_add(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if event.event_status == 'finished':
        raise PermissionDenied('Завершённое мероприятие нельзя редактировать.')
    form = EventShiftForm(request.POST or None, event=event)
    if request.method == 'POST' and form.is_valid():
        shift = form.save(commit=False)
        shift.event = event
        shift.save()
        messages.success(request, 'Смена мероприятия добавлена.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('event_detail', args=[event.id]),
        )
    return modal_form_response(
        request, 'blog/event_shift_form.html',
        {'form': form, 'event': event, 'title': f'Новая смена: {event.title}', 'submit_label': 'Добавить',
         'volunteer_needed_options': VOLUNTEER_NEEDED_OPTIONS},
        partial_template='blog/partials/_event_shift_form_body.html',
    )


@manager_required
def event_shift_edit(request, event_id, shift_id):
    event = get_object_or_404(Event, pk=event_id)
    if event.event_status == 'finished':
        raise PermissionDenied('Завершённое мероприятие нельзя редактировать.')
    shift = get_object_or_404(EventShift, pk=shift_id, event=event)
    form = EventShiftForm(request.POST or None, instance=shift, event=event)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Смена мероприятия обновлена.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('event_detail', args=[event.id]),
        )
    return modal_form_response(
        request, 'blog/event_shift_form.html',
        {'form': form, 'event': event, 'title': f'Редактировать смену: {event.title}', 'submit_label': 'Сохранить',
         'volunteer_needed_options': VOLUNTEER_NEEDED_OPTIONS},
        partial_template='blog/partials/_event_shift_form_body.html',
    )


@manager_required
def event_shift_delete(request, event_id, shift_id):
    event = get_object_or_404(Event, pk=event_id)
    if event.event_status == 'finished':
        raise PermissionDenied('Завершённое мероприятие нельзя редактировать.')
    shift = get_object_or_404(EventShift, pk=shift_id, event=event)
    if request.method == 'POST':
        # Нельзя удалить последнюю смену: мероприятие без смен теряет смысл (нет набора,
        # нет явки, нельзя вычислить статус по датам). Чтобы «убрать» такое меро —
        # удаляют мероприятие целиком (event_delete).
        if event.shifts.count() <= 1:
            messages.error(
                request,
                'Нельзя удалить единственную смену мероприятия. Если мероприятие не нужно — '
                'удалите его целиком кнопкой «Удалить».'
            )
            return redirect('event_detail', event_id=event.id)
        shift.delete()
        messages.success(request, 'Смена мероприятия удалена.')
    return redirect('event_detail', event_id=event.id)



# ---------------------------------------------------------------------------
# Явка (Этап 5)
# ---------------------------------------------------------------------------

@login_required
def participation_set_status(request, participation_id):
    """Простановка явки прямо в таблице на странице мероприятия (AJAX), без отдельной
    формы/подтверждения: явка (был/не был) + при "не был" — причина (уважительно/без
    предупреждения). Часы и full_shift считаются автоматически, а не вводятся вручную:
    - «Был» → hours = длительность дня (end_time - start_time), full_shift=True.
    - «Отсутствовал» (обе причины) → hours=0, full_shift=False.
    Единственное явное последствие для волонтёра — churn при неявке без предупреждения."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)

    participation = get_object_or_404(
        Participation.objects.select_related('event_day__event', 'user'), pk=participation_id
    )
    event = participation.event_day.event
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет доступа к явке этого мероприятия.')
    if event.event_status == 'finished':
        return JsonResponse({'error': 'Мероприятие завершено — явку менять больше нельзя.'}, status=403)

    new_status = request.POST.get('status')
    if new_status not in dict(Participation.STATUS_CHOICES):
        return JsonResponse({'error': 'Некорректный статус.'}, status=400)

    old_status = participation.status
    participation.status = new_status
    # Смена статуса заново вычисляет часы из длительности смены и сбрасывает ручную
    # корректировку (hours_overridden): переключение «Был/Не был» — это явное действие,
    # после которого часы возвращаются к автоматическому значению, пока их снова не
    # поправят вручную.
    if new_status == 'attended':
        day = participation.event_day
        duration = day.end_time - day.start_time
        participation.hours = max(0, round(duration.total_seconds() / 3600))
        participation.full_shift = True
    else:
        participation.hours = 0
        participation.full_shift = False
    participation.hours_overridden = False
    participation.save(update_fields=['status', 'hours', 'full_shift', 'hours_overridden'])
    recalc_user_aggregates(participation.user)

    if new_status == 'absent_unexcused' and old_status != 'absent_unexcused':
        from blog.services.stats import apply_churn_no_show
        apply_churn_no_show(participation.user)
    elif new_status == 'attended' and old_status != 'attended':
        from blog.services.stats import apply_churn_activity_decay
        apply_churn_activity_decay(participation.user)

    logger.info(
        'Явка проставлена (веб): participation=%s event=%s %s→%s by=%s subject=%s',
        participation.id, event.id, old_status, new_status,
        actor(request.user), actor(participation.user),
    )
    return JsonResponse({
        'status': participation.status,
        'status_display': participation.get_status_display(),
        'hours': participation.hours,
    })


@login_required
def participation_set_hours(request, participation_id):
    """Ручная корректировка часов участия тим-лидером/менеджером прямо в таблице явки
    (AJAX). Помечает участие hours_overridden=True — после этого автоматический пересчёт
    часов при изменении времени смены эти часы не трогает."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)

    participation = get_object_or_404(
        Participation.objects.select_related('event_day__event', 'user'), pk=participation_id
    )
    event = participation.event_day.event
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет доступа к явке этого мероприятия.')
    if event.event_status == 'finished':
        return JsonResponse({'error': 'Мероприятие завершено — явку менять больше нельзя.'}, status=403)

    raw = (request.POST.get('hours') or '').strip()
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Часы должны быть целым числом.'}, status=400)
    if hours < 0:
        return JsonResponse({'error': 'Часы не могут быть отрицательными.'}, status=400)

    participation.hours = hours
    participation.hours_overridden = True
    participation.save(update_fields=['hours', 'hours_overridden'])
    recalc_user_aggregates(participation.user)

    logger.info(
        'Часы участия скорректированы вручную (веб): participation=%s hours=%s by=%s subject=%s',
        participation.id, hours, actor(request.user), actor(participation.user),
    )
    return JsonResponse({'hours': participation.hours})


@login_required
@login_required
def participation_edit(request, participation_id):
    participation = get_object_or_404(
        Participation.objects.select_related('event_day__event', 'user'), pk=participation_id
    )
    event = participation.event_day.event
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет доступа к явке этого мероприятия.')
    if event.event_status == 'finished':
        raise PermissionDenied('Мероприятие завершено — явку менять больше нельзя.')

    form = ParticipationForm(request.POST or None, instance=participation)
    if request.method == 'POST' and form.is_valid():
        old = Participation.objects.get(pk=participation.pk)
        old_status = old.status
        participation = form.save(commit=False)
        # Ручная правка часов через форму фиксирует hours_overridden, чтобы автопересчёт
        # при изменении времени смены не затирал введённое значение.
        if participation.status == 'attended' and participation.hours != old.hours:
            participation.hours_overridden = True
        participation.save()
        recalc_user_aggregates(participation.user)

        if participation.status == 'absent_unexcused' and old_status != 'absent_unexcused':
            from blog.services.stats import apply_churn_no_show
            apply_churn_no_show(participation.user)
        elif participation.status == 'attended':
            from blog.services.stats import apply_churn_activity_decay
            apply_churn_activity_decay(participation.user)

        messages.success(request, 'Явка обновлена, статистика пересчитана.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('event_detail', args=[event.id]),
        )

    return modal_form_response(
        request, 'blog/participation_form.html',
        {'form': form, 'participation': participation, 'title': f'Явка: {participation.user.full_name}'},
    )


# ---------------------------------------------------------------------------
# Заявки (Этап 4)
# ---------------------------------------------------------------------------

def _fill_application_shifts(application, selected_shifts):
    if selected_shifts:
        application.selected_shifts.set(selected_shifts)
        application.shifts = ', '.join(s.day.isoformat() for s in selected_shifts.order_by('day'))
    else:
        # Смены не выбраны — считаем заявку на все открытые смены меро (одна смена
        # или пользователь ничего не отмечал вручную). Если открытых смен нет вовсе
        # (набор закрыт целиком) — берём все смены меро, заявка всё равно уйдёт в
        # резерв целиком (см. application_create).
        all_shifts = application.event.shifts.filter(recruit_status='open').order_by('day')
        if not all_shifts.exists():
            all_shifts = application.event.shifts.all().order_by('day')
        application.selected_shifts.set(all_shifts)
        application.shifts = 'Все смены'
    application.save(update_fields=['shifts'])


@login_required
def application_create(request):
    """Заявка через веб: ФИО/Telegram/телефон берём из профиля авторизованного
    пользователя — система их уже знает, вводить заново не нужно.

    Дубли на веб-форме не допускаются (в отличие от Excel-импорта, db.md правило 3,
    которое остаётся как есть): если у пользователя уже есть активная заявка
    (new/approved) на выбранное меро, вместо создания второй — редирект на
    редактирование существующей."""
    # Отдельной СТРАНИЦЫ подачи заявки больше нет — форма живёт только в модалке (кнопка
    # «Подать заявку» на странице «Мероприятия»). Прямой не-AJAX GET на /applications/new/
    # уводим на список мероприятий, чтобы не рендерить осиротевшую полную страницу.
    if request.method == 'GET' and not is_ajax(request):
        return redirect('event_list')

    # Подать заявку может только пользователь с «заполненным аккаунтом» (ФИО + Telegram +
    # телефон). Если чего-то не хватает — НЕ грузим форму в модалку (иначе редирект внутри
    # fetch ломался и «ничего не происходило»): отвечаем JSON с плашкой и ссылкой на
    # редактирование профиля. Модальный JS показывает плашку, а по повторному клику ведёт
    # на страницу заполнения профиля. Для не-AJAX (прямой заход) — обычный редирект.
    if not account_is_complete(request.user):
        missing = ', '.join(account_missing_fields(request.user))
        profile_url = reverse('profile_edit') + f'?next={quote(request.get_full_path())}'
        if is_ajax(request):
            return JsonResponse({
                'profile_incomplete': True,
                'message': f'Заполните {missing} в личном кабинете, чтобы подать заявку.',
                'profile_url': profile_url,
            }, status=200)
        messages.warning(request, f'Заполните {missing} в личном кабинете, чтобы подать заявку.')
        return redirect(profile_url)

    event_id = request.POST.get('event') or request.GET.get('event')
    if event_id:
        # Подать заявку можно только на опубликованное мероприятие (кнопка «Опубликовать»
        # открывает набор). До публикации меро не видно волонтёрам и заявки не принимаются.
        target_event = Event.objects.filter(pk=event_id).first()
        if target_event and not target_event.published_at:
            messages.error(request, 'Мероприятие ещё не опубликовано — подать заявку нельзя.')
            return redirect('dashboard')
        existing = Application.objects.filter(
            user=request.user, event_id=event_id, status__in=['new', 'approved'],
        ).first()
        if existing:
            messages.info(request, 'Заявка на это мероприятие уже подана — вы можете отредактировать её.')
            return redirect('application_edit', application_id=existing.id)

    initial = {'event': event_id} if event_id and request.method != 'POST' else None
    form = ApplicationForm(request.POST or None, initial=initial, user=request.user)
    if request.method == 'POST' and form.is_valid():
        application = form.save(commit=False)
        application.submitted_at = timezone.now()
        application.user = request.user
        application.first_name = request.user.first_name or ''
        application.last_name = request.user.last_name
        application.middle_name = request.user.middle_name
        application.telegram_username = request.user.telegram_username
        application.phone = request.user.phone

        # Требования меро (db.md правило 6): если волонтёр не соответствует хотя бы
        # одному — заявка сразу уходит в резерв, без особого сообщения пользователю
        # (обычное «заявка отправлена»); причина — в уведомлении тим-лидеру.
        from blog.services.requirements import check_application_requirements
        req_check = check_application_requirements(application.event, request.user)
        if req_check['auto_reject']:
            application.status = 'rejected'
            application.auto_reject_reason = '; '.join(req_check['reasons'])

        # Набор закрыт на все выбранные (или на все смены меро, если ничего не
        # выбирали) смены — заявку всё равно принимаем, но сразу в резерв: волонтёр
        # заранее видит, что мест нет, вместо того чтобы блокировать подачу целиком.
        selected_shifts = form.cleaned_data.get('selected_shifts') or application.event.shifts.all()
        if not application.auto_reject_reason and not selected_shifts.filter(recruit_status='open').exists():
            application.status = 'rejected'
            application.auto_reject_reason = 'Набор на выбранные смены закрыт — заявка в резерве'

        application.save()
        _fill_application_shifts(application, form.cleaned_data.get('selected_shifts'))
        notifications_service.notify_application_submitted(application, unknown_age=req_check['unknown_age'])
        logger.info(
            'Заявка подана через веб: application=%s event=%s by=%s%s',
            application.id, application.event_id, actor(request.user),
            f' auto_reject={application.auto_reject_reason!r}' if application.auto_reject_reason else '',
        )
        if application.status == 'rejected' and 'закрыт' in (application.auto_reject_reason or ''):
            messages.success(
                request,
                'Заявка принята! Набор на это мероприятие уже закрыт, поэтому вы в резерве — '
                'мы свяжемся, если освободится место.',
            )
        else:
            messages.success(request, 'Заявка отправлена.')
        return modal_form_response(request, None, None, success_redirect=_referer_or(request))
    return modal_form_response(
        request, 'blog/application_form.html',
        {'form': form, 'title': 'Подать заявку на мероприятие', 'submit_label': 'Отправить заявку'},
        partial_template='blog/partials/_application_form_body.html',
    )


@manager_required
def application_manual_create(request):
    """Ручное добавление заявок волонтёров менеджером (пайплайн как у веб-подачи/импорта).
    За раз — на ОДНО мероприятие, но сразу на нескольких волонтёров. Волонтёры выбираются
    remote-виджетом выбора (data-select-remote="users"); новый волонтёр создаётся заранее отдельным
    AJAX-запросом (см. quick_create_volunteer) и приходит сюда уже обычным user_id —
    единая точка создания заявок, без спецлогики "нового по ФИО" в этой вьюхе.

    Мероприятие: если пришло `?event=<id>` (кнопка на странице меро) — оно зафиксировано
    и не выбирается; иначе (страница заявок) — выбирается из списка."""
    from blog.services.applications import create_manual_application

    fixed_event_id = request.GET.get('event') or request.POST.get('event')
    fixed_event = Event.objects.filter(pk=fixed_event_id).first() if fixed_event_id else None

    if request.method == 'POST':
        event = fixed_event or Event.objects.filter(pk=request.POST.get('event')).first()
        if not event:
            return JsonResponse({'errors': {'event': ['Выберите мероприятие.']}}, status=400)

        user_ids = request.POST.getlist('users')
        if not user_ids:
            return JsonResponse({'errors': {'users': ['Выберите хотя бы одного волонтёра.']}}, status=400)

        targets = list(User.objects.filter(id__in=user_ids))

        created = 0
        skipped = 0
        for user in targets:
            _, was_created = create_manual_application(event, user, created_by=request.user)
            if was_created:
                created += 1
            else:
                skipped += 1

        msg = f'Добавлено заявок: {created}.'
        if skipped:
            msg += f' Пропущено (уже есть активная заявка): {skipped}.'
        messages.success(request, msg)
        # Возврат туда, откуда пришли (страница меро или заявок).
        redirect_url = reverse('event_detail', args=[event.id]) if fixed_event else _referer_or(request, default='pending_applications')
        return modal_form_response(request, None, None, success_redirect=redirect_url)

    # GET → форма в модалке. Список меро для выбора (если не зафиксировано). Пул
    # волонтёров НЕ рендерим в контекст — его грузит единый remote-виджет выбора
    # (data-select-remote="users") общим AJAX-запросом с ранжированием и лимитом.
    events = None if fixed_event else Event.objects.order_by('-created_at')
    return modal_form_response(
        request, 'blog/application_manual_form.html',
        {
            'fixed_event': fixed_event,
            'events': events,
            'title': ('Добавить волонтёров на «%s»' % fixed_event.title) if fixed_event else 'Добавить заявки волонтёров',
            'submit_label': 'Добавить',
        },
        partial_template='blog/partials/_application_manual_form_body.html',
    )


@login_required
def application_edit(request, application_id):
    """Редактирование своей заявки (смены/функция/роль) — вместо создания дубля."""
    application = get_object_or_404(Application, pk=application_id, user=request.user)
    if application.status not in ('new', 'approved'):
        messages.error(request, 'Эта заявка уже неактивна и не может быть отредактирована.')
        return redirect('dashboard')

    form = ApplicationForm(request.POST or None, user=request.user, instance=application)
    if request.method == 'POST' and form.is_valid():
        application = form.save(commit=False)
        application.save()
        _fill_application_shifts(application, form.cleaned_data.get('selected_shifts'))
        messages.success(request, 'Заявка обновлена.')
        return modal_form_response(request, None, None, success_redirect=_referer_or(request))
    return modal_form_response(
        request, 'blog/application_form.html',
        {'form': form, 'title': 'Редактировать заявку', 'submit_label': 'Сохранить', 'application': application},
        partial_template='blog/partials/_application_form_body.html',
    )


@login_required
def application_cancel(request, application_id):
    """Отмена заявки волонтёром — только пока до ближайшей выбранной смены осталось
    больше `const.late_cancel_hours`; причина обязательна. Правило — общее с ботом,
    см. `blog.services.applications.can_cancel_application`."""
    application = get_object_or_404(Application, pk=application_id, user=request.user)
    can_cancel, reason_code, late_cancel_hours = can_cancel_application(application)

    if not can_cancel:
        if reason_code == 'inactive':
            messages.error(request, 'Эта заявка уже неактивна.')
        else:
            messages.error(
                request,
                f'Отменить заявку можно не позднее чем за {late_cancel_hours:g} ч. до начала мероприятия — '
                'обратитесь к тим-лидеру или менеджеру напрямую.',
            )
        return redirect('dashboard')

    form = ApplicationCancelForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        cancel_application(application, form.cleaned_data['reason'])
        messages.success(request, 'Заявка отменена.')
        return modal_form_response(request, None, None, success_redirect=_referer_or(request))
    return modal_form_response(
        request, 'blog/application_cancel_form.html',
        {'form': form, 'title': f'Отменить заявку на «{application.event.title}»', 'submit_label': 'Отменить заявку', 'application': application},
    )


@login_required
def event_shifts_json(request, event_id):
    """Список открытых смен мероприятия — для чип-виджета выбора смен в форме заявки
    (JS дозапрашивает при смене выбранного мероприятия, аналог поиска справочников)."""
    event = get_object_or_404(Event, pk=event_id)
    shifts = event.shifts.filter(recruit_status='open').order_by('day')
    return JsonResponse({
        'shifts': [
            {'id': s.id, 'label': f'{s.day.strftime("%d.%m.%Y")} {s.start_time.strftime("%H:%M")}–{s.end_time.strftime("%H:%M")}'}
            for s in shifts
        ],
    })


@login_required
def application_process(request, application_id):
    application = get_object_or_404(Application.objects.select_related('event'), pk=application_id)
    if not can_process_applications(request.user, application.event_id):
        raise PermissionDenied('Нет прав на обработку заявок этого мероприятия.')
    if application.event.event_status == 'finished':
        raise PermissionDenied('Мероприятие завершено — заявки менять больше нельзя.')

    # Возвращаемся туда, откуда пришёл запрос (страница мероприятия или
    # список необработанных заявок), а не всегда на карточку мероприятия.
    next_url = request.POST.get('next')
    if next_url:
        redirect_url = next_url
    else:
        redirect_url = reverse('event_detail', args=[application.event_id]) + '#applications'

    new_status = request.POST.get('status')
    if new_status not in ('approved', 'rejected'):
        messages.error(request, 'Некорректный статус.')
        return redirect(redirect_url)

    process_application(application, new_status, request.user)
    messages.success(request, f'Заявка #{application.id} обработана: {application.get_status_display()}.')
    return redirect(redirect_url)


@login_required
def application_shift_process(request, application_id, shift_id):
    """Принять/отклонить заявку ТОЛЬКО на одну смену (таблица набора на event_detail,
    где заявка на несколько смен показывается в таблице каждой смены отдельно) —
    остальные смены той же заявки не затрагиваются (ApplicationShiftDecision)."""
    application = get_object_or_404(Application.objects.select_related('event'), pk=application_id)
    shift = get_object_or_404(EventShift, pk=shift_id, event=application.event)
    if not can_process_applications(request.user, application.event_id):
        raise PermissionDenied('Нет прав на обработку заявок этого мероприятия.')
    if application.event.event_status == 'finished':
        raise PermissionDenied('Мероприятие завершено — заявки менять больше нельзя.')

    redirect_url = reverse('event_detail', args=[application.event_id]) + '#applications'
    new_status = request.POST.get('status')
    if new_status not in ('approved', 'rejected'):
        messages.error(request, 'Некорректный статус.')
        return redirect(redirect_url)

    from blog.services.applications import process_shift_decision
    process_shift_decision(application, shift, new_status, request.user)
    messages.success(request, f'Заявка на смену {shift.day.strftime("%d.%m.%Y")} обработана.')
    return redirect(redirect_url)


@login_required
def shift_applications_approve_all(request, event_id, shift_id):
    """«Принять всех» на КОНКРЕТНУЮ смену — одобряет все нерешённые (new) решения по
    заявкам на эту смену. Дополняет общую кнопку «Принять всех» по мероприятию: та
    обрабатывает все new-заявки целиком, а эта — только выбранную смену."""
    event = get_object_or_404(Event, pk=event_id)
    shift = get_object_or_404(EventShift, pk=shift_id, event=event)
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет прав на обработку заявок этого мероприятия.')
    if event.event_status == 'finished':
        raise PermissionDenied('Мероприятие завершено — заявки менять больше нельзя.')

    redirect_url = reverse('event_detail', args=[event.id]) + '#applications'
    if request.method != 'POST':
        return redirect(redirect_url)

    from blog.services.applications import ensure_shift_decisions, process_shift_decision

    # Гарантируем, что у всех активных заявок на это меро есть решения по сменам,
    # затем берём new-решения именно этой смены.
    for app in event.applications.exclude(status='cancelled').prefetch_related('selected_shifts', 'event__shifts'):
        ensure_shift_decisions(app)

    pending_decisions = list(
        ApplicationShiftDecision.objects.filter(shift=shift, status='new')
        .exclude(application__status='cancelled')
        .select_related('application')
    )
    if not pending_decisions:
        messages.info(request, f'На смене {shift.day.strftime("%d.%m.%Y")} нет необработанных заявок.')
        return redirect(redirect_url)

    for decision in pending_decisions:
        process_shift_decision(decision.application, shift, 'approved', request.user)
    messages.success(
        request,
        f'Принято заявок на смену {shift.day.strftime("%d.%m.%Y")}: {len(pending_decisions)}.'
    )
    return redirect(redirect_url)


def _pending_applications_queryset(event_id=None):
    qs = Application.objects.filter(status='new').select_related('event')
    if event_id:
        qs = qs.filter(event_id=event_id)
    return qs


@login_required
def application_process_all(request, event_id=None):
    """«Принять всех» / «Обработать все заявки» — approve всех new-заявок сразу
    (в рамках одного мероприятия, если event_id передан, иначе глобально).

    Если одобрение всех заявок даёт перебор относительно нужного количества
    волонтёров — сначала показываем страницу-уточнение с расчётом (на сколько
    человек больше, % от заявленного) и явным подтверждением; без перебора —
    принимаем сразу."""
    event = get_object_or_404(Event, pk=event_id) if event_id else None
    if event:
        if not can_process_applications(request.user, event.id):
            raise PermissionDenied('Нет прав на обработку заявок этого мероприятия.')
        if event.event_status == 'finished':
            raise PermissionDenied('Мероприятие завершено — заявки менять больше нельзя.')
    elif not is_manager(request.user):
        raise PermissionDenied('Нет прав на обработку заявок.')

    pending = _pending_applications_queryset(event_id)
    pending_count = pending.count()

    redirect_url = reverse('event_detail', args=[event.id]) + '#applications' if event else reverse('pending_applications')

    if pending_count == 0:
        messages.info(request, 'Необработанных заявок нет.')
        return redirect(redirect_url)

    needed = sum(s.volunteer_needed for s in event.shifts.all()) if event else None
    approved_now = event.applications.filter(status='approved').count() if event else None
    overflow = None
    if needed:
        total_after = approved_now + pending_count
        if total_after > needed:
            overflow = {
                'extra': total_after - needed,
                'pct': round(total_after / needed * 100),
                'needed': needed,
                'total_after': total_after,
            }

    confirmed = request.POST.get('confirm') == 'yes'
    if overflow and not confirmed:
        # Первый заход (без явного "да, принять всех") — показываем расчёт перебора,
        # ничего не меняем. Работает и для POST от кнопки «Принять всех», и для GET.
        return render(request, 'blog/application_process_all_confirm.html', {
            'event': event,
            'pending_count': pending_count,
            'overflow': overflow,
            'redirect_url': redirect_url,
            'confirm_action_url': request.path,
        })

    for application in pending:
        process_application(application, 'approved', request.user)
    messages.success(request, f'Принято заявок: {pending_count}.')
    return redirect(redirect_url)


def _rows_missing_last(rows):
    """Строки превью импорта с недостающим мероприятием (event_missing) — в конец
    списка: сначала показываем то, что уже готово к загрузке, а «незакрытые вопросы»
    (нужно создать меро) — внизу, стабильно сохраняя исходный порядок внутри групп."""
    return sorted(rows, key=lambda row: bool(row.get('event_missing')))


@manager_required
def import_preview(request):
    """Excel-импорт заявок. Обычный вход (со страницы «Заявки») — мероприятие
    определяется из колонки файла. Вход с конкретного мероприятия (?event=<id>,
    кнопка «Загрузить заявки» на event_detail) — событие ЗАФИКСИРОВАНО: колонка
    «Мероприятие» в файле полностью игнорируется для привязки, остальной пайплайн
    (превью → подтверждение → commit) идентичен обычной загрузке.

    Если в файле встречаются другие названия мероприятия (расхождение с fixed_event)
    — показываем отдельный экран с перечнем уникальных названий и просим явно
    подтвердить «всё равно добавить», прежде чем показать обычное превью."""
    fixed_event_id = request.GET.get('event') or request.POST.get('event')
    fixed_event = Event.objects.filter(pk=fixed_event_id).first() if fixed_event_id else None

    form = ExcelImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and 'excel_file' in request.FILES and form.is_valid():
        result = import_service.parse_excel(request.FILES['excel_file'], fixed_event=fixed_event)
        request.session['import_rows'] = [
            {**row, 'submitted_at': row['submitted_at'].isoformat() if row.get('submitted_at') else None}
            for row in result['rows']
        ]
        request.session['import_fixed_event_id'] = fixed_event.id if fixed_event else None

        if fixed_event and result['mismatched_titles']:
            return render(request, 'blog/import_mismatch_confirm.html', {
                'fixed_event': fixed_event,
                'mismatched_titles': result['mismatched_titles'],
                'errors': result['errors'],
                'rows_count': len(result['rows']),
            })
        return render(request, 'blog/import_preview.html', {
            'rows': _rows_missing_last(result['rows']), 'errors': result['errors'], 'fixed_event': fixed_event,
            'has_missing_events': any(row.get('event_missing') for row in result['rows']),
        })

    # Подтверждение "всё равно добавить" после экрана расхождений — строки уже в
    # сессии из предыдущего шага, просто показываем обычное превью.
    if request.method == 'POST' and request.POST.get('confirm_mismatch') == 'yes':
        rows = request.session.get('import_rows', [])
        return render(request, 'blog/import_preview.html', {
            'rows': _rows_missing_last(rows), 'errors': [], 'fixed_event': fixed_event,
            'has_missing_events': any(row.get('event_missing') for row in rows),
        })

    # Возврат на превью без нового файла (напр. после создания мероприятия из
    # модалки, открытой прямо с этого экрана) — строки уже в сессии, пересчитываем
    # event_missing по актуальному состоянию БД и показываем то же превью снова.
    if request.method == 'GET' and request.session.get('import_rows'):
        rows = import_service.refresh_missing_events(request.session['import_rows'])
        request.session['import_rows'] = rows
        return render(request, 'blog/import_preview.html', {
            'rows': _rows_missing_last(rows), 'errors': [], 'fixed_event': fixed_event,
            'has_missing_events': any(row.get('event_missing') for row in rows),
        })

    return render(request, 'blog/import_form.html', {'form': form, 'fixed_event': fixed_event})


@manager_required
def import_commit(request):
    if request.method != 'POST':
        return redirect('import_preview')

    rows = request.session.get('import_rows', [])
    rows = import_service.refresh_missing_events(rows)
    still_missing = sorted({row['event_title'] for row in rows if row.get('event_missing')})
    if still_missing:
        request.session['import_rows'] = rows
        titles = '», «'.join(still_missing)
        messages.error(
            request,
            f'Сначала создайте мероприятие(я) «{titles}» — без этого заявки на них загрузить нельзя.',
        )
        return redirect('import_preview')

    request.session.pop('import_rows', None)
    fixed_event_id = request.session.pop('import_fixed_event_id', None)
    for row in rows:
        if row.get('submitted_at'):
            row['submitted_at'] = datetime.datetime.fromisoformat(row['submitted_at'])

    result = import_service.commit_import(rows)
    logger.info(
        'Excel-импорт заявок подтверждён: by=%s created=%s updated=%s skipped=%s fixed_event=%s',
        actor(request.user), result['created'], result['updated'], result['skipped'], fixed_event_id,
    )
    msg = f'Новых заявок: {result["created"]}.'
    if result['updated']:
        msg += f' Обновлено (изменилось содержание): {result["updated"]}.'
    if result['skipped']:
        msg += f' Без изменений: {result["skipped"]}.'
    messages.success(request, msg)
    return redirect('event_detail', event_id=fixed_event_id) if fixed_event_id else redirect('event_list')


# ---------------------------------------------------------------------------
# Статистика / профиль (Этап 5-6, публичный + расширенный уровень)
# ---------------------------------------------------------------------------

@login_required
def profile_detail(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    is_owner = request.user.id == target.id
    is_mgr = is_manager(request.user)
    # Расширенный + внутренний профиль: владелец, менеджер, либо ТЛ в контексте
    # своего мероприятия (access-control.md, правило 5).
    has_extended = has_extended_access_to_profile(request.user, target)
    # Комментарии волонтёр не видит никогда, даже о себе (access-control.md, правило 6).
    can_see_comments = is_mgr or (is_team_leader(request.user) and has_extended and not is_owner)

    from blog.services.experience import build_experience
    experience = build_experience(target)

    context = {
        'target': target,
        'is_owner': is_owner,
        'is_manager': is_mgr,
        'has_extended_access': has_extended,
        'can_see_comments': can_see_comments,
        'experience': experience,
        # Ссылка «Скопировать опыт» — публичная страница опыта по токену (раздел 4).
        'experience_share_url': request.build_absolute_uri(
            reverse('public_experience', args=[target.experience_token])
        ),
        'experience_form': ExternalExperienceForm() if is_owner else None,
    }

    # Блок «Активные заявки» — заявки на мероприятия, которые ещё НЕ прошли (статус
    # меро не 'passed'/'finished'). Видят и владелец, и менеджер/ТЛ на чужом профиле.
    # Как только мероприятие прошло — его заявка исчезает из блока (см. шаблон).
    if is_owner or has_extended:
        active_apps = (
            target.applications.select_related('event')
            .exclude(status='cancelled')
            .prefetch_related('event__shifts')
            .order_by('-created_at')
        )
        active_rows = []
        for app in active_apps:
            if app.event.compute_status() in ('passed', 'finished'):
                continue
            active_rows.append(app)
        context['active_applications'] = active_rows
        context['show_active_applications'] = True

    if is_owner:
        from blog.services.pgas_certificate import pgas_certificate_eligibility, only_verification_missing
        pgas = pgas_certificate_eligibility(target)
        context['pgas_eligible'] = pgas['eligible']
        context['pgas_missing'] = pgas['missing']
        context['pgas_only_verification_missing'] = only_verification_missing(target)

    if has_extended and not is_owner:
        from blog.services.pgas_certificate import compute_course_and_graduation
        context['course_info'] = compute_course_and_graduation(target)

    # Публичный блок ТЛ/менеджера (reports.md: кол-во меро как ТЛ, дата назначения).
    tl_role = target.team_leader_roles.filter(revoked_at__isnull=True).first()
    if tl_role:
        context['tl_role'] = tl_role
        context['tl_event_count'] = EventStaff.objects.filter(
            user=target, staff_role='team_lead'
        ).count()
    mgr_role = target.manager_roles.filter(revoked_at__isnull=True).first()
    if mgr_role:
        context['mgr_role'] = mgr_role

    # Единая таблица «Мероприятия и заявки» — ТОЛЬКО для менеджера/ТЛ на ЧУЖОМ
    # профиле (has_extended and not is_owner). Волонтёр сам эту таблицу не видит
    # вовсе — у себя видит только блок «Мой опыт» (_experience_block.html:
    # участия центра + внешний опыт, без заявок и без статусов). Здесь — один
    # список строк на все заявки волонтёра (включая новые/отклонённые/отменённые,
    # которых волонтёр у себя не видит) + отдельными строками внешний опыт
    # (для него статус заявки/присутствие — прочерк, часы — 0).
    if has_extended and not is_owner:
        applications = list(
            target.applications.select_related('event')
            .prefetch_related('selected_shifts', 'event__shifts')
            .order_by('-created_at')
        )
        shift_ids_by_app = {
            app.id: [s.id for s in (app.selected_shifts.all() or app.event.shifts.all())]
            for app in applications
        }
        all_shift_ids = {sid for ids in shift_ids_by_app.values() for sid in ids}
        shifts_by_id = {s.id: s for s in EventShift.objects.filter(id__in=all_shift_ids)}
        participations = Participation.objects.filter(
            user=target, event_day_id__in=all_shift_ids,
        ).select_related('event_day')
        participation_by_shift = {p.event_day_id: p for p in participations}

        attendance_labels = dict(Participation.STATUS_CHOICES)
        rows = []
        for app in applications:
            shift_ids = shift_ids_by_app[app.id]
            shifts = sorted((shifts_by_id[sid] for sid in shift_ids if sid in shifts_by_id), key=lambda s: s.day)
            can_have_attended = app.status not in ('rejected', 'cancelled')
            attendance_display = None
            total_hours = 0
            if can_have_attended:
                shift_parts = [p for sid in shift_ids if (p := participation_by_shift.get(sid))]
                total_hours = sum(p.hours for p in shift_parts)
                if shift_parts:
                    status = 'attended' if any(p.status == 'attended' for p in shift_parts) else shift_parts[0].status
                    attendance_display = attendance_labels.get(status)
            rows.append({
                'kind': 'internal',
                'title': app.event.title,
                'event_id': app.event_id,
                'sort_date': shifts[0].day if shifts else None,
                'date_display': ', '.join(s.day.strftime('%d.%m.%y') for s in shifts) or '—',
                'application': app,
                'note': app.profile_note,
                'attendance_display': attendance_display,
                'total_hours': total_hours,
            })
        for exp in target.external_experiences.all():
            if exp.date and exp.date_to and exp.date_to != exp.date:
                date_display = f'{exp.date.strftime("%d.%m.%y")} — {exp.date_to.strftime("%d.%m.%y")}'
            elif exp.date:
                date_display = exp.date.strftime('%d.%m.%y')
            else:
                date_display = '—'
            rows.append({
                'kind': 'external',
                'title': exp.title,
                'event_id': None,
                'sort_date': exp.date,
                'date_display': date_display,
                'application': None,
                'note': exp.description,
                'attendance_display': None,
                'total_hours': 0,
            })
        # Свежие сверху; записи без даты — в конец (в отдельной группе, чтобы обратная
        # сортировка по дате не утаскивала их наверх).
        rows.sort(key=lambda r: (r['sort_date'] is None, r['sort_date'] and -r['sort_date'].toordinal()))
        context['profile_experience_rows'] = rows

    if has_extended:
        # Пул благодарственных писем: мероприятия с явкой и заданным шаблоном.
        context['letters_pool'] = (
            Event.objects.filter(
                shifts__participations__user=target,
                shifts__participations__status='attended',
                letter__isnull=False,
            )
            .distinct()
            .select_related('letter')
            .order_by('-created_at')
        )

    if is_mgr:
        context['churn_history'] = target.churn_history.select_related('season').order_by('-created_at')

    if can_see_comments:
        context['comments'] = target.received_comments.select_related('author', 'event').order_by('-created_at')
        if is_mgr:
            event_queryset = Event.objects.all()
        else:
            event_queryset = Event.objects.filter(
                staff__user=request.user, staff__staff_role='team_lead'
            ).exclude(event_status='finished')
        context['comment_form'] = UserCommentForm(event_queryset=event_queryset)

    return render(request, 'blog/profile_detail.html', context)


@login_required
def letter_view(request, user_id, event_id):
    """Благодарственное письмо — генерируется на лету, PDF не хранится
    (implementation-plan Этап 6.4). Страница свёрстана под печать/сохранение в PDF.

    Доступ: сам волонтёр, менеджер или ТЛ с расширенным доступом к профилю.
    """
    target = get_object_or_404(User, pk=user_id)
    event = get_object_or_404(Event.objects.select_related('letter', 'organization'), pk=event_id)

    if not has_extended_access_to_profile(request.user, target):
        raise PermissionDenied('Нет доступа к письмам этого волонтёра.')
    if not event.letter:
        raise PermissionDenied('У мероприятия не задан шаблон благодарственного письма.')

    attended = Participation.objects.filter(
        user=target, event_day__event=event, status='attended'
    ).select_related('event_day')
    if not attended.exists():
        raise PermissionDenied('Волонтёр не участвовал в этом мероприятии.')

    hours = sum(p.hours for p in attended)
    last_day = max(p.event_day.day for p in attended)

    return render(request, 'blog/letter.html', {
        'target': target,
        'event': event,
        'letter': event.letter,
        'hours': hours,
        'last_day': last_day,
    })


@manager_required
def pending_applications(request):
    applications = Application.objects.filter(status='new').select_related('event', 'user').order_by('created_at')
    return render(request, 'blog/pending_applications.html', {
        'applications': applications,
        'pending_count': applications.count(),
    })


@login_required
def profile_comment_add(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    is_mgr = is_manager(request.user)
    can_comment = is_mgr or (
        is_team_leader(request.user)
        and has_extended_access_to_profile(request.user, target)
        and request.user.id != target.id
    )
    if not can_comment:
        raise PermissionDenied('Нет прав оставлять комментарии этому волонтёру.')

    if is_mgr:
        event_queryset = Event.objects.all()
    else:
        event_queryset = Event.objects.filter(
            staff__user=request.user, staff__staff_role='team_lead'
        ).exclude(event_status='finished')

    if request.method == 'POST':
        form = UserCommentForm(request.POST, event_queryset=event_queryset)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.target_user = target
            comment.author = request.user
            comment.save()
            messages.success(request, 'Комментарий добавлен.')
    return redirect('profile_detail', user_id=target.id)


# ---------------------------------------------------------------------------
# Отчёты (Этап 5, reports.md раздел 7)
# ---------------------------------------------------------------------------

def _report_period_range(request):
    """Диапазон дат для отчёта: пресет (`period`) или произвольный диапазон
    (`date_from`/`date_to` — brandbook §6.3, date range picker, стиль Booking.com)."""
    today = timezone.now().date()

    raw_from = request.GET.get('date_from')
    raw_to = request.GET.get('date_to')
    if raw_from and raw_to:
        try:
            date_from = datetime.date.fromisoformat(raw_from)
            date_to = datetime.date.fromisoformat(raw_to)
            if date_from <= date_to:
                return 'custom', date_from, date_to
        except ValueError:
            pass

    period = request.GET.get('period', 'season')
    if period == 'yesterday':
        date_from = date_to = today - datetime.timedelta(days=1)
        return period, date_from, date_to
    if period == 'today':
        return period, today, today
    if period == 'week':
        return period, today - datetime.timedelta(days=7), today
    if period == 'month':
        return period, today - datetime.timedelta(days=30), today
    if period == 'season':
        current = Season.objects.filter(start_season__lte=today).order_by('-start_season').first()
        if current:
            return period, current.start_season, current.end_season or today
        return period, today - datetime.timedelta(days=120), today
    if period == 'last_season':
        current = Season.objects.filter(start_season__lte=today).order_by('-start_season').first()
        previous_qs = Season.objects.order_by('-start_season')
        if current:
            previous_qs = previous_qs.filter(start_season__lt=current.start_season)
        previous = previous_qs.first()
        if previous:
            return period, previous.start_season, previous.end_season or (current.start_season - datetime.timedelta(days=1) if current else today)
        return period, today - datetime.timedelta(days=240), today - datetime.timedelta(days=120)

    # Фоллбэк, если сезонов в базе ещё нет вовсе.
    period = 'season'
    return period, today - datetime.timedelta(days=120), today


def _report_scope(request):
    """Охват отчёта — два взаимоисключающих режима (reports_template.md «Выбор охвата»):
    `scope=events` + `event_ids=1,2,3` — по явному списку мероприятий (даты игнорируются),
    иначе — по периоду через `_report_period_range`. Возвращает
    (scope_mode, period, date_from, date_to, event_ids).

    Оставлено для генераторов экспорта (report_*_export), которые ходят по старой схеме
    `?scope=events&event_ids=…`. Экранный ERP-дашборд использует `_report_erp_scope`."""
    raw_event_ids = request.GET.get('event_ids', '').strip()
    if request.GET.get('scope') == 'events' and raw_event_ids:
        event_ids = [int(x) for x in raw_event_ids.split(',') if x.strip().isdigit()]
        if event_ids:
            return 'events', None, None, None, event_ids

    period, date_from, date_to = _report_period_range(request)
    return 'period', period, date_from, date_to, None


def _parse_int_csv(raw):
    return [int(x) for x in (raw or '').split(',') if x.strip().lstrip('-').isdigit()]


def _report_erp_scope(request):
    """Охват ERP-дашборда «Отчёты»: диапазон дат + статус-режим пула меро
    (all/ongoing/past) + список УБРАННЫХ пользователем меро (`exclude`). Пул строится от
    дат, из него исключаются `exclude` — так ссылка компактна (даты+исключения), переживает
    появление новых меро и совпадает с механикой чипов-«убирания» на странице.

    Возвращает dict: period, date_from, date_to, event_status, exclude_ids, event_ids
    (итоговый охват — id меро пула минус исключённые)."""
    period, date_from, date_to = _report_period_range(request)
    event_status = request.GET.get('event_status', 'all')
    if event_status not in reports_service.EVENT_SCOPE_MODES:
        event_status = 'all'
    exclude_ids = _parse_int_csv(request.GET.get('exclude'))
    event_ids = reports_service.events_pool(date_from, date_to, event_status, exclude_ids)
    return {
        'period': period,
        'date_from': date_from,
        'date_to': date_to,
        'event_status': event_status,
        'exclude_ids': exclude_ids,
        'event_ids': event_ids,
    }


# ERP-хаб «Отчёты»: верхний переключатель режимов. Активный режим — в URL (?view=…),
# чтобы копируемая ссылка и кнопка «назад» помнили, где был пользователь.
REPORT_VIEWS = [
    {'key': 'dashboard', 'icon': '📊', 'title': 'Дашборд', 'desc': 'Ключевые показатели и графики за охват'},
    {'key': 'tables', 'icon': '🗂️', 'title': 'Таблицы', 'desc': 'Детальные списки: волонтёры, меро, набор, персонал'},
    {'key': 'dobro', 'icon': '❤️', 'title': 'Добро.ру', 'desc': 'Простановка часов и выгрузка отчёта'},
]
# Под-таблицы внутри режима «Таблицы».
REPORT_TABLES = [
    {'key': 'volunteers', 'title': 'Волонтёры'},
    {'key': 'events', 'title': 'Мероприятия'},
    {'key': 'teamleaders', 'title': 'Тим-лидеры'},
    {'key': 'managers', 'title': 'Менеджеры'},
    {'key': 'applications', 'title': 'Заявки'},
]


def _report_event_chips(date_from, date_to, event_status, exclude_ids):
    """Данные для чипов охвата (выбор/убирание мероприятий, как чипы категорий): весь пул
    периода данного статус-режима, с флагом excluded по каждому. Пользователь «убирает»
    ненужные — их id уходят в ?exclude=."""
    from data_base import data_controller as dc
    exclude_set = set(exclude_ids or [])
    pool_all = reports_service.events_pool(date_from, date_to, event_status, exclude_ids=None)
    chips = []
    for event in dc.events_qs().filter(id__in=pool_all).prefetch_related('shifts'):
        first_day = event.shifts.order_by('day').values_list('day', flat=True).first()
        chips.append({
            'id': event.id,
            'title': event.title,
            'date': first_day.strftime('%d.%m.%Y') if first_day else None,
            'excluded': event.id in exclude_set,
        })
    # Свежие сверху (по первой смене).
    chips.sort(key=lambda c: c['date'] or '', reverse=True)
    return chips


@manager_required
def report_period(request):
    """ERP-хаб «Отчёты». GET без ?partial=1 — шелл (переключатель режимов + строка охвата,
    панель подгружается AJAX'ом). GET с ?partial=1&view=… — partial активного режима."""
    view_key = request.GET.get('view', 'dashboard')
    if view_key not in {v['key'] for v in REPORT_VIEWS}:
        view_key = 'dashboard'
    scope = _report_erp_scope(request)
    wants_partial = request.GET.get('partial') == '1' or is_ajax(request)

    # Смена охвата (даты/статус/исключения) обновляет весь блок «строка охвата»
    # AJAX'ом целиком (пресеты/лейбл диапазона/статус-режим/чипы) — сервер остаётся
    # единственным источником истины для того, какая кнопка активна и что показано
    # в лейбле диапазона; раньше окно перезагружалось целиком, и браузер прыгал
    # наверх. Панель режима обновляется отдельным запросом тем же fetch'ем.
    if request.GET.get('scope_partial') == '1':
        chips = _report_event_chips(scope['date_from'], scope['date_to'], scope['event_status'], scope['exclude_ids'])
        return render(request, 'blog/partials/_report_scope.html', {
            'period': scope['period'],
            'date_from': scope['date_from'],
            'date_to': scope['date_to'],
            'event_status': scope['event_status'],
            'event_chips': chips,
        })

    if wants_partial:
        return _report_render_panel(request, view_key, scope)

    # Шелл: строка охвата (даты/статус-режим/чипы) + переключатель режимов.
    chips = _report_event_chips(scope['date_from'], scope['date_to'], scope['event_status'], scope['exclude_ids'])
    return render(request, 'blog/report_period.html', {
        'views': REPORT_VIEWS,
        'active_view': view_key,
        'period': scope['period'],
        'date_from': scope['date_from'],
        'date_to': scope['date_to'],
        'event_status': scope['event_status'],
        'exclude_ids': scope['exclude_ids'],
        'event_chips': chips,
    })


def _report_scope_querystring(scope, extra=None):
    """Собрать query-string охвата (даты/статус/исключения) для ссылок экспорта и
    AJAX-подгрузок панелей — чтобы панель считалась по тому же охвату, что на экране."""
    from urllib.parse import urlencode
    params = {
        'date_from': scope['date_from'].isoformat(),
        'date_to': scope['date_to'].isoformat(),
        'event_status': scope['event_status'],
    }
    if scope['exclude_ids']:
        params['exclude'] = ','.join(str(i) for i in scope['exclude_ids'])
    if extra:
        params.update(extra)
    return urlencode(params)


def _report_render_panel(request, view_key, scope):
    """Рендер partial активного режима хаба (дашборд/таблицы/добро)."""
    if view_key == 'dobro':
        return _report_dobro_panel(request, scope)
    if view_key == 'tables':
        return _report_tables_panel(request, scope)
    return _report_dashboard_panel(request, scope)


def _report_dashboard_panel(request, scope):
    """Панель «Дашборд»: KPI-плитки + графики (набор по меро, явка-бублик, топ волонтёров,
    оценки). Воронка/динамика/категории убраны из UI, поэтому не считаем (dynamics больше
    не нужен). Считаем только то, что показывается на экране."""
    event_ids = scope['event_ids']
    date_from, date_to = scope['date_from'], scope['date_to']
    data = reports_service.period_report(date_from, date_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    return render(request, 'blog/partials/_report_dashboard.html', {
        'report': data,
        'efficiency': efficiency,
        'scope_qs': _report_scope_querystring(scope),
        'event_count': len(event_ids),
    })


def _report_tables_panel(request, scope):
    """Панель «Таблицы» (ERP): под-выбор таблицы + сама таблица. Каждая таблица считает
    только свою функцию (ленивость), выбор таблицы — в ?table=."""
    table_key = request.GET.get('table', 'volunteers')
    if table_key not in {t['key'] for t in REPORT_TABLES}:
        table_key = 'volunteers'
    event_ids = scope['event_ids']
    date_from, date_to = scope['date_from'], scope['date_to']

    context = {
        'tables': REPORT_TABLES,
        'active_table': table_key,
        'scope_qs': _report_scope_querystring(scope),
        'event_count': len(event_ids),
    }
    if table_key == 'volunteers':
        context['rows'] = reports_service.volunteers_table(date_from, date_to, event_ids=event_ids)
    elif table_key == 'events':
        rows, max_shifts = reports_service.events_table(date_from, date_to, event_ids=event_ids)
        # Дополняем список смен до max_shifts пустыми ячейками — шаблон тогда просто
        # итерирует по row.shift_cells и рисует ровно N колонок «Смена k» у всех строк.
        for r in rows:
            r['shift_cells'] = list(r['shift_cells']) + ['—'] * (max_shifts - len(r['shift_cells']))
        context['rows'] = rows
        context['shift_columns'] = range(1, max_shifts + 1)
    elif table_key == 'teamleaders':
        context['rows'] = reports_service.team_leaders_table(date_from, date_to, event_ids=event_ids)
    elif table_key == 'managers':
        context['rows'] = reports_service.managers_table(date_from, date_to, event_ids=event_ids)
    elif table_key == 'applications':
        context['rows'] = reports_service.applications_table(date_from, date_to, event_ids=event_ids)
    return render(request, 'blog/partials/_report_tables.html', context)


def _report_dobro_panel(request, scope):
    """Панель «Добро.ру»: перенос страницы dobro_page — таблица ссылок с чекбоксом
    «часы проставлены» (переключается AJAX'ом) + кнопка выгрузки отчёта.

    Фильтруется тем же охватом (event_ids), что дашборд/таблицы — раньше показывала
    вообще все ссылки/меро в системе независимо от выбранного периода/исключений.

    Дополнительные фильтры хедера: ?only_unlogged=1 (часы не проставлены) и
    ?has_link=yes|no (есть/нет URL у ссылки)."""
    only_unlogged = request.GET.get('only_unlogged') == '1'
    has_link = request.GET.get('has_link')  # 'yes' | 'no' | None
    if has_link not in ('yes', 'no'):
        has_link = None
    rows, unlogged_event_ids = _dobro_rows(
        only_unlogged=only_unlogged, event_ids=scope['event_ids'], has_link=has_link,
    )
    return render(request, 'blog/partials/_report_dobro.html', {
        'rows': rows,
        'only_unlogged': only_unlogged,
        'has_link': has_link,
        'unlogged_event_ids': unlogged_event_ids,
        'scope_qs': _report_scope_querystring(scope),
    })


@manager_required
def report_events_search(request):
    """Поиск мероприятий для модалки выбора охвата «по мероприятиям» (reports_template.md).
    Полный список без поиска теперь грузится сразу со страницей (report_period,
    recent_events_json) — этот эндпоинт используется только при вводе текста в поиск."""
    from data_base import data_controller as dc
    query = request.GET.get('q', '').strip()
    events = dc.events_qs().order_by('-created_at')
    if query:
        events = events.filter(title__icontains=query)

    def _brief(event):
        day = event.shifts.order_by('day').values_list('day', flat=True).first()
        return {
            'id': event.id, 'title': event.title,
            'date': day.strftime('%d.%m.%Y') if day else None,
            'dobro_unlogged': event.dobro_ru_link_kind != 'none' and not event.dobro_ru_hours_logged,
        }

    return JsonResponse({'events': [_brief(e) for e in events]})


def _xlsx_response(workbook, filename):
    from django.http import HttpResponse
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response


@manager_required
def report_period_export(request):
    """Excel-отчёт за охват (.xlsx): по листу на каждую экранную таблицу ERP-раздела
    (Волонтёры / Мероприятия / Тим-лидеры / Менеджеры / Заявки). Охват — тот же, что на
    экране (даты + статус-режим + убранные меро), поэтому парсим ERP-охват."""
    scope = _report_erp_scope(request)
    wb = report_exports.build_period_workbook(
        scope['date_from'], scope['date_to'], scope['event_ids'],
        scope_mode='events', compare_mode='adjacent',
    )
    filename = f"report_{scope['date_from']}_{scope['date_to']}.xlsx"
    return _xlsx_response(wb, filename)


@manager_required
def report_period_pdf(request, variant):
    """PDF-отчёт за охват (reports_template.md, «Отчёт за период (общий)»).
    variant='external' — обезличенный (для руководства), 'internal' — с именами
    и операционными данными (нагрузка персонала, retention/churn, проблемные зоны)."""
    if variant not in ('external', 'internal'):
        raise PermissionDenied('Неизвестная вариация отчёта.')

    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    compare_mode = request.GET.get('compare', 'adjacent')
    if compare_mode not in ('adjacent', 'year_ago'):
        compare_mode = 'adjacent'

    prev_from = prev_to = None
    if scope_mode == 'period':
        prev_from, prev_to = reports_service.previous_period_range(date_from, date_to, compare_mode)

    data = reports_service.period_report(date_from, date_to, prev_from, prev_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    timing = reports_service.application_timing(date_from, date_to, event_ids=event_ids)
    post_timing = reports_service.post_publication_timing(date_from, date_to, event_ids=event_ids)
    weekly = reports_service.weekly_dynamics(date_from, date_to, event_ids=event_ids)

    context = {
        'variant': variant,
        'is_internal': variant == 'internal',
        'scope_mode': scope_mode,
        'date_from': date_from,
        'date_to': date_to,
        'compare_mode': compare_mode,
        'generated_at': timezone.now(),
        'report': data,
        'efficiency': efficiency,
        'timing': timing,
        'post_timing': post_timing,
    }
    if variant == 'internal':
        context['staff'] = reports_service.staff_load(date_from, date_to, event_ids=event_ids)

    if data['category_breakdown']:
        context['category_chart'] = charts_service.bar_chart(
            [c['name'] or 'Без категории' for c in data['category_breakdown']],
            [c['volunteers'] for c in data['category_breakdown']],
            title='Распределение по категориям', ylabel='Волонтёров',
        )
    context['funnel_chart'] = charts_service.funnel_chart([
        ('Подано', data['funnel']['submitted']),
        ('Одобрено', data['funnel']['approved']),
        ('Явка', data['funnel']['attended']),
        ('Неявка без предупр.', data['funnel']['unexcused']),
    ])
    if weekly:
        context['weekly_chart'] = charts_service.bar_chart(
            [w['from'].strftime('%d.%m') for w in weekly], [w['hours'] for w in weekly],
            title='Динамика по неделям', ylabel='Часы',
        )
    if timing['density']:
        context['timing_chart'] = charts_service.bar_chart(
            [d['label'] for d in timing['density']], [d['count'] for d in timing['density']],
            title='Отклик на мероприятие', ylabel='Заявок',
        )
    if variant == 'internal':
        context['churn_chart'] = charts_service.histogram_chart(
            [b['label'] for b in data['churn_histogram']], [b['count'] for b in data['churn_histogram']],
            title='Распределение churn_score',
        )

    builder = report_builders_service.build_period_report(context)
    return docx_response(builder, f'period_report_{variant}.docx')


@manager_required
def report_event_export(request, event_id):
    """Excel-отчёт по одному мероприятию (reports_template.md §4)."""
    event = get_object_or_404(Event, pk=event_id)
    wb = report_exports.build_event_workbook(event.id)
    return _xlsx_response(wb, f"event_{event.id}_report.xlsx")


@manager_required
def report_event_pdf(request, event_id):
    """PDF-отчёт по одному мероприятию (reports_template.md §4), включая график
    «Жизнь мероприятия» (события меро засечками + заявки точками, кластеризация)."""
    event = get_object_or_404(Event, pk=event_id)
    rep = report_exports.event_report(event.id)
    rep['generated_at'] = timezone.now()

    timeline = event_timeline_service.event_timeline_data(event)
    rep['timeline_chart'] = charts_service.event_timeline_chart(
        timeline['milestones'], timeline['applications']
    )
    builder = report_builders_service.build_event_report(rep)
    return docx_response(builder, f'event_{event.id}_report.docx')


def _person_report_context(user_id, date_from, date_to):
    rep = person_report_service.person_report(user_id, date_from, date_to)
    charts = {}
    if rep['scope']['scoped'] and rep['participations']:
        by_month = {}
        for p in rep['participations']:
            key = p['day'].strftime('%Y-%m') if p['day'] else '—'
            by_month[key] = by_month.get(key, 0) + (p['hours'] or 0)
        months = sorted(by_month.keys())
        charts['activity_chart'] = charts_service.bar_chart(
            months, [by_month[m] for m in months], title='Часы по месяцам', ylabel='Часы',
        )
    if rep['internal']['churn_history']:
        seasons = [h.season.start_season.strftime('%d.%m.%Y') for h in rep['internal']['churn_history']]
        scores = [h.churn_score for h in rep['internal']['churn_history']]
        charts['churn_chart'] = charts_service.line_chart(
            seasons, scores, title='Churn по сезонам', ylabel='Churn score',
        )
    rep.update(charts)
    return rep


@manager_required
def report_person_pdf(request, user_id):
    """PDF-отчёт по человеку (reports_template.md «Отчёт по человеку»): блоки A-D
    у всех, E/F добавляются автоматически при наличии активной роли ТЛ/менеджера.
    Охват — «за всё время» (без параметров) либо «за период» (date_from/date_to)."""
    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    rep = _person_report_context(user_id, date_from, date_to)
    context = {
        'rep': rep,
        'user': rep['user'],
        'scope': rep['scope'],
        'generated_at': timezone.now(),
    }
    builder = report_builders_service.build_person_report(rep)
    return docx_response(builder, f'person_{user_id}_report.docx')


@manager_required
def report_volunteers_pdf(request):
    """PDF-отчёт по волонтёрам: сводка сверху + карточки подряд по алфавиту
    (reports_template.md «Отчёт по волонтёрам»). Охват — всё время/период,
    выборка — по умолчанию все с хотя бы одной заявкой, либо явный список ?user_ids=."""
    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    raw_ids = request.GET.get('user_ids', '').strip()
    user_ids = [int(x) for x in raw_ids.split(',') if x.strip().isdigit()] if raw_ids else None

    rep = volunteers_report_service.volunteers_report(date_from, date_to, user_ids=user_ids)
    if rep['hours_distribution']:
        rep['hours_hist_chart'] = charts_service.histogram_chart(
            [str(i) for i in range(len(rep['hours_distribution']))],
            sorted(rep['hours_distribution'], reverse=True),
            title='Распределение часов волонтёров (по убыванию)',
        )
    if rep['top_volunteers']:
        rep['top_chart'] = charts_service.funnel_chart(
            [(f"{v['user'].full_name}", v['hours'] or 0) for v in rep['top_volunteers']],
            title='Топ-10 волонтёров по часам',
        )
    rep['churn_chart'] = charts_service.histogram_chart(
        [b['label'] for b in rep['churn_histogram']],
        [b['count'] for b in rep['churn_histogram']],
        title='Распределение churn_score',
    )
    rep['generated_at'] = timezone.now()
    builder = report_builders_service.build_volunteers_report(rep)
    return docx_response(builder, 'volunteers_report.docx')


@manager_required
def report_volunteers_export(request):
    """Excel-отчёт по волонтёрам: лист «Сводка» + лист «Волонтёры» + лист «Участия»."""
    from openpyxl import Workbook

    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    rep = volunteers_report_service.volunteers_report(date_from, date_to)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Сводка'
    ws.append(['Показатель', 'Значение'])
    for key, label in [
        ('total_volunteers', 'Всего волонтёров'), ('total_hours', 'Суммарно часов'),
        ('total_events', 'Суммарно участий'), ('avg_hours', 'Ср. часов на волонтёра'),
        ('new_count', 'Новых за охват'), ('star_count', 'Со звёздочкой ПГАС'),
        ('blacklisted_count', 'В блэклисте'), ('at_risk_count', 'На грани блэклиста'),
    ]:
        ws.append([label, rep['summary'][key]])

    ws_v = wb.create_sheet('Волонтёры')
    ws_v.append(['ФИО', 'Telegram', 'Телефон', 'Часов', 'Мероприятий', 'Заявок', 'Конверсия %', 'Churn', 'Статус'])
    for card in rep['cards']:
        u = card['user']
        stats = card['stats']
        ws_v.append([
            u.full_name, u.telegram_username or '—', u.phone or '—',
            stats['scoped_hours'] if rep['scope']['scoped'] else stats['total_hours'],
            stats['scoped_events'] if rep['scope']['scoped'] else stats['total_events'],
            card['applications_summary']['total'], card['applications_summary']['conversion_pct'],
            round(u.churn_score or 0, 2), u.get_status_display(),
        ])

    ws_p = wb.create_sheet('Участия')
    ws_p.append(['Волонтёр', 'Мероприятие', 'Дата', 'Статус', 'Часы'])
    for card in rep['cards']:
        u = card['user']
        for p in card['participations']:
            ws_p.append([u.full_name, p['event'], p['day'].isoformat() if p['day'] else '—', p['status'], p['hours']])

    return _xlsx_response(wb, 'volunteers_report.xlsx')


@manager_required
def report_organization_pdf(request, org_id):
    """PDF-отчёт по организации (reports_template.md «Отчёт по организации»):
    профиль, контакты, статистика, все мероприятия подряд, история взаимодействия."""
    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    rep = organization_report_service.organization_report(org_id, date_from, date_to)
    if rep['categories_breakdown']:
        rep['categories_chart'] = charts_service.bar_chart(
            [c[0] for c in rep['categories_breakdown']], [c[1] for c in rep['categories_breakdown']],
            title='Мероприятия по категориям',
        )
    rep['generated_at'] = timezone.now()
    builder = report_builders_service.build_organization_report(rep)
    return docx_response(builder, f'organization_{org_id}_report.docx')


@manager_required
def report_people_search(request):
    """Поиск человека для карточки выбора отчёта «по человеку» (по ФИО/username)."""
    from data_base import data_controller as dc
    query = request.GET.get('q', '').strip()
    users = dc.users_qs()
    if query:
        users = users.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
            | Q(telegram_username__icontains=query)
        )
    users = users.order_by('last_name', 'first_name')[:30]
    return JsonResponse({'users': [
        {'id': u.id, 'name': u.full_name, 'telegram': u.telegram_username or ''} for u in users
    ]})


@manager_required
def report_organizations_search(request):
    """Поиск организации для карточки выбора отчёта «по организации»."""
    from data_base import data_controller as dc
    query = request.GET.get('q', '').strip()
    orgs = sorted(dc.get_organizations(name_filter=query or None), key=lambda o: o.name)[:30]
    return JsonResponse({'organizations': [{'id': o.id, 'name': o.name} for o in orgs]})


@manager_required
def report_complex_pdf(request):
    """Комплексный отчёт за период (PDF-пакет, reports_template.md): часть 1 —
    сводная аналитика (переиспользует данные report_period_pdf/internal), часть 2 —
    все мероприятия периода подряд с таймлайнами, часть 3 — таблица работы с
    заявками за период, часть 4 — карточки волонтёров периода подряд по алфавиту."""
    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    compare_mode = request.GET.get('compare', 'adjacent')
    if compare_mode not in ('adjacent', 'year_ago'):
        compare_mode = 'adjacent'

    prev_from = prev_to = None
    if scope_mode == 'period':
        prev_from, prev_to = reports_service.previous_period_range(date_from, date_to, compare_mode)

    data = reports_service.period_report(date_from, date_to, prev_from, prev_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    staff = reports_service.staff_load(date_from, date_to, event_ids=event_ids)
    timing = reports_service.application_timing(date_from, date_to, event_ids=event_ids)
    post_timing = reports_service.post_publication_timing(date_from, date_to, event_ids=event_ids)
    weekly = reports_service.weekly_dynamics(date_from, date_to, event_ids=event_ids)

    events_scope = reports_service._events_in_scope(date_from, date_to, event_ids)
    events_reports = []
    for event in events_scope.order_by('shifts__day').distinct():
        rep = report_exports.event_report(event.id)
        timeline = event_timeline_service.event_timeline_data(event)
        rep['timeline_chart'] = charts_service.event_timeline_chart(
            timeline['milestones'], timeline['applications']
        )
        events_reports.append(rep)

    applications_rows = report_exports.applications_rows(date_from, date_to, event_ids)
    lags = [
        (row['assigned_at'] - row['created_at']).total_seconds() / 3600
        for row in applications_rows if row.get('assigned_at') and row.get('created_at')
    ]
    applications_summary = {
        'total': len(applications_rows),
        'approved': sum(1 for r in applications_rows if r['status'] == 'Одобрена'),
        'rejected': sum(1 for r in applications_rows if r['status'] == 'Отклонена/резерв'),
        'new': sum(1 for r in applications_rows if r['status'] == 'Новая'),
        'avg_lag_hours': round(sum(lags) / len(lags), 1) if lags else None,
    }

    volunteers = volunteers_report_service.volunteers_report(date_from, date_to, user_ids=None)

    context = {
        'scope_mode': scope_mode,
        'date_from': date_from,
        'date_to': date_to,
        'generated_at': timezone.now(),
        'report': data,
        'efficiency': efficiency,
        'staff': staff,
        'timing': timing,
        'post_timing': post_timing,
        'weekly': weekly,
        'events_reports': events_reports,
        'applications_rows': applications_rows,
        'applications_summary': applications_summary,
        'volunteers': volunteers,
    }
    builder = report_builders_service.build_complex_report(context)
    return docx_response(builder, 'complex_report.docx')


@manager_required
def dobro_page(request):
    """Страница «Добро.ру»: все ссылки Добро.ру таблицей — общие (DobroRuSharedLink) и
    уникальные (заданные прямо у мероприятия), их тип, к каким мероприятиям привязана
    ссылка (чипами сбоку) и статус простановки часов (выставлены/нет) по каждому меро.

    Мероприятия с типом учёта 'none' в таблицу не попадают (часы не ведём).

    Фильтр `?only_unlogged=1` оставляет только ссылки, по которым часы ещё НЕ полностью
    проставлены (есть хотя бы одно незакрытое меро)."""
    # Добро.ру переехало во вкладку ERP-хаба «Отчёты» (?view=dobro). Прямой заход на
    # /dobro/ редиректим туда, чтобы не держать вторую копию страницы.
    return redirect(reverse('report_period') + '?view=dobro')


@manager_required
def report_dobro_toggle(request, event_id):
    """AJAX-переключение «часы на Добро.ру проставлены» из таблицы Добро.ру внутри
    ERP-хаба (галочка в строке). Те же инварианты, что у event_dobro_toggle (только
    завершённые меро с ведением учёта), но ответ — JSON для обновления галочки без
    перезагрузки панели."""
    event = get_object_or_404(Event, pk=event_id)
    if request.method != 'POST':
        return JsonResponse({'error': 'method'}, status=405)
    if event.event_status != 'finished':
        return JsonResponse({'error': 'Статус доступен только после завершения мероприятия.'}, status=400)
    if event.dobro_ru_link_kind == 'none':
        return JsonResponse({'error': 'У мероприятия учёт часов на Добро.ру не ведётся.'}, status=400)
    event.dobro_ru_hours_logged = not event.dobro_ru_hours_logged
    event.dobro_ru_logged_by = request.user if event.dobro_ru_hours_logged else None
    event.save(update_fields=['dobro_ru_hours_logged', 'dobro_ru_logged_by'])
    return JsonResponse({'logged': event.dobro_ru_hours_logged})


@manager_required
def report_dobro_set_link(request, event_id):
    """AJAX: задать/изменить уникальную ссылку Добро.ру мероприятию прямо из таблицы
    Добро.ру (двойной клик по ячейке «нет ссылки» → модалка ввода URL). Ставит
    dobro_ru_link_kind='unique' и dobro_ru_link=<url>. Пустой URL — снимает ссылку
    (kind='none'). Общие (shared) ссылки отсюда не трогаем — их источник DobroRuSharedLink,
    менять её здесь было бы неожиданно (она общая на несколько меро)."""
    event = get_object_or_404(Event, pk=event_id)
    if request.method != 'POST':
        return JsonResponse({'error': 'method'}, status=405)
    if event.dobro_ru_link_kind == 'shared':
        return JsonResponse({'error': 'У мероприятия общая ссылка Добро.ру — измените её в справочнике общих ссылок.'}, status=400)
    url = (request.POST.get('url') or '').strip()
    if url:
        # Мягкая валидация: ждём http(s)-ссылку.
        validator = URLValidator()
        try:
            validator(url)
        except ValidationError:
            return JsonResponse({'error': 'Введите корректную ссылку (http/https).'}, status=400)
        event.dobro_ru_link = url
        event.dobro_ru_link_kind = 'unique'
    else:
        event.dobro_ru_link = None
        event.dobro_ru_link_kind = 'none'
        event.dobro_ru_hours_logged = False
    event.save(update_fields=['dobro_ru_link', 'dobro_ru_link_kind', 'dobro_ru_hours_logged'])
    return JsonResponse({'url': event.dobro_ru_link or '', 'kind': event.dobro_ru_link_kind})


def _dobro_rows(only_unlogged=False, event_ids=None, has_link=None):
    """Строки таблицы Добро.ру — ПО ОДНОМУ МЕРОПРИЯТИЮ охвата (не по ссылке): в таблице
    присутствует каждое меро из охвата, даже если у него нет ссылки Добро.ру (тогда в
    колонке «Ссылка» явно пишется «нет ссылки»). Раньше таблица была link-центричной и
    меро без учёта Добро.ру (kind='none') в неё вообще не попадали — из-за чего при
    выбранном периоде таблица выглядела пустой, хотя мероприятия в охвате были.

    Для каждого меро колонка «Ссылка» = его уникальный URL (kind='unique'), либо URL
    общей ссылки (kind='shared'), либо пусто (kind='none'). Чекбокс «часы проставлены»
    доступен только у завершённых меро с ведением учёта (kind != 'none').

    event_ids — охват (даты/статус/исключения). None → все меро (прямой заход).
    has_link — 'yes'|'no'|None (фильтр по наличию URL). only_unlogged — только меро с
    непроставленными часами."""
    from data_base import data_controller as dc
    events = dc.events_qs().select_related('dobro_ru_shared_link').order_by('-created_at')
    if event_ids is not None:
        events = events.filter(id__in=event_ids)

    KIND_DISPLAY = {'none': 'Нет учёта', 'unique': 'Уникальная', 'shared': 'Общая'}
    rows = []
    for event in events:
        if event.dobro_ru_link_kind == 'unique':
            url = event.dobro_ru_link or ''
        elif event.dobro_ru_link_kind == 'shared':
            url = event.dobro_ru_shared_link.url if event.dobro_ru_shared_link else ''
        else:
            url = ''
        tracks_hours = event.dobro_ru_link_kind != 'none'
        rows.append({
            'event': event,
            'title': event.title,
            'url': url,
            'kind': event.dobro_ru_link_kind,
            'kind_display': KIND_DISPLAY.get(event.dobro_ru_link_kind, event.dobro_ru_link_kind),
            'tracks_hours': tracks_hours,
            'logged': event.dobro_ru_hours_logged,
            # Чекбокс доступен только у завершённого меро с ведением учёта.
            'toggle_enabled': tracks_hours and event.event_status == 'finished',
        })

    if only_unlogged:
        # «Не проставленные» = ведём учёт и часы ещё не отмечены.
        rows = [r for r in rows if r['tracks_hours'] and not r['logged']]
    if has_link == 'yes':
        rows = [r for r in rows if r['url'].strip()]
    elif has_link == 'no':
        rows = [r for r in rows if not r['url'].strip()]

    # Для кнопки выгрузки — id завершённых меро с непроставленными часами (отчёт берёт
    # в охват только их).
    unlogged_event_ids = sorted(
        r['event'].id for r in rows
        if r['tracks_hours'] and not r['logged'] and r['event'].event_status == 'finished'
    )
    return rows, unlogged_event_ids


@manager_required
def report_dobro_export(request):
    """Excel-отчёт простановки часов на Добро.ру (reports_template.md §5):
    листы «По ссылке», «По человеку», «Сводка»."""
    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    show_logged = request.GET.get('show_logged') == '1'
    wb = report_exports.build_dobro_workbook(date_from, date_to, event_ids, show_logged)
    return _xlsx_response(wb, "dobro_ru_logging.xlsx")


@manager_required
def report_bundle(request):
    """Комплексный отчёт (reports_template.md §3): ZIP из внешнего DOCX, внутреннего DOCX
    и Excel-книги за охват."""
    import io
    import zipfile
    from django.http import HttpResponse

    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    compare_mode = request.GET.get('compare', 'adjacent')
    if compare_mode not in ('adjacent', 'year_ago'):
        compare_mode = 'adjacent'

    prev_from = prev_to = None
    if scope_mode == 'period':
        prev_from, prev_to = reports_service.previous_period_range(date_from, date_to, compare_mode)
    data = reports_service.period_report(date_from, date_to, prev_from, prev_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    timing = reports_service.application_timing(date_from, date_to, event_ids=event_ids)
    post_timing = reports_service.post_publication_timing(date_from, date_to, event_ids=event_ids)

    base_ctx = {
        'scope_mode': scope_mode, 'date_from': date_from, 'date_to': date_to,
        'compare_mode': compare_mode, 'generated_at': timezone.now(),
        'report': data, 'efficiency': efficiency, 'timing': timing, 'post_timing': post_timing,
    }
    external_docx = report_builders_service.build_period_report({
        **base_ctx, 'variant': 'external', 'is_internal': False,
    }).build_bytes()
    internal_docx = report_builders_service.build_period_report({
        **base_ctx, 'variant': 'internal', 'is_internal': True,
        'staff': reports_service.staff_load(date_from, date_to, event_ids=event_ids),
    }).build_bytes()

    wb = report_exports.build_period_workbook(date_from, date_to, event_ids, scope_mode, compare_mode)
    xlsx_buf = io.BytesIO()
    wb.save(xlsx_buf)

    scope_slug = f'{date_from}_{date_to}' if scope_mode == 'period' else 'events'

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'report_external_{scope_slug}.docx', external_docx)
        zf.writestr(f'report_internal_{scope_slug}.docx', internal_docx)
        zf.writestr(f'report_{scope_slug}.xlsx', xlsx_buf.getvalue())
    zip_buf.seek(0)

    response = HttpResponse(zip_buf.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="report_bundle_{scope_slug}.zip"'
    return response


@manager_required
def location_list(request):
    # Панель хаба настроек: по AJAX (X-Requested-With) отдаём только partial панели для
    # подгрузки в блок настроек; прямой заход на /locations/ редиректит в хаб на нужную
    # вкладку (страница-справочник больше не живёт отдельно, agent-workflow.md §4).
    locations = Location.objects.order_by('name')
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_locations.html', {'locations': locations})
    return redirect(reverse('settings') + '?tab=locations')


@manager_required
def location_create(request):
    form = LocationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Локация создана.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('settings') + '?tab=locations',
        )
    return modal_form_response(
        request, 'blog/location_form.html',
        {'form': form, 'title': 'Новая локация'},
    )


@manager_required
def location_edit(request, location_id):
    location = get_object_or_404(Location, pk=location_id)
    form = LocationForm(request.POST or None, instance=location)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Локация обновлена.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('settings') + '?tab=locations',
        )
    return modal_form_response(
        request, 'blog/location_form.html',
        {'form': form, 'title': f'Редактировать: {location.name}', 'submit_label': 'Сохранить'},
    )


@manager_required
def organizations_list(request):
    # Панель хаба настроек (см. location_list): AJAX → partial, прямой заход → редирект.
    organizations = Organization.objects.order_by('name')
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_organizations.html', {'organizations': organizations})
    return redirect(reverse('settings') + '?tab=organizations')


@manager_required
def organization_create(request):
    form = OrganizationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        organization = form.save()
        messages.success(request, 'Организация создана.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('organization_detail', args=[organization.id]),
        )
    return modal_form_response(
        request, 'blog/organization_form.html',
        {'form': form, 'title': 'Новая организация'},
    )


@manager_required
def organization_edit(request, org_id):
    organization = get_object_or_404(Organization, pk=org_id)
    form = OrganizationForm(request.POST or None, instance=organization)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Организация обновлена.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('organization_detail', args=[organization.id]),
        )
    return modal_form_response(
        request, 'blog/organization_form.html',
        {'form': form, 'title': f'Редактировать: {organization.name}', 'submit_label': 'Сохранить'},
    )


@manager_required
def organization_detail(request, org_id):
    organization = get_object_or_404(Organization, pk=org_id)
    events = organization.events.prefetch_related('shifts').order_by('-created_at')
    organizers = Organizer.objects.filter(organization_links__organization=organization).distinct()
    return render(request, 'blog/organization_detail.html', {
        'organization': organization, 'events': events, 'organizers': organizers,
    })


# ---------------------------------------------------------------------------
# Пользователи, организаторы, настройки
# ---------------------------------------------------------------------------

@manager_required
def users_picker_data(request):
    """Компактный JSON-список всех пользователей (id + ФИО + флаги активных ролей) для
    единого JS-виджета выбора в remote-режиме (data-select-remote="users", base.html) — единственный источник
    данных для ЛЮБОГО количества таких виджетов на любой странице: страница требований
    (список исключений на каждое требование) и страница настроек (назначение/снятие
    ролей) раньше рендерили серверный <select> со ВСЕМИ пользователями на КАЖДЫЙ такой
    блок — при нескольких тысячах пользователей и нескольких блоков на странице это
    давало десятки тысяч <option> в HTML и заметно тормозило загрузку. Теперь список
    запрашивается один раз (JS кэширует на странице) и рендерится на клиенте.

    Флаги is_team_lead/is_manager нужны, чтобы виджет мог на клиенте отфильтровать
    список под конкретный блок (напр. «снять роль ТЛ» — показывать только действующих
    ТЛ), не делая для этого отдельный серверный запрос/queryset на каждый блок.

    Ранжирование и лимит (легаси-база копит десятки тысяч пользователей, отдавать всех
    сразу незачем):
      - `?order=recent` (по умолчанию) — сначала те, кто был на меро недавно
        (last_event_at DESC, никогда не участвовавшие — в конце);
      - `?order=name` — по алфавиту (фамилия, имя);
      - без `?all=1` отдаём только первые `users_picker_limit` (константа) записей
        ВЫБРАННОГО порядка + флаг `truncated`, чтобы клиент показал «показать всех»;
      - `?all=1` — весь список (менеджер нажал «показать всех»)."""
    from data_base import data_controller as dc

    tl_ids = set(TeamLeader.objects.filter(revoked_at__isnull=True).values_list('user_id', flat=True))
    mgr_ids = set(Manager.objects.filter(revoked_at__isnull=True).values_list('user_id', flat=True))

    order = 'name' if request.GET.get('order') == 'name' else 'recent'
    qs = dc.users_ranked_qs(order)

    show_all = request.GET.get('all') == '1'
    limit = int(dc.get_const('users_picker_limit', default=200))
    total = qs.count()
    if not show_all:
        qs = qs[:limit]

    users = qs.values('id', 'first_name', 'last_name')
    data = [
        {
            'id': u['id'],
            'label': f"{u['last_name'] or ''} {u['first_name'] or ''}".strip() or f"#{u['id']}",
            'is_team_lead': u['id'] in tl_ids,
            'is_manager': u['id'] in mgr_ids,
        }
        for u in users
    ]
    return JsonResponse({
        'users': data,
        'truncated': (not show_all) and total > limit,
        'total': total,
        'shown': len(data),
    })


@manager_required
def user_list(request):
    from django.db.models import OuterRef, Subquery

    # Дата последней заявки (любой статус) и дата последнего мероприятия, на котором
    # человек реально был и получил часы (Participation.status='attended', hours>0) —
    # считаем через Subquery по каждому пользователю страницы, а не в Python-цикле,
    # чтобы не плодить N+1 при infinite-scroll подгрузке новых порций.
    last_application_sq = (
        Application.objects.filter(user=OuterRef('pk'))
        .order_by('-submitted_at', '-created_at')
        .values('submitted_at')[:1]
    )
    last_event_sq = (
        Participation.objects.filter(user=OuterRef('pk'), status='attended', hours__gt=0)
        .order_by('-event_day__day')
        .values('event_day__day')[:1]
    )
    users = User.objects.order_by('-created_at').annotate(
        last_application_at=Subquery(last_application_sq),
        last_attended_day=Subquery(last_event_sq),
    )
    paginator = Paginator(users, 40)
    page = paginator.get_page(request.GET.get('page'))

    manager_ids = set(Manager.objects.filter(revoked_at__isnull=True).values_list('user_id', flat=True))
    team_leader_ids = set(TeamLeader.objects.filter(revoked_at__isnull=True).values_list('user_id', flat=True))

    context = {
        'page_obj': page,
        'manager_ids': manager_ids,
        'team_leader_ids': team_leader_ids,
    }
    if is_ajax(request):
        return render(request, 'blog/partials/_user_list_rows.html', context)
    return render(request, 'blog/user_list.html', context)


@manager_required
def organizer_list(request):
    # Панель хаба настроек (см. location_list): AJAX → partial, прямой заход → редирект.
    organizers = Organizer.objects.order_by('last_name', 'first_name')
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_organizers.html', {'organizers': organizers})
    return redirect(reverse('settings') + '?tab=organizers')


@manager_required
def organizer_create(request):
    form = OrganizerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        organizer = form.save()
        messages.success(request, 'Организатор создан.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('organizer_detail', args=[organizer.id]),
        )
    return modal_form_response(
        request, 'blog/organizer_form.html',
        {'form': form, 'title': 'Новый организатор'},
    )


@manager_required
def organizer_edit(request, organizer_id):
    organizer = get_object_or_404(Organizer, pk=organizer_id)
    form = OrganizerForm(request.POST or None, instance=organizer)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Организатор обновлён.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('organizer_detail', args=[organizer.id]),
        )
    return modal_form_response(
        request, 'blog/organizer_form.html',
        {'form': form, 'title': f'Редактировать: {organizer.first_name} {organizer.last_name}', 'submit_label': 'Сохранить'},
    )


@manager_required
def organizer_detail(request, organizer_id):
    organizer = get_object_or_404(Organizer, pk=organizer_id)
    organizations = Organization.objects.filter(organizer_links__organizer=organizer)
    events = organizer.managed_events.prefetch_related('shifts').order_by('-created_at')
    interactions = organizer.interaction_log.select_related('author').order_by('-created_at')
    return render(request, 'blog/organizer_detail.html', {
        'organizer': organizer, 'organizations': organizations,
        'events': events, 'interactions': interactions,
    })


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
    # полностраничная версия того же окна капчи (captcha_page.html), а не const_form.html
    # (который был захардкожен под редактирование константы и рендерил не ту форму).
    return render(request, 'blog/captcha_page.html', context)


# Секции назначения/снятия ролей в настройках: (action, role kind, глагол для сообщений).
ROLE_ACTIONS = {
    'assign_team_lead': ('team_lead', 'assign'),
    'revoke_team_lead': ('team_lead', 'revoke'),
    'assign_manager': ('manager', 'assign'),
    'revoke_manager': ('manager', 'revoke'),
}
ROLE_LABELS = {'team_lead': 'тим-лидера', 'manager': 'менеджера'}

# Хаб настроек: единый порядок и метаданные вкладок-кнопок в хедере страницы настроек.
# Каждая вкладка открывает свою панель в блоке контента ниже (AJAX-подгрузка partial'а).
# 'url' — имя вьюхи, отдающей partial по X-Requested-With:
#   - справочники (локации/организаторы/организации/требования) — их же list-вьюхи,
#     которые раньше были отдельными страницами (теперь редиректят на settings, а по
#     AJAX отдают только partial панели);
#   - константы/сезоны/тим-лидеры/менеджеры — сама settings_view (?tab=…).
# Панели ролей разделены на две вкладки (тим-лидеры / менеджеры), внутри каждой —
# по секции назначения и снятия (partials/_settings_team_leaders|managers.html).
SETTINGS_TABS = [
    {'key': 'locations', 'icon': '📍', 'title': 'Локации', 'desc': 'Площадки проведения мероприятий', 'url': 'location_list'},
    {'key': 'organizers', 'icon': '🤝', 'title': 'Организаторы', 'desc': 'Контактные лица организаций', 'url': 'organizer_list'},
    {'key': 'organizations', 'icon': '🏢', 'title': 'Организации', 'desc': 'Партнёры и заказчики мероприятий', 'url': 'organizations_list'},
    {'key': 'requirements', 'icon': '✅', 'title': 'Требования', 'desc': 'Условия допуска волонтёров', 'url': 'requirement_list'},
    {'key': 'constants', 'icon': '🔢', 'title': 'Константы', 'desc': 'Пороги и коэффициенты системы', 'url': 'settings'},
    {'key': 'seasons', 'icon': '🗓️', 'title': 'Сезоны', 'desc': 'Периоды учёта и закрытие сезона', 'url': 'settings'},
    {'key': 'team_leaders', 'icon': '⭐', 'title': 'Тим-лидеры', 'desc': 'Назначение и снятие роли ТЛ', 'url': 'settings'},
    {'key': 'managers', 'icon': '🛡️', 'title': 'Менеджеры', 'desc': 'Назначение и снятие роли менеджера', 'url': 'settings'},
    {'key': 'pgas_template', 'icon': '📄', 'title': 'Шаблон справки ПГАС', 'desc': 'Текст и плейсхолдеры справки ВЦ', 'url': 'settings'},
]

# Панели настроек, которые обслуживает сама settings_view (не отдельные list-вьюхи).
SETTINGS_NATIVE_PANELS = {
    'constants': 'blog/partials/_settings_constants.html',
    'seasons': 'blog/partials/_settings_seasons.html',
    'team_leaders': 'blog/partials/_settings_team_leaders.html',
    'managers': 'blog/partials/_settings_managers.html',
    'pgas_template': 'blog/partials/_settings_pgas_template.html',
}
SETTINGS_DEFAULT_TAB = 'locations'


def _settings_tabs_context(active_tab):
    """Готовит список вкладок с готовыми URL для шелла настроек. URL справочников ведут
    на их list-вьюхи с ?tab= (для истории/копируемой ссылки шелл всё равно перепишет URL
    на /settings/?tab=…), URL нативных панелей — на settings с ?tab=&partial=1."""
    tabs = []
    for tab in SETTINGS_TABS:
        if tab['url'] == 'settings':
            url = reverse('settings') + f"?tab={tab['key']}&partial=1"
        else:
            url = reverse(tab['url'])
        tabs.append({**tab, 'url': url})
    active_url = next((t['url'] for t in tabs if t['key'] == active_tab), tabs[0]['url'])
    return tabs, active_url


@manager_required
def const_edit(request, const_id):
    """Редактирование константы в модалке (как редактирование мероприятия), с
    двухшаговым подтверждением: капча появляется только когда значение реально
    меняется, и генерируется заново при каждой попытке (нельзя переиспользовать
    подсмотренный пример)."""
    const = get_object_or_404(Const, pk=const_id)

    if request.method == 'POST':
        # ВАЖНО: сохранить исходное значение до form.is_valid() — ModelForm._post_clean()
        # присваивает cleaned_data в instance (construct_instance) уже во время валидации,
        # так что после is_valid() const.value уже равен НОВОМУ значению.
        original_value = const.value
        form = ConstForm(request.POST, instance=const)
        value_changed = form.is_valid() and form.cleaned_data['value'] != original_value

        if not value_changed:
            if form.is_valid():
                # Значение не менялось — сохранять и требовать капчу незачем.
                messages.info(request, 'Значение не изменилось.')
                return modal_form_response(request, None, None, success_redirect=reverse('settings'))
        else:
            session_key = f'captcha_const_{const.id}'
            if 'captcha_answer' in request.POST:
                captcha_ok = _check_captcha(request, session_key, request.POST.get('captcha_answer'))
                if captcha_ok:
                    form.save()
                    messages.success(request, f'Константа «{const.name}» обновлена.')
                    return modal_form_response(request, None, None, success_redirect=reverse('settings'))
                messages.error(request, 'Неверный ответ капчи.')
            # Значение меняется — показываем то же значение формы + новую капчу.
            return modal_form_response(
                request, 'blog/const_form.html',
                {
                    'form': form, 'const': const,
                    'show_captcha': True,
                    'captcha_question': _new_captcha(request, session_key),
                },
                partial_template='blog/partials/_const_form_body.html',
            )

    return modal_form_response(
        request, 'blog/const_form.html',
        {'form': ConstForm(instance=const), 'const': const, 'show_captcha': False},
        partial_template='blog/partials/_const_form_body.html',
    )


def _settings_redirect(tab):
    """Редирект после POST-действия настроек — обратно на нужную вкладку хаба
    (/settings/?tab=…), чтобы пользователь остался в том же разделе, а не был выброшен
    на дефолтную вкладку."""
    return redirect(reverse('settings') + f'?tab={tab}')


def _build_role_sections(request):
    """Секции назначения/снятия ролей для панелей «тим-лидеры» и «менеджеры»: на каждую
    роль — форма-пикер, свежая капча и число доступных пользователей. Вынесено, чтобы
    строить только когда реально рендерим панель ролей (а не на каждый заход в настройки)."""
    role_sections = {}
    for action, (kind, verb) in ROLE_ACTIONS.items():
        session_key = f'captcha_{action}'
        queryset = (
            roles_service.users_without_role(kind) if verb == 'assign'
            else roles_service.users_with_role(kind)
        )
        role_sections[action] = {
            # prefix обязателен: без него все 4 формы на странице рендерят <select id="id_users">
            # с одинаковым id, и JS chip-виджет находит только первый по document.getElementById.
            'form': RoleUsersForm(queryset=queryset, prefix=action),
            'captcha_question': _new_captcha(request, session_key),
            'users_count': queryset.count(),
        }
    return role_sections


@manager_required
def settings_view(request):
    """Хаб настроек. GET без ?partial=1 отдаёт шелл (хедер-кнопки + пустой блок панели,
    который JS сразу подгружает AJAX'ом). GET с ?partial=1&tab=… отдаёт partial нативной
    панели (константы/сезоны/тим-лидеры/менеджеры). POST обрабатывает действия этих
    панелей (добавить/закрыть сезон, назначить/снять роль) и редиректит на свою вкладку."""
    # --- POST-действия панелей ---
    if request.method == 'POST' and request.POST.get('action') == 'add_season':
        season_form = SeasonForm(request.POST)
        if season_form.is_valid():
            season_form.save()
            messages.success(request, 'Сезон добавлен.')
            return _settings_redirect('seasons')
        # Невалидная форма — покажем панель сезонов с ошибками (partial).
        return render(request, 'blog/partials/_settings_seasons.html', {
            'seasons': Season.objects.order_by('-start_season'),
            'season_form': season_form,
        })

    if request.method == 'POST' and request.POST.get('action') == 'close_season':
        from blog.services.stats import close_season
        season = get_object_or_404(Season, pk=request.POST.get('season_id'))
        next_season = close_season(season)
        msg = 'Сезон закрыт: churn зафиксирован в истории, сезонные счётчики обнулены.'
        if next_season:
            msg += ' Создан новый бессрочный сезон — задайте дату его окончания.'
        messages.success(request, msg)
        return _settings_redirect('seasons')

    if request.method == 'POST' and request.POST.get('action') == 'save_pgas_template':
        from blog.services.pgas_certificate import (
            EVENTS_BLOCK_START, EVENTS_BLOCK_END, get_template,
        )
        upload = request.FILES.get('docx_file')
        if not upload or not upload.name.lower().endswith('.docx'):
            messages.error(request, 'Загрузите файл шаблона в формате .docx.')
            return _settings_redirect('pgas_template')
        data = upload.read()
        # Проверяем, что в шаблоне есть оба маркера блока мероприятий — иначе
        # перечисление меро не развернётся. Читаем текст docx через python-docx.
        try:
            import io as _io
            from docx import Document
            doc_text = '\n'.join(p.text for p in Document(_io.BytesIO(data)).paragraphs)
        except Exception:
            messages.error(request, 'Не удалось прочитать .docx — файл повреждён или не Word.')
            return _settings_redirect('pgas_template')
        if EVENTS_BLOCK_START not in doc_text or EVENTS_BLOCK_END not in doc_text:
            messages.error(request, f'В шаблоне должны быть строки «{EVENTS_BLOCK_START}» и '
                                    f'«{EVENTS_BLOCK_END}» вокруг блока мероприятий.')
            return _settings_redirect('pgas_template')

        template = get_template()
        template.docx_file = data
        template.filename = upload.name
        template.updated_by = request.user
        template.save(update_fields=['docx_file', 'filename', 'updated_by', 'updated_at'])
        logger.info('Шаблон справки ПГАС обновлён (.docx): by=%s', actor(request.user))
        messages.success(request, 'Шаблон справки ПГАС загружен.')
        return _settings_redirect('pgas_template')

    if request.method == 'POST' and request.POST.get('action') in ROLE_ACTIONS:
        action = request.POST.get('action')
        kind, verb = ROLE_ACTIONS[action]
        session_key = f'captcha_{action}'
        # Роль ТЛ — на вкладке «тим-лидеры», роль менеджера — на «менеджеры».
        role_tab = 'team_leaders' if kind == 'team_lead' else 'managers'

        queryset = (
            roles_service.users_without_role(kind) if verb == 'assign'
            else roles_service.users_with_role(kind)
        )
        role_form = RoleUsersForm(request.POST, queryset=queryset, prefix=action)
        captcha_ok = _check_captcha(request, session_key, request.POST.get('captcha_answer'))

        if not captcha_ok:
            messages.error(request, 'Неверный ответ капчи. Действие отклонено.')
        elif role_form.is_valid():
            users = list(role_form.cleaned_data['users'])
            if verb == 'assign':
                affected = roles_service.assign_role(kind, users, assigned_by=request.user)
                verb_text = 'назначены'
            else:
                affected = roles_service.revoke_role(kind, users, revoked_by=request.user)
                verb_text = 'сняты с роли'
            role_word = ROLE_LABELS[kind]
            if affected:
                names = ', '.join(u.full_name for u in affected)
                messages.success(request, f'{role_word.capitalize()} {verb_text}: {names} ({len(affected)}).')
            else:
                messages.info(request, 'Выбранные пользователи уже были в этом статусе — изменений нет.')
            return _settings_redirect(role_tab)
        else:
            messages.error(request, 'Выберите хотя бы одного пользователя.')
        return _settings_redirect(role_tab)

    # --- GET: partial панели или шелл ---
    tab = request.GET.get('tab') or SETTINGS_DEFAULT_TAB
    wants_partial = request.GET.get('partial') == '1' or is_ajax(request)

    if wants_partial and tab in SETTINGS_NATIVE_PANELS:
        template = SETTINGS_NATIVE_PANELS[tab]
        context = {}
        if tab == 'constants':
            context['consts'] = Const.objects.order_by('name')
        elif tab == 'seasons':
            context['seasons'] = Season.objects.order_by('-start_season')
            context['season_form'] = SeasonForm()
        elif tab in ('team_leaders', 'managers'):
            context['role_sections'] = _build_role_sections(request)
        elif tab == 'pgas_template':
            from blog.services.pgas_certificate import get_template
            context['pgas_template'] = get_template()
        return render(request, template, context)

    # Шелл хаба: активная вкладка из ?tab= (или дефолт), если такой нет — дефолт.
    if tab not in {t['key'] for t in SETTINGS_TABS}:
        tab = SETTINGS_DEFAULT_TAB
    tabs, active_url = _settings_tabs_context(tab)
    return render(request, 'blog/settings.html', {
        'tabs': tabs,
        'active_tab': tab,
        'active_url': active_url,
    })


# ---------------------------------------------------------------------------
# Требования к волонтёрам (db.md правило 6): справочник + белый список исключений
# «кто НЕ соответствует». По умолчанию все волонтёры соответствуют всем требованиям.
# ---------------------------------------------------------------------------

@manager_required
def requirement_list(request):
    """Список требований: описание + компактный список тех, кто не соответствует
    (не грузим весь список волонтёров на экран — только тех, кто в исключениях, плюс
    маленькая форма добавления с поиском по select)."""
    requirements = EventRequirement.objects.order_by('title')
    sections = []
    for req in requirements:
        exceptions = req.user_exceptions.select_related('user').order_by('-created_at')
        sections.append({
            'requirement': req,
            'exceptions': exceptions,
            'exception_form': RequirementExceptionForm(requirement=req),
        })

    # Панель хаба настроек (см. location_list): AJAX → partial, прямой заход → редирект.
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_requirements.html', {
            'sections': sections,
            'requirement_form': RequirementForm(),
        })
    return redirect(reverse('settings') + '?tab=requirements')


@manager_required
def requirement_create(request):
    form = RequirementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Требование добавлено.')
        return modal_form_response(request, None, None, success_redirect=reverse('settings') + '?tab=requirements')
    return modal_form_response(
        request, 'blog/requirement_form.html',
        {'form': form, 'title': 'Новое требование', 'submit_label': 'Добавить'},
    )


@manager_required
def requirement_edit(request, requirement_id):
    requirement = get_object_or_404(EventRequirement, pk=requirement_id)
    form = RequirementEditForm(request.POST or None, instance=requirement)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Требование обновлено.')
        return modal_form_response(request, None, None, success_redirect=reverse('settings') + '?tab=requirements')
    return modal_form_response(
        request, 'blog/requirement_form.html',
        {'form': form, 'title': f'Редактировать: {requirement.title}', 'submit_label': 'Сохранить'},
    )


@manager_required
def requirement_delete(request, requirement_id):
    requirement = get_object_or_404(EventRequirement, pk=requirement_id)
    if request.method == 'POST':
        requirement.delete()
        messages.success(request, f'Требование «{requirement.title}» удалено.')
    return redirect('requirement_list')


@manager_required
def requirement_exception_add(request, requirement_id):
    """Отметить волонтёра как НЕ соответствующего требованию (белый список исключений,
    db.md правило 6) — освобождает тим-лидеров от повторной обработки его заявок:
    при подаче на меро с этим требованием заявка сразу уйдёт в резерв."""
    requirement = get_object_or_404(EventRequirement, pk=requirement_id)
    if request.method == 'POST':
        form = RequirementExceptionForm(request.POST, requirement=requirement)
        if form.is_valid():
            form.save()
            messages.success(request, f'{form.instance.user.full_name}: отмечен(а) как не соответствующий(ая) требованию «{requirement.title}».')
        else:
            messages.error(request, 'Не удалось добавить — выберите волонтёра из списка.')
    return redirect('requirement_list')


@manager_required
def requirement_exception_remove(request, exception_id):
    exception = get_object_or_404(UserRequirementException.objects.select_related('user', 'requirement'), pk=exception_id)
    if request.method == 'POST':
        name = exception.user.full_name
        title = exception.requirement.title
        exception.delete()
        messages.success(request, f'{name}: отметка о несоответствии требованию «{title}» снята.')
        return redirect('requirement_list')
    return redirect('requirement_list')


# ---------------------------------------------------------------------------
# Аналитика: приём событий с фронта (доступно всем аутентифицированным и
# гостям — пишем активность независимо от роли)
# ---------------------------------------------------------------------------

@require_POST
def analytics_ping(request):
    """Heartbeat активной вкладки — обновляет last_seen_at сессии и duration_ms
    текущего просмотра страницы. Вызывается раз в ~20с, пока вкладка видима."""
    session_key = request.session.session_key
    if not session_key:
        return JsonResponse({'ok': False}, status=204)
    page_view_id = request.POST.get('page_view_id')
    duration_ms = request.POST.get('duration_ms')

    now = timezone.now()
    WebSession.objects.filter(session_key=session_key).update(last_seen_at=now)
    if page_view_id and duration_ms and duration_ms.isdigit():
        WebPageView.objects.filter(pk=page_view_id, session__session_key=session_key).update(
            duration_ms=int(duration_ms)
        )
    return JsonResponse({'ok': True})


@require_POST
def analytics_leave(request):
    """Финальная длительность просмотра при уходе со страницы (sendBeacon)."""
    session_key = request.session.session_key
    page_view_id = request.POST.get('page_view_id')
    duration_ms = request.POST.get('duration_ms')
    if session_key and page_view_id and duration_ms and duration_ms.isdigit():
        WebPageView.objects.filter(pk=page_view_id, session__session_key=session_key).update(
            duration_ms=int(duration_ms)
        )
    return JsonResponse({'ok': True})


@require_POST
def analytics_click(request):
    """Клик по элементу с data-track (или кнопке/ссылке) — фиксируем для дашборда.
    Привязываем к текущей WebSession (по session_key), чтобы позже можно было
    восстановить последовательность действий гостя, у которого нет user_id."""
    action_key = (request.POST.get('action_key') or '').strip()[:150]
    if not action_key:
        return JsonResponse({'ok': False}, status=400)
    label = (request.POST.get('label') or '').strip()[:200]
    user = request.user if request.user.is_authenticated else None
    web_session = WebSession.objects.filter(session_key=request.session.session_key).first()
    ButtonClickEvent.objects.create(
        source='web',
        user=user,
        web_session=web_session,
        role_snapshot=roles_service.role_slug(user) if user else 'guest',
        action_key=action_key,
        label=label,
    )
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Аналитика: дашборд менеджера
# ---------------------------------------------------------------------------

def _analytics_period(request):
    """Читает date_from/date_to из query (ISO-даты) с фолбэком на последние 7 дней."""
    raw_from = request.GET.get('date_from')
    raw_to = request.GET.get('date_to')
    date_to = timezone.now()
    date_from = date_to - datetime.timedelta(days=7)
    if raw_from:
        try:
            date_from = datetime.datetime.fromisoformat(raw_from)
            if timezone.is_naive(date_from):
                date_from = timezone.make_aware(date_from)
        except ValueError:
            pass
    if raw_to:
        try:
            date_to = datetime.datetime.fromisoformat(raw_to)
            if timezone.is_naive(date_to):
                date_to = timezone.make_aware(date_to)
        except ValueError:
            pass
    return date_from, date_to


@tech_admin_required
def analytics_dashboard(request):
    return render(request, 'blog/analytics_dashboard.html', {})


@tech_admin_required
def analytics_online_data(request):
    source = request.GET.get('source', 'web')
    minutes = min(int(request.GET.get('minutes', 60)), 24 * 60)
    if source == 'bot':
        data = analytics_service.online_series_bot(minutes=minutes)
    else:
        data = analytics_service.online_series_web(minutes=minutes)
    return JsonResponse(data)


@tech_admin_required
def analytics_clicks_data(request):
    """`source` обязателен ('web' или 'bot') — веб и бот показываются двумя отдельными
    графиками (разный функционал, разные кнопки), общий график не имеет смысла."""
    date_from, date_to = _analytics_period(request)
    source = request.GET.get('source')
    if source not in ('web', 'bot'):
        return JsonResponse({'error': 'source must be web or bot'}, status=400)
    role = request.GET.get('role') or None
    data = analytics_service.click_distribution(source=source, role=role, date_from=date_from, date_to=date_to)
    return JsonResponse(data)


@tech_admin_required
def analytics_load_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.page_load_stats(date_from=date_from, date_to=date_to)
    return JsonResponse(data)


@tech_admin_required
def analytics_duration_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.page_duration_histogram(date_from=date_from, date_to=date_to)
    return JsonResponse(data)


@tech_admin_required
def analytics_top_pages_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.top_pages(date_from=date_from, date_to=date_to)
    return JsonResponse(data)


@tech_admin_required
def analytics_top_bot_commands_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.top_bot_commands(date_from=date_from, date_to=date_to)
    return JsonResponse(data)


@tech_admin_required
def analytics_downtimes_data(request):
    """Периоды простоя (для красных/жёлтых зон на графиках онлайна) за последние `hours`."""
    hours = min(int(request.GET.get('hours', 24)), 24 * 30)
    since = timezone.now() - datetime.timedelta(hours=hours)
    downtimes = SystemDowntime.objects.filter(ended_at__gte=since).order_by('started_at')
    return JsonResponse({
        'downtimes': [
            {
                'kind': d.kind,
                'started_at': d.started_at.isoformat(),
                'ended_at': d.ended_at.isoformat(),
                'comment': d.comment,
            }
            for d in downtimes
        ],
    })


@manager_required
@require_POST
def analytics_downtime_add(request):
    kind = request.POST.get('kind')
    if kind not in ('crash', 'planned'):
        return JsonResponse({'error': 'kind must be crash or planned'}, status=400)
    started_raw = request.POST.get('started_at')
    ended_raw = request.POST.get('ended_at')
    started = datetime.datetime.fromisoformat(started_raw) if started_raw else None
    ended = datetime.datetime.fromisoformat(ended_raw) if ended_raw else None
    if not started or not ended:
        return JsonResponse({'error': 'started_at/ended_at обязательны (ISO 8601)'}, status=400)
    if timezone.is_naive(started):
        started = timezone.make_aware(started)
    if timezone.is_naive(ended):
        ended = timezone.make_aware(ended)
    if ended <= started:
        return JsonResponse({'error': 'ended_at должен быть позже started_at'}, status=400)

    downtime = SystemDowntime.objects.create(
        kind=kind, started_at=started, ended_at=ended,
        comment=(request.POST.get('comment') or '').strip()[:255],
    )
    return JsonResponse({'ok': True, 'id': downtime.id})


@manager_required
@require_POST
def analytics_downtime_delete(request, downtime_id):
    SystemDowntime.objects.filter(pk=downtime_id).delete()
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Аналитика: просмотр и скачивание файловых логов (web.log/bot.log/db.log)
# ---------------------------------------------------------------------------

LOG_CHANNELS = {'web': 'web.log', 'bot': 'bot.log', 'db': 'db.log'}
LOG_TAIL_BATCH = 150


def _log_file_path(channel):
    filename = LOG_CHANNELS.get(channel)
    if not filename:
        raise Http404('Неизвестный канал логов.')
    path = Path(settings.LOG_DIR) / filename
    if not path.exists():
        raise Http404('Файл лога ещё не создан.')
    return path


@tech_admin_required
def analytics_log_download(request, channel):
    path = _log_file_path(channel)
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)


@tech_admin_required
def analytics_log_tail(request, channel):
    """Батч из LOG_TAIL_BATCH строк лога, читаемый с конца файла (для infinite scroll
    снизу вверх). `before_line` — курсор: номер строки (с конца, 0-based), с которой
    продолжать чтение более старых строк; без параметра отдаёт самый свежий батч."""
    path = _log_file_path(channel)
    with open(path, encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()

    total = len(all_lines)
    before_line = request.GET.get('before_line')
    end_offset = int(before_line) if before_line and before_line.isdigit() else 0
    start_index = max(total - end_offset - LOG_TAIL_BATCH, 0)
    end_index = total - end_offset
    batch = all_lines[start_index:end_index]

    return JsonResponse({
        'lines': [line.rstrip('\n') for line in batch],
        'next_cursor': total - start_index,
        'has_more': start_index > 0,
    })
