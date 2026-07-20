"""Вьюхи домена «profiles». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


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
            messages.warning(request, 'Данные изменены — верификация для справки ПГАС снята, '
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

complete_profile = profile_edit

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

@login_required
def profile_detail(request, user_id):
    from data_base import data_controller as dc
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
        context['tl_event_count'] = dc.event_staff_qs().filter(
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
        shifts_by_id = {s.id: s for s in dc.event_shifts_qs().filter(id__in=all_shift_ids)}
        participations = dc.participations_qs().filter(
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
            dc.events_qs().filter(
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
        # Полная история изменений чарна (неявки, списания, сброс по сезону, блокировки).
        context['churn_log'] = target.churn_log.select_related('actor', 'event').order_by('-created_at')

    if can_see_comments:
        context['comments'] = target.received_comments.select_related('author', 'event').order_by('-created_at')
        if is_mgr:
            event_queryset = dc.events_qs()
        else:
            event_queryset = dc.events_qs().filter(
                staff__user=request.user, staff__staff_role='team_lead'
            ).exclude(event_status='finished')
        context['comment_form'] = UserCommentForm(event_queryset=event_queryset)

    # Владелец и менеджер/ТЛ на чужом профиле — ДВА разных шаблона (разные страницы),
    # а не ветвления в одном файле.
    template = 'blog/profile_self.html' if is_owner else 'blog/profile_manage.html'
    return render(request, template, context)

@login_required
def letter_view(request, user_id, event_id):
    """Благодарственное письмо — генерируется на лету, PDF не хранится
    (implementation-plan Этап 6.4). Страница свёрстана под печать/сохранение в PDF.

    Доступ: сам волонтёр, менеджер или ТЛ с расширенным доступом к профилю.
    """
    from data_base import data_controller as dc
    target = get_object_or_404(User, pk=user_id)
    event = get_object_or_404(Event.objects.select_related('letter', 'organization'), pk=event_id)

    if not has_extended_access_to_profile(request.user, target):
        raise PermissionDenied('Нет доступа к письмам этого волонтёра.')
    if not event.letter:
        raise PermissionDenied('У мероприятия не задан шаблон благодарственного письма.')

    attended = dc.participations_qs().filter(
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

    from data_base import data_controller as dc
    if is_mgr:
        event_queryset = dc.events_qs()
    else:
        event_queryset = dc.events_qs().filter(
            staff__user=request.user, staff__staff_role='team_lead'
        ).exclude(event_status='finished')

    redirect_url = reverse('profile_detail', args=[target.id])
    form = UserCommentForm(request.POST or None, event_queryset=event_queryset)
    if request.method == 'POST' and form.is_valid():
        comment = form.save(commit=False)
        comment.target_user = target
        comment.author = request.user
        comment.save()
        messages.success(request, 'Комментарий добавлен.')
        return modal_form_response(request, None, None, success_redirect=redirect_url)
    # GET (открытие модалки) или невалидный POST — отдаём форму (в модалку по AJAX).
    return modal_form_response(
        request, 'blog/profile_comment_form.html',
        {'form': form, 'target': target, 'title': f'Комментарий: {target.full_name}',
         'submit_label': 'Добавить комментарий'},
    )
