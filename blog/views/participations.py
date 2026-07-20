"""Вьюхи домена «participations». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


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
        apply_churn_no_show(participation.user, event=event, actor=request.user)
    elif new_status == 'attended' and old_status != 'attended':
        from blog.services.stats import apply_churn_activity_decay
        apply_churn_activity_decay(participation.user, event=event)

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
        from data_base import data_controller as dc
        old = dc.participations_qs().get(pk=participation.pk)
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
            apply_churn_no_show(participation.user, event=event, actor=request.user)
        elif participation.status == 'attended':
            from blog.services.stats import apply_churn_activity_decay
            apply_churn_activity_decay(participation.user, event=event)

        messages.success(request, 'Явка обновлена, статистика пересчитана.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('event_detail', args=[event.id]),
        )

    return modal_form_response(
        request, 'blog/participation_form.html',
        {'form': form, 'participation': participation, 'title': f'Явка: {participation.user.full_name}'},
    )
