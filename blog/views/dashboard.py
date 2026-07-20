"""Вьюхи домена «dashboard». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403
# Гостевой дашборд показывает тот же список активных меро, что и публичная витрина —
# переиспользуем хелпер домена событий, а не дублируем выборку.
from .events import _published_active_events


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
