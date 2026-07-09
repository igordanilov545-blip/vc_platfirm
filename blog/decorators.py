from functools import wraps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from blog.services.roles import is_manager


def manager_required(view_func):
    """ACL проверяется на бэкенде (access-control.md п.4.1): только активный менеджер."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_manager(request.user):
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
        allowed_ids = settings.ANALYTICS_ADMIN_TG_IDS
        if str(request.user.telegram_id) not in allowed_ids:
            raise PermissionDenied('Доступно только техническим администраторам.')
        return view_func(request, *args, **kwargs)
    return _wrapped
