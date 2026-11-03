"""Вьюхи домена «applications». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


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
        from data_base import data_controller as dc
        target_event = dc.get_event_by_id(event_id)
        if target_event and not target_event.published_at:
            messages.error(request, 'Мероприятие ещё не опубликовано — подать заявку нельзя.')
            if is_ajax(request):
                return JsonResponse({'redirect': reverse('dashboard')})
            return redirect('dashboard')
        existing = dc.applications_qs().filter(
            user=request.user, event_id=event_id, status__in=['new', 'approved'],
        ).first()
        if existing:
            messages.info(request, 'Заявка на это мероприятие уже подана — вы можете отредактировать её.')
            edit_url = reverse('application_edit', args=[existing.id])
            if is_ajax(request):
                return JsonResponse({'redirect': edit_url})
            return redirect(edit_url)

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
        # Заявка — источник достижений «Первая заявка», «Активный отклик», «Скорость
        # отклика» (по post_published_at). Доначисляем в той же операции.
        from blog.services.achievements import recalc_user_achievements
        recalc_user_achievements(request.user)
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
    from data_base import data_controller as dc

    fixed_event_id = request.GET.get('event') or request.POST.get('event')
    fixed_event = dc.get_event_by_id(fixed_event_id) if fixed_event_id else None

    if request.method == 'POST':
        event = fixed_event or dc.get_event_by_id(request.POST.get('event'))
        if not event:
            return JsonResponse({'errors': {'event': ['Выберите мероприятие.']}}, status=400)

        user_ids = request.POST.getlist('users')
        if not user_ids:
            return JsonResponse({'errors': {'users': ['Выберите хотя бы одного волонтёра.']}}, status=400)

        targets = list(dc.users_qs().filter(id__in=user_ids))

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
    events = None if fixed_event else dc.events_qs().order_by('-created_at')
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
    """Смены мероприятия для чип-виджета выбора смен в форме заявки (JS дозапрашивает
    при смене выбранного мероприятия).

    Возвращаем ВСЕ смены, которые ещё НЕ начались (start_time > now) — и открытые, и
    закрытые по набору: на закрытую смену тоже можно подать заявку (она уйдёт сразу в
    резерв), поэтому её показываем, но помечаем `closed=True` (виджет красит серым).
    Прошедшие/уже начавшиеся смены не предлагаются. Это ровно тот же пул, что у
    ApplicationForm.selected_shifts — раньше эндпоинт ошибочно фильтровал только
    recruit_status='open', из-за чего меро с закрытым набором показывалось без смен и
    подать заявку в резерв было невозможно."""
    event = get_object_or_404(Event, pk=event_id)
    now = timezone.now()
    shifts = event.shifts.filter(start_time__gt=now).order_by('day')
    return JsonResponse({
        'shifts': [
            {
                'id': s.id,
                'label': f'{s.day.strftime("%d.%m.%Y")} {timezone.localtime(s.start_time).strftime("%H:%M")}–{timezone.localtime(s.end_time).strftime("%H:%M")}',
                'closed': s.recruit_status != 'open',
            }
            for s in shifts
        ],
    })

@login_required
def application_process(request, application_id):
    application = get_object_or_404(dc.applications_qs().select_related('event'), pk=application_id)
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
    application = get_object_or_404(dc.applications_qs().select_related('event'), pk=application_id)
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

    from data_base import data_controller as dc
    pending_decisions = list(
        dc.application_shift_decisions_qs().filter(shift=shift, status='new')
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
    from data_base import data_controller as dc
    qs = dc.applications_qs().filter(status='new').select_related('event')
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
    elif not has_manager_access(request.user):
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

def _missing_event_titles(rows):
    """Уникальные названия недостающих мероприятий (в порядке первого появления).
    В превью импорта обычно 1–2 разных меро на десятки строк, поэтому кнопку «создать
    меро» показываем ОДИН раз на уникальное название (отдельным блоком внизу), а не в
    каждой строке — иначе получаем 25 одинаковых кнопок."""
    seen = {}
    for row in rows:
        if row.get('event_missing'):
            title = row.get('event_title') or ''
            seen.setdefault(title, True)
    return list(seen.keys())

def _import_preview_context(rows, *, errors, fixed_event):
    """Единый контекст экрана превью импорта (одинаков во всех точках входа)."""
    return {
        'rows': _rows_missing_last(rows),
        'errors': errors,
        'fixed_event': fixed_event,
        'has_missing_events': any(row.get('event_missing') for row in rows),
        'missing_event_titles': _missing_event_titles(rows),
    }

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
    from data_base import data_controller as dc
    fixed_event_id = request.GET.get('event') or request.POST.get('event')
    fixed_event = dc.get_event_by_id(fixed_event_id) if fixed_event_id else None

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
        return render(request, 'blog/import_preview.html',
                      _import_preview_context(result['rows'], errors=result['errors'], fixed_event=fixed_event))

    # Подтверждение "всё равно добавить" после экрана расхождений — строки уже в
    # сессии из предыдущего шага, просто показываем обычное превью.
    if request.method == 'POST' and request.POST.get('confirm_mismatch') == 'yes':
        rows = request.session.get('import_rows', [])
        return render(request, 'blog/import_preview.html',
                      _import_preview_context(rows, errors=[], fixed_event=fixed_event))

    # Возврат на превью без нового файла (напр. после создания мероприятия из
    # модалки, открытой прямо с этого экрана) — строки уже в сессии, пересчитываем
    # event_missing по актуальному состоянию БД и показываем то же превью снова.
    if request.method == 'GET' and request.session.get('import_rows'):
        rows = import_service.refresh_missing_events(request.session['import_rows'])
        request.session['import_rows'] = rows
        return render(request, 'blog/import_preview.html',
                      _import_preview_context(rows, errors=[], fixed_event=fixed_event))

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

@manager_required
def pending_applications(request):
    from data_base import data_controller as dc
    applications = dc.applications_qs().filter(status='new').select_related('event', 'user').order_by('created_at')
    return render(request, 'blog/pending_applications.html', {
        'applications': applications,
        'pending_count': applications.count(),
    })
