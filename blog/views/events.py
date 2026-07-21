"""Вьюхи домена «events». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


def _published_active_events():
    """Опубликованные и ещё не завершённые мероприятия (для гостевого списка и
    списка активных). Сортировка — ближайшие предстоящие/идущие сверху."""
    from data_base import data_controller as dc
    events = list(
        dc.events_qs().filter(published_at__isnull=False)
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
        dc.events_qs().select_related('location', 'organization'),
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
    from data_base import data_controller as dc
    events = list(
        dc.events_qs().select_related('location', 'organization', 'dobro_ru_shared_link')
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
        for staff in dc.event_staff_qs().filter(staff_role='team_lead').select_related('user'):
            tl_map[staff.event_id].append(staff.user.full_name)
        tl_by_event = tl_map

        for staff in dc.event_staff_qs().filter(staff_role='manager').select_related('user'):
            manager_by_event.setdefault(staff.event_id, staff.user.full_name)

        decisions = (
            dc.application_shift_decisions_qs()
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
            dc.events_qs().filter(dobro_ru_link_kind='shared', dobro_ru_shared_link__isnull=False)
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
    from data_base import data_controller as dc
    event = get_object_or_404(dc.events_qs().select_related('location', 'organization', 'organizer'), pk=event_id)
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
    categories = dc.event_categories_qs().filter(event_map__event=event).order_by('name')
    requirements = dc.requirements_qs().filter(event_map__event=event).order_by('title')
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
    my_active_application = dc.applications_qs().filter(
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
        for p in dc.participations_qs().filter(event_day__in=shifts).select_related('user'):
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
                dc.application_shift_decisions_qs().filter(shift=shift)
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
        dc.applications_qs().filter(user=request.user, event=event).exists()
        or dc.participations_qs().filter(user=request.user, event_day__event=event).exists()
    )
    if is_participant:
        volunteers_count = dc.participations_qs().filter(event_day__event=event).values('user').distinct().count()
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
    from data_base import data_controller as dc
    event = get_object_or_404(Event, pk=event_id)
    is_participant = (
        dc.applications_qs().filter(user=request.user, event=event).exists()
        or dc.participations_qs().filter(user=request.user, event_day__event=event).exists()
    )
    if not is_participant:
        raise PermissionDenied('Оставить оценку могут только участники мероприятия.')

    if dc.has_feedback(request.user.id, event.id):
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
        from data_base import data_controller as dc
        affected_user_ids = list(
            dc.participations_qs().filter(event_day__event=event)
            .values_list('user_id', flat=True).distinct()
        )
        title = event.title
        event.delete()
        if affected_user_ids:
            from blog.services.stats import recalc_user_aggregates
            for user in dc.users_qs().filter(id__in=affected_user_ids):
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
