import datetime
import random

from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from blog.decorators import manager_required
from blog.forms import (
    ApplicationForm, CaptchaForm, ConstForm, EventDayForm, EventFeedbackForm, EventForm,
    EventStaffAssignForm, ExcelImportForm, LoginForm, OrganizationForm, OrganizerForm,
    ParticipationForm, SeasonForm, UserCommentForm,
)
from blog.models import (
    Application, Const, Event, EventFeedback, EventStaff, Manager, Organization,
    Organizer, Participation, Season, TeamLeader, User,
)
from blog.services import import_applications as import_service
from blog.services import reports as reports_service
from blog.services.applications import process_application
from blog.services.roles import (
    can_process_applications, has_extended_access_to_profile, is_manager, is_team_leader, role_label,
)
from blog.services.stats import recalc_user_aggregates


# ---------------------------------------------------------------------------
# Аутентификация
# ---------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request,
            login=form.cleaned_data['login'],
            password=form.cleaned_data['password'],
        )
        if user is not None:
            auth_login(request, user)
            return redirect('dashboard')
        messages.error(request, 'Неверный логин или пароль.')

    return render(request, 'blog/login.html', {'form': form})


def logout_view(request):
    auth_logout(request)
    return redirect('login')


# ---------------------------------------------------------------------------
# Дашборд
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    user = request.user
    context = {
        'role_label': role_label(user),
        'is_manager': is_manager(user),
        'is_team_leader': is_team_leader(user),
    }
    if is_manager(user):
        context['new_applications_count'] = Application.objects.filter(status='new').count()
        context['open_events_count'] = Event.objects.filter(recruit_status='open').count()
    return render(request, 'blog/dashboard.html', context)


# ---------------------------------------------------------------------------
# Мероприятия (Этап 3)
# ---------------------------------------------------------------------------

@login_required
def event_list(request):
    events = Event.objects.select_related('location', 'organization').order_by('-created_at')
    paginator = Paginator(events, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'blog/event_list.html', {'page_obj': page})


@login_required
def event_detail(request, event_id):
    event = get_object_or_404(Event.objects.select_related('location', 'organization', 'organizer'), pk=event_id)
    days = event.days.select_related('location').order_by('day')
    team_leads = event.staff.filter(staff_role='team_lead').select_related('user')
    can_manage_applications = can_process_applications(request.user, event.id)

    context = {
        'event': event,
        'days': days,
        'team_leads': team_leads,
        'can_manage_applications': can_manage_applications,
        'is_manager': is_manager(request.user),
    }

    if is_manager(request.user):
        context['staff_assign_form'] = EventStaffAssignForm()

    if can_manage_applications:
        applications = event.applications.select_related('user').order_by('-created_at')
        needed = sum(d.volunteer_needed for d in days)
        approved = event.applications.filter(status='approved').count()
        context.update({
            'applications': applications,
            'needed': needed,
            'approved_count': approved,
            'remaining': max(needed - approved, 0),
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
        })

    return render(request, 'blog/event_detail.html', context)


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
    form = EventForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        event = form.save()
        messages.success(request, 'Мероприятие создано.')
        return redirect('event_detail', event_id=event.id)
    return render(request, 'blog/event_form.html', {'form': form, 'title': 'Новое мероприятие'})


