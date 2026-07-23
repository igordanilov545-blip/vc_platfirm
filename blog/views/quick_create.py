"""Вьюхи домена «quick_create». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


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
def quick_create_perk(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    form = QuickPerkForm(request.POST)
    if form.is_valid():
        perk = form.save()
        return JsonResponse({'id': perk.id, 'label': perk.name})
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
