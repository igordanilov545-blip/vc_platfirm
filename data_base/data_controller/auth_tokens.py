"""Доступ к данным: одноразовые токены Telegram-входа/верификации и веб-сессии.

`TelegramAuthToken` (вход по ссылке из бота) и `TelegramVerifyToken` (подтверждение
«это мой аккаунт») — инфраструктура аутентификации; сюда же инвалидация Django-`Session`
(разлогин при смене кредов/отклонении верификации). Единый слой доступа — чтобы
сервисы аутентификации не ходили в ORM напрямую.
"""
from typing import Optional

from django.contrib.sessions.models import Session
from django.utils import timezone

from blog.models import TelegramAuthToken, TelegramVerifyToken, User


# --- TelegramAuthToken (вход по ссылке из бота) ---
def invalidate_user_auth_tokens(user: User) -> None:
    TelegramAuthToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())


def create_auth_token(user: User, expires_at) -> TelegramAuthToken:
    return TelegramAuthToken.objects.create(user=user, expires_at=expires_at)


def get_auth_token(token: str) -> Optional[TelegramAuthToken]:
    return TelegramAuthToken.objects.filter(token=token).select_related('user').first()


# --- TelegramVerifyToken (подтверждение владения аккаунтом) ---
def invalidate_user_verify_tokens(user: User) -> None:
    TelegramVerifyToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())


def create_verify_token(user: User, expires_at) -> TelegramVerifyToken:
    return TelegramVerifyToken.objects.create(user=user, expires_at=expires_at)


def get_verify_token(token: str) -> Optional[TelegramVerifyToken]:
    return TelegramVerifyToken.objects.filter(token=token).select_related('user').first()


def get_user_by_telegram_id_excluding(telegram_id: str, exclude_user_id: int) -> Optional[User]:
    """Пользователь с данным реальным telegram_id, кроме указанного (для детекции
    коллизии при подтверждении владения)."""
    return User.objects.filter(telegram_id=str(telegram_id)).exclude(pk=exclude_user_id).first()


# --- Django-сессии (разлогин пользователя) ---
def logout_user_web_sessions(user: User) -> int:
    """Удаляет активные веб-сессии пользователя (смена веб-кредов, отклонение
    верификации, блокировка). Возвращает число удалённых."""
    removed = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.get_decoded().get('_auth_user_id') == str(user.id):
            session.delete()
            removed += 1
    return removed
