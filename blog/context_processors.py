from django.conf import settings

from blog.services.roles import is_manager, is_team_leader, role_label


def role_flags(request):
    user = getattr(request, 'user', None)
    authenticated = bool(user and user.is_authenticated)
    is_tech_admin = authenticated and str(getattr(user, 'telegram_id', '')) in settings.ANALYTICS_ADMIN_TG_IDS
    return {
        'is_manager': is_manager(user) if authenticated else False,
        'is_team_leader': is_team_leader(user) if authenticated else False,
        'role_label': role_label(user) if authenticated else None,
        'is_tech_admin': is_tech_admin,
        'analytics_page_view_id': getattr(request, 'analytics_page_view_id', None),
    }
