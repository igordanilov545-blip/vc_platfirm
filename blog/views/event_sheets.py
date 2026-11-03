"""Тонкие вьюхи FaP. Парсинг/ACL/обмен — в сервисах, SQL — в data_controller."""
from ._common import *  # noqa: F401,F403
from blog.forms import EventSheetImportForm, GoogleSheetsConnectionForm, SheetTeamLeaderBindingForm
from blog.services import event_sheets as sheets


@manager_required
def event_sheet(request, group_id):
    group = get_object_or_404(dc.event_groups_qs(), pk=group_id)
    return render(request, 'blog/event_sheet.html', {
        'event_group': group,
        'sheet_link': dc.event_sheet_links_qs().filter(event_group=group).first(),
        'sheet_leaders': dc.sheet_leaders_qs().filter(direction__event_group=group).select_related('direction', 'position__event', 'user'),
        'zone_responsibles': dc.zone_responsibles_qs().filter(direction__event_group=group).select_related('direction', 'position__event'),
        'google_connection': dc.google_sheets_connection(),
    })


@manager_required
def event_sheet_link(request, group_id):
    group = get_object_or_404(dc.event_groups_qs(), pk=group_id)
    form = EventSheetImportForm(request.POST or None, request.FILES or None, assigned_by=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            sheets.apply_prepared_sheet(request.user, group, form.prepared_sheet)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            return modal_form_response(request, None, None, success_redirect=reverse('event_sheet', args=[group.pk]))
    return modal_form_response(request, 'blog/event_sheet_import.html', {'form': form, 'event_group': group, 'title': 'Связать таблицу'}, partial_template='blog/partials/_event_sheet_import.html')


@manager_required
@require_POST
def event_sheet_sync(request, group_id):
    group = get_object_or_404(dc.event_groups_qs(), pk=group_id)
    try:
        if request.POST.get('direction') == 'pull':
            sheets.pull_google(request.user, group)
            messages.success(request, 'Изменения получены из Google Таблицы.')
        elif request.POST.get('direction') == 'push':
            sheets.push_google(request.user, group)
            messages.success(request, 'План и оформление отправлены в Google Таблицу.')
        else:
            raise ValidationError('Выберите направление обмена.')
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect('event_sheet', group_id=group.pk)


@manager_required
def event_sheet_export(request, group_id):
    group = get_object_or_404(dc.event_groups_qs(), pk=group_id)
    try:
        content = sheets.export_workbook(request.user, group)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect('event_sheet', group_id=group.pk)
    response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="event-{group.pk}-shifts.xlsx"'
    response['Cache-Control'] = 'private, no-store'
    return response


@manager_required
def google_sheets_settings(request):
    from blog.services.google_sheets import save_credentials
    form = GoogleSheetsConnectionForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            save_credentials(request.user, form.cleaned_data['credentials'].read())
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Ключ Google сохранён. Выдайте показанному аккаунту доступ редактора к таблице.')
            return redirect('google_sheets_settings')
    return render(request, 'blog/google_sheets_settings.html', {'form': form, 'google_connection': dc.google_sheets_connection()})


@manager_required
def sheet_team_leader_bind(request, assignment_id):
    assignment = get_object_or_404(dc.sheet_leaders_qs().select_related('direction', 'position'), pk=assignment_id)
    form = SheetTeamLeaderBindingForm(request.POST or None, initial={'user': assignment.user_id})
    if request.method == 'POST' and form.is_valid():
        try:
            sheets.bind_team_leader(request.user, assignment.pk, form.cleaned_data['user'])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            return modal_form_response(request, None, None, success_redirect=reverse('event_sheet', args=[assignment.direction.event_group_id]))
    return modal_form_response(request, 'blog/event_sheet_bind.html', {'form': form, 'title': f'Тим-лидер: {assignment.display_name}'}, partial_template='blog/partials/_modal_form.html')
