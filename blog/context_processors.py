from blog.services.roles import is_manager, is_team_leader, is_tech_admin, role_label


def role_flags(request):
    user = getattr(request, 'user', None)
    authenticated = bool(user and user.is_authenticated)
    return {
        'is_manager': is_manager(user) if authenticated else False,
        'is_team_leader': is_team_leader(user) if authenticated else False,
        'role_label': role_label(user) if authenticated else None,
        'is_tech_admin': is_tech_admin(user) if authenticated else False,
        'analytics_page_view_id': getattr(request, 'analytics_page_view_id', None),
        # Пример меро для компаньон-тура: тур ведёт «за руку» на карточку конкретного
        # мероприятия, поэтому нужен id реального меро (первое опубликованное). Если меро
        # нет — тур пропускает шаги про карточку. Лёгкий запрос (values_list+first).
        'companion_sample_event_id': _companion_sample_event_id() if authenticated else None,
    }


def _companion_sample_event_id():
    """id первого опубликованного мероприятия — точка перехода компаньон-тура на карточку
    меро. None, если публикаций ещё нет (шаги про карточку тогда пропускаются)."""
    from data_base import data_controller as dc
    return (
        dc.events_qs().filter(published_at__isnull=False)
        .order_by('-created_at').values_list('id', flat=True).first()
    )