@manager_required
def event_edit(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    form = EventForm(request.POST or None, instance=event)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Мероприятие обновлено.')
        return redirect('event_detail', event_id=event.id)
    return render(request, 'blog/event_form.html', {'form': form, 'title': f'Редактировать: {event.title}'})


@manager_required
def event_day_add(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    form = EventDayForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        day = form.save(commit=False)
        day.event = event
        day.save()
        messages.success(request, 'День мероприятия добавлен.')
        return redirect('event_detail', event_id=event.id)
    return render(request, 'blog/event_day_form.html', {'form': form, 'event': event})


@manager_required
def event_assign_staff(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if request.method == 'POST':
        form = EventStaffAssignForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            role = form.cleaned_data['staff_role']
            EventStaff.objects.get_or_create(event=event, user=user, staff_role=role)
            if role == 'team_lead' and not TeamLeader.objects.filter(user=user, revoked_at__isnull=True).exists():
                TeamLeader.objects.create(user=user, assigned_by=request.user)
            messages.success(request, 'Сотрудник назначен на мероприятие.')
        else:
            messages.error(request, 'Не удалось назначить сотрудника — проверьте выбранные значения.')
    return redirect('event_detail', event_id=event.id)


# ---------------------------------------------------------------------------
# Явка (Этап 5)
# ---------------------------------------------------------------------------

@login_required
def participation_edit(request, participation_id):
    participation = get_object_or_404(
        Participation.objects.select_related('event_day__event', 'user'), pk=participation_id
    )
    event = participation.event_day.event
    if not can_process_applications(request.user, event.id):
        raise PermissionDenied('Нет доступа к явке этого мероприятия.')

    form = ParticipationForm(request.POST or None, instance=participation)
    if request.method == 'POST' and form.is_valid():
        old_status = Participation.objects.get(pk=participation.pk).status
        participation = form.save()
        recalc_user_aggregates(participation.user)

        if participation.status == 'absent_unexcused' and old_status != 'absent_unexcused':
            from blog.services.stats import apply_churn_no_show
            apply_churn_no_show(participation.user)
        elif participation.status == 'attended':
            from blog.services.stats import apply_churn_activity_decay
            apply_churn_activity_decay(participation.user)

        messages.success(request, 'Явка обновлена, статистика пересчитана.')
        return redirect('event_detail', event_id=event.id)

    return render(request, 'blog/participation_form.html', {'form': form, 'participation': participation})


# ---------------------------------------------------------------------------
# Заявки (Этап 4)
# ---------------------------------------------------------------------------

@login_required
def application_create(request):
    form = ApplicationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        application = form.save(commit=False)
        application.submitted_at = timezone.now()
        if request.user.is_authenticated:
            application.user = request.user
        application.save()
        messages.success(request, 'Заявка отправлена.')
        return redirect('dashboard')
    return render(request, 'blog/application_form.html', {'form': form})


@login_required
def application_process(request, application_id):
    application = get_object_or_404(Application.objects.select_related('event'), pk=application_id)
    if not can_process_applications(request.user, application.event_id):
        raise PermissionDenied('Нет прав на обработку заявок этого мероприятия.')

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


@manager_required
def import_preview(request):
    form = ExcelImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        result = import_service.parse_excel(request.FILES['excel_file'])
        request.session['import_rows'] = [
            {**row, 'submitted_at': row['submitted_at'].isoformat() if row.get('submitted_at') else None}
            for row in result['rows']
        ]
        return render(request, 'blog/import_preview.html', {
            'rows': result['rows'], 'errors': result['errors'],
        })
    return render(request, 'blog/import_form.html', {'form': form})


@manager_required
def import_commit(request):
    if request.method != 'POST':
        return redirect('import_preview')

    rows = request.session.pop('import_rows', [])
    for row in rows:
        if row.get('submitted_at'):
            row['submitted_at'] = datetime.datetime.fromisoformat(row['submitted_at'])
        row['create_new_user'] = not row.get('matched_user_id')

    created = import_service.commit_import(rows)
    messages.success(request, f'Импортировано заявок: {created}.')
    return redirect('event_list')


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

    context = {
        'target': target,
        'is_owner': is_owner,
        'is_manager': is_mgr,
        'has_extended_access': has_extended,
        'can_see_comments': can_see_comments,
        'past_participations': target.participations.filter(status='attended').select_related('event_day__event').order_by('-event_day__day')[:50],
    }

    if has_extended:
        context['applications'] = target.applications.select_related('event').order_by('-created_at')

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


@manager_required
def pending_applications(request):
    applications = Application.objects.filter(status='new').select_related('event', 'user').order_by('created_at')
    paginator = Paginator(applications, 30)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'blog/pending_applications.html', {'page_obj': page})


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

@manager_required
def report_period(request):
    today = timezone.now().date()
    period = request.GET.get('period', 'month')

    if period == 'week':
        date_from = today - datetime.timedelta(days=7)
    elif period == 'season':
        date_from = today - datetime.timedelta(days=120)
    else:
        date_from = today - datetime.timedelta(days=30)
    date_to = today

    span = (date_to - date_from).days
    prev_to = date_from - datetime.timedelta(days=1)
    prev_from = prev_to - datetime.timedelta(days=span)

    data = reports_service.period_report(date_from, date_to, prev_from, prev_to)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to)
    staff = reports_service.staff_load(date_from, date_to)

    context = {
        'period': period,
        'date_from': date_from,
        'date_to': date_to,
        'report': data,
        'efficiency': efficiency,
        'staff': staff,
    }
    return render(request, 'blog/report_period.html', context)


@manager_required
def organizations_list(request):
    organizations = Organization.objects.order_by('name')
    return render(request, 'blog/organizations_list.html', {'organizations': organizations})


@manager_required
def organization_create(request):
    form = OrganizationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        organization = form.save()
        messages.success(request, 'Организация создана.')
        return redirect('organization_detail', org_id=organization.id)
    return render(request, 'blog/organization_form.html', {'form': form, 'title': 'Новая организация'})


@manager_required
def organization_detail(request, org_id):
    organization = get_object_or_404(Organization, pk=org_id)
    events = organization.events.order_by('-created_at')
    organizers = Organizer.objects.filter(organization_links__organization=organization).distinct()
    return render(request, 'blog/organization_detail.html', {
        'organization': organization, 'events': events, 'organizers': organizers,
    })


# ---------------------------------------------------------------------------
# Пользователи, организаторы, настройки
# ---------------------------------------------------------------------------

@manager_required
def user_list(request):
    users = User.objects.order_by('-created_at')
    paginator = Paginator(users, 30)
    page = paginator.get_page(request.GET.get('page'))

    manager_ids = set(Manager.objects.filter(revoked_at__isnull=True).values_list('user_id', flat=True))
    team_leader_ids = set(TeamLeader.objects.filter(revoked_at__isnull=True).values_list('user_id', flat=True))

    return render(request, 'blog/user_list.html', {
        'page_obj': page,
        'manager_ids': manager_ids,
        'team_leader_ids': team_leader_ids,
    })


@manager_required
def organizer_list(request):
    organizers = Organizer.objects.order_by('last_name', 'first_name')
    return render(request, 'blog/organizer_list.html', {'organizers': organizers})


@manager_required
def organizer_create(request):
    form = OrganizerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        organizer = form.save()
        messages.success(request, 'Организатор создан.')
        return redirect('organizer_detail', organizer_id=organizer.id)
    return render(request, 'blog/organizer_form.html', {'form': form, 'title': 'Новый организатор'})


@manager_required
def organizer_detail(request, organizer_id):
    organizer = get_object_or_404(Organizer, pk=organizer_id)
    organizations = Organization.objects.filter(organizer_links__organizer=organizer)
    events = organizer.managed_events.order_by('-created_at')
    interactions = organizer.interaction_log.select_related('author').order_by('-created_at')
    return render(request, 'blog/organizer_detail.html', {
        'organizer': organizer, 'organizations': organizations,
        'events': events, 'interactions': interactions,
    })


def _new_captcha(request):
    x = random.randint(-10, 10)
    y = random.randint(-10, 10)
    request.session['captcha_answer'] = x + y
    return f'{x} + ({y})' if y < 0 else f'{x} + {y}'


@manager_required
def settings_view(request):
    consts = Const.objects.order_by('name')
    seasons = Season.objects.order_by('-start_season')

    if request.method == 'POST' and request.POST.get('action') == 'update_const':
        const = get_object_or_404(Const, pk=request.POST.get('const_id'))
        const_form = ConstForm(request.POST, instance=const)
        captcha_form = CaptchaForm(request.POST)

        expected = request.session.get('captcha_answer')
        captcha_ok = (
            captcha_form.is_valid()
            and expected is not None
            and captcha_form.cleaned_data['answer'] == expected
        )

        if const_form.is_valid() and captcha_ok:
            const_form.save()
            request.session.pop('captcha_answer', None)
            messages.success(request, f'Константа «{const.name}» обновлена.')
            return redirect('settings')
        elif not captcha_ok:
            messages.error(request, 'Неверный ответ капчи. Изменение константы отклонено.')
        else:
            messages.error(request, 'Некорректное значение константы.')

    if request.method == 'POST' and request.POST.get('action') == 'add_season':
        season_form = SeasonForm(request.POST)
        if season_form.is_valid():
            season_form.save()
            messages.success(request, 'Сезон добавлен.')
            return redirect('settings')
    else:
        season_form = SeasonForm()

    captcha_question = _new_captcha(request)

    return render(request, 'blog/settings.html', {
        'consts': consts,
        'seasons': seasons,
        'season_form': season_form,
        'captcha_question': captcha_question,
    })
