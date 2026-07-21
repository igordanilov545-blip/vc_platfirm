from django.contrib.auth.backends import BaseBackend

from data_base import data_controller as dc


class WebLoginBackend(BaseBackend):
    """Аутентификация по login/password для Web Platform (см. architecture.md 2.1)."""

    def authenticate(self, request, login=None, password=None, **kwargs):
        if not login or not password:
            return None
        user = dc.get_user_by_login(login)
        if user is None:
            return None
        if user.has_usable_password() and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        return dc.get_user_by_id(user_id)


class TelegramWebAppBackend(BaseBackend):
    """Вход в TG Mini App по проверенному Telegram `initData` (architecture.md §2.1) —
    без пароля. Сам `authenticate()` не вызывается напрямую (пользователь уже найден/создан
    в `views.webapp_auth` через `data_controller`); backend нужен только для `django.contrib.auth.login`,
    чтобы указать явный `backend=` и для последующего `get_user` по сессии."""

    def authenticate(self, request, **kwargs):
        return None

    def get_user(self, user_id):
        return dc.get_user_by_id(user_id)
