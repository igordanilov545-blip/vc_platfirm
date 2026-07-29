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
            # Заполненность профиля — источник достижения «Профиль заполнен на 100%».
            from blog.services.achievements import recalc_user_achievements
            recalc_user_achievements(request.user)
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
    is_mgr = has_manager_access(request.user)
    # Расширенный + внутренний профиль: владелец, менеджер (и тех.админ), либо ТЛ
    # в контексте своего мероприятия (access-control.md, правило 5).
    has_extended = has_extended_access_to_profile(request.user, target)
    # Комментарии волонтёр не видит никогда, даже о себе (access-control.md, правило 6).
    can_see_comments = is_mgr or (is_team_leader(request.user) and has_extended and not is_owner)

    from blog.services.experience import build_experience
    experience = build_experience(target)

    # Достижения вынесены на отдельную страницу (profile_achievements) — тут только
    # счётчик полученных для кнопки-перехода «🏅 Достижения».
    achievement_earned_count = dc.user_achievements_qs().filter(user=target).count()

    context = {
        'target': target,
        'is_owner': is_owner,
        'is_manager': is_mgr,
        'has_extended_access': has_extended,
        'can_see_comments': can_see_comments,
        'experience': experience,
        'achievement_earned_count': achievement_earned_count,
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
        letters_pool = list(_letter_events_for(target))
        context['letters_pool'] = letters_pool
        # «Скачать все» доступно, только если есть хотя бы одно письмо с PDF-фоном
        # (у legacy-HTML-шаблонов нет готового файла — их печатают по одному).
        context['has_downloadable_letters'] = any(e.letter.has_background for e in letters_pool)

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
def profile_achievements(request, user_id):
    """Отдельная страница «Мои достижения» (achievements.md). Доступ — как к профилю:
    владелец видит свои, менеджер/ТЛ с расширенным доступом — чужие (access-control.md
    правило 5). Каждая карточка — значок с рамкой по уровню сложности (tier); series
    раскрывается по ступеням (build_profile_achievements)."""
    target = get_object_or_404(User, pk=user_id)
    is_owner = request.user.id == target.id
    if not (is_owner or has_extended_access_to_profile(request.user, target)):
        raise PermissionDenied('Нет доступа к достижениям этого пользователя.')

    from blog.services.achievements import build_profile_achievements
    groups = build_profile_achievements(target, viewer_is_owner=is_owner)
    earned_count = sum(1 for grp in groups for c in grp['items'] if c['earned'])
    total_count = sum(len(grp['items']) for grp in groups)

    return render(request, 'blog/profile_achievements.html', {
        'target': target,
        'is_owner': is_owner,
        'achievement_groups': groups,
        'earned_count': earned_count,
        'total_count': total_count,
    })

@login_required
def profile_stats(request, user_id):
    """Страница «Моя статистика» — карточки за периоды (месяц/сезон ПГАС) под шаринг
    (achievements.md §«Периодическая статистика»). Доступ — как к профилю."""
    target = get_object_or_404(User, pk=user_id)
    is_owner = request.user.id == target.id
    if not (is_owner or has_extended_access_to_profile(request.user, target)):
        raise PermissionDenied('Нет доступа к статистике этого пользователя.')

    from blog.services.stats_cards import build_period_stats
    data = build_period_stats(target)
    return render(request, 'blog/profile_stats.html', {
        'target': target,
        'is_owner': is_owner,
        'months': data['months'],
        'season': data['season'],
    })

@login_required
@xframe_options_sameorigin
def letter_view(request, user_id, event_id):
    """Благодарственное письмо — генерируется на лету, PDF не хранится
    (implementation-plan Этап 6.4). Страница свёрстана под печать/сохранение в PDF.

    @xframe_options_sameorigin: письмо показывается в модалке через <iframe> (см.
    letter_modal.js). Глобальный XFrameOptionsMiddleware ставит X-Frame-Options: DENY
    → браузер отказывался рендерить PDF в iframe («не удаётся установить соединение»).
    Декоратор разрешает встраивание ТОЛЬКО с нашего же origin (SAMEORIGIN) — внешние
    сайты письмо по-прежнему не зафреймят.

    Доступ: сам волонтёр, менеджер или ТЛ с расширенным доступом к профилю.
    """
    from data_base import data_controller as dc
    target = get_object_or_404(User, pk=user_id)
    event = get_object_or_404(dc.events_qs().select_related('letter', 'organization'), pk=event_id)

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
    days = [p.event_day.day for p in attended]
    first_day, last_day = min(days), max(days)

    # Основной путь — конструктор поверх PDF: если у шаблона загружен фон, штампуем
    # реальные значения PyMuPDF и отдаём готовый PDF (letter-templates.md). Иначе —
    # legacy HTML-шаблон letter.html (обратная совместимость со старыми шаблонами).
    if event.letter.has_background:
        from blog.services import letter_render
        download = request.GET.get('download') == '1'
        try:
            ctx = letter_render.letter_context(
                target, event, hours=hours, first_day=first_day, last_day=last_day
            )
            # Скачивание — PDF (для печати/архива). Просмотр — PNG-«картинка»: письмо
            # показывается в модалке как фото в ленте (просто изображение по центру),
            # без браузерного PDF-вьюера с панелью печати.
            if download:
                body = letter_render.render_letter_pdf(event.letter, ctx)
            else:
                body = letter_render.render_letter_png(event.letter, ctx)
        except Exception:
            # Прод-диагностика: полный трейс в лог vc.web (иначе при DEBUG=False видна
            # только пустая страница 500). Сузит причину сбоя рендера на сервере.
            logger.exception(
                'Ошибка рендера письма: user=%s event=%s letter=%s',
                target.id, event.id, event.letter_id,
            )
            # ?debug=1 (только менеджеру) — вернуть текст трейса прямо в ответ, чтобы
            # диагностировать прод без доступа к логам сервера. Временная мера.
            if request.GET.get('debug') == '1' and has_manager_access(request.user):
                import traceback
                return HttpResponse(
                    'LETTER RENDER ERROR\n\n' + traceback.format_exc(),
                    content_type='text/plain; charset=utf-8', status=500,
                )
            raise
        if download:
            resp = HttpResponse(body, content_type='application/pdf')
            resp['Content-Disposition'] = _content_disposition('attachment', _letter_filename(target, event))
        else:
            resp = HttpResponse(body, content_type='image/png')
            resp['Content-Disposition'] = 'inline'
        return resp

    return render(request, 'blog/letter.html', {
        'target': target,
        'event': event,
        'letter': event.letter,
        'hours': hours,
        'last_day': last_day,
    })


def _content_disposition(disposition: str, filename: str) -> str:
    """Заголовок Content-Disposition с кириллическим именем файла. Тип (attachment/
    inline) и ASCII-fallback остаются как есть, а UTF-8 имя кодируется по RFC 5987
    (`filename*=UTF-8''…`). Иначе Django MIME-кодирует ВЕСЬ заголовок в `=?utf-8?b?…?=`,
    и часть браузеров не распознаёт тип/имя (см. тест — attachment «пропадал»)."""
    from urllib.parse import quote
    ascii_name = filename.encode('ascii', 'ignore').decode('ascii') or 'letter.pdf'
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _letter_filename(target, event) -> str:
    """Человекочитаемое имя файла письма: «Письмо_<ФИО>_<Меро>.pdf», без опасных
    символов файловой системы."""
    import re
    raw = f'Письмо_{target.full_name}_{event.title}'
    safe = re.sub(r'[\\/:*?"<>|]+', '_', raw).strip('_')[:120]
    return f'{safe}.pdf'


def _letter_events_for(target):
    """Мероприятия, по которым волонтёру положено благодарственное письмо: явка
    (attended) + у меро задан шаблон. Общий источник для пула на странице и для
    «скачать все» (не дублируем запрос)."""
    return (
        dc.events_qs().filter(
            shifts__participations__user=target,
            shifts__participations__status='attended',
            letter__isnull=False,
        )
        .distinct()
        .select_related('letter', 'organization')
        .order_by('-created_at')
    )


@login_required
def letters_download_all(request, user_id):
    """ZIP со всеми благодарственными письмами волонтёра (по одному PDF на меро).
    Только письма с PDF-фоном (у legacy-HTML-шаблонов нет готового файла — их
    открывают/печатают по одному). Доступ — как у letter_view."""
    import io
    import zipfile

    target = get_object_or_404(User, pk=user_id)
    if not has_extended_access_to_profile(request.user, target):
        raise PermissionDenied('Нет доступа к письмам этого волонтёра.')

    from blog.services import letter_render
    events = _letter_events_for(target)

    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for event in events:
            if not event.letter.has_background:
                continue  # legacy-HTML шаблон — готового PDF нет
            attended = dc.participations_qs().filter(
                user=target, event_day__event=event, status='attended'
            ).select_related('event_day')
            hours = sum(p.hours for p in attended)
            days = [p.event_day.day for p in attended]
            if not days:
                continue
            ctx = letter_render.letter_context(
                target, event, hours=hours, first_day=min(days), last_day=max(days)
            )
            pdf = letter_render.render_letter_pdf(event.letter, ctx)
            zf.writestr(_letter_filename(target, event), pdf)
            count += 1

    if count == 0:
        raise Http404('Нет писем для скачивания (нужен PDF-шаблон и явка).')

    buf.seek(0)
    import re
    safe_name = re.sub(r'[\\/:*?"<>|]+', '_', target.full_name).strip('_')[:80]
    resp = HttpResponse(buf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = _content_disposition('attachment', f'Письма_{safe_name}.zip')
    return resp

@tech_admin_required
def profile_admin_edit(request, user_id):
    """Редактирование чужого профиля техническим администратором (ANALYTICS_ADMIN_TG_IDS).
    Не бизнес-роль менеджера/ТЛ — отдельный закрытый доступ (см. decorators.tech_admin_required).
    Форма — та же, что и в личном кабинете (ProfileForm), просто применяется к чужому
    instance."""
    target = get_object_or_404(User, pk=user_id)
    form = ProfileForm(request.POST or None, instance=target)
    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Профиль отредактирован тех.админом: user=%s by=%s', target.id, actor(request.user))
        messages.success(request, f'Профиль «{target.full_name}» обновлён.')
        return redirect('profile_detail', user_id=target.id)

    return render(request, 'blog/profile_edit.html', {
        'form': form,
        'target': target,
        'next': '',
        'missing_fields': account_missing_fields(target),
    })


@tech_admin_required
def profile_admin_delete(request, user_id):
    """Полное удаление чужого профиля техническим администратором — с двухфакторным
    подтверждением (капча x+y, как event_delete). Каскадом удаляются заявки, участия,
    комментарии и т.п. (FK on_delete=CASCADE/SET_NULL на User, см. models.py). В отличие
    от блокировки менеджером (user_blacklist) — необратимо стирает профиль, а не просто
    закрывает доступ."""
    target = get_object_or_404(User, pk=user_id)
    if target.id == request.user.id:
        raise PermissionDenied('Нельзя удалить собственный профиль.')
    session_key = f'captcha_profile_admin_delete_{target.id}'

    if request.method == 'POST':
        reason = (request.POST.get('reason') or '').strip()
        if not reason:
            messages.error(request, 'Укажите причину удаления.')
            return redirect('profile_detail', user_id=target.id)
        if not _check_captcha(request, session_key, request.POST.get('captcha_answer')):
            messages.error(request, 'Неверный ответ на пример — удаление отменено. Попробуйте ещё раз.')
            return modal_form_response(request, None, None, success_redirect=reverse('profile_detail', args=[target.id]))

        full_name = target.full_name
        logger.info(
            'Профиль удалён тех.админом: user=%s name=%r by=%s reason=%r',
            target.id, full_name, actor(request.user), reason,
        )
        target.delete()
        messages.success(request, f'Профиль «{full_name}» удалён.')
        return modal_form_response(request, None, None, success_redirect=reverse('user_list'))

    return render_captcha_modal(
        request,
        session_key=session_key,
        action_url=reverse('profile_admin_delete', args=[target.id]),
        confirm_text=f'Удалить профиль «{target.full_name}» безвозвратно? Все его заявки, '
                      f'участия и комментарии будут удалены вместе с ним.',
        submit_label='Удалить профиль',
        title=f'Удаление профиля: {target.full_name}',
        reason_field=True,
        reason_label='Причина удаления (обязательно)',
    )


@login_required
def profile_comment_add(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    is_mgr = has_manager_access(request.user)
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
