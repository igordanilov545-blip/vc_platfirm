from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from blog.services.roles import has_manager_access, is_tech_admin


def manager_required(view_func):
    """ACL проверяется на бэкенде (access-control.md п.4.1): активный менеджер, а
    также тех.админ (ANALYTICS_ADMIN_TG_IDS) — получает полный доступ ко всем
    менеджерским разделам, оставаясь при этом видимой ролью, кем был (roles.
    has_manager_access)."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not has_manager_access(request.user):
            raise PermissionDenied('Доступно только менеджерам.')
        return view_func(request, *args, **kwargs)
    return _wrapped


def tech_admin_required(view_func):
    """Доступ к техническому дашборду аналитики (/analytics/) — не бизнес-роль, а
    закрытый список telegram_id в .env (ANALYTICS_ADMIN_TG_IDS). Дашборд показывает
    техническую нагрузку системы и внутренние логи, не предназначен для менеджеров."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_tech_admin(request.user):
            raise PermissionDenied('Доступно только техническим администраторам.')
        return view_func(request, *args, **kwargs)
    return _wrapped
