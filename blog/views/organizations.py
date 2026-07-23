"""Вьюхи домена «organizations». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


@manager_required
def location_list(request):
    # Панель хаба настроек: по AJAX (X-Requested-With) отдаём только partial панели для
    # подгрузки в блок настроек; прямой заход на /locations/ редиректит в хаб на нужную
    # вкладку (страница-справочник больше не живёт отдельно, agent-workflow.md §4).
    from data_base import data_controller as dc
    locations = dc.locations_qs().order_by('name')
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
    from data_base import data_controller as dc
    organizations = dc.organizations_qs().order_by('name')
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
        partial_template='blog/partials/_organization_form_body.html',
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
        partial_template='blog/partials/_organization_form_body.html',
    )

@manager_required
def organization_detail(request, org_id):
    organization = get_object_or_404(Organization, pk=org_id)
    from data_base import data_controller as dc
    events = organization.events.prefetch_related('shifts').order_by('-created_at')
    organizers = dc.organizers_qs().filter(organization_links__organization=organization).distinct()
    return render(request, 'blog/organization_detail.html', {
        'organization': organization, 'events': events, 'organizers': organizers,
    })

@manager_required
def organizer_list(request):
    # Панель хаба настроек (см. location_list): AJAX → partial, прямой заход → редирект.
    from data_base import data_controller as dc
    organizers = dc.organizers_qs().order_by('last_name', 'first_name')
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
        partial_template='blog/partials/_organizer_form_body.html',
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
        partial_template='blog/partials/_organizer_form_body.html',
    )

@manager_required
def organizer_detail(request, organizer_id):
    organizer = get_object_or_404(Organizer, pk=organizer_id)
    from data_base import data_controller as dc
    organizations = dc.organizations_qs().filter(organizer_links__organizer=organizer)
    events = organizer.managed_events.prefetch_related('shifts').order_by('-created_at')
    interactions = organizer.interaction_log.select_related('author').order_by('-created_at')
    return render(request, 'blog/organizer_detail.html', {
        'organizer': organizer, 'organizations': organizations,
        'events': events, 'interactions': interactions,
    })
