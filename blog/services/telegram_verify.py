"""Подтверждение владения Telegram из личного кабинета («Подтвердить телеграм»).

Поток (см. дерево бота и модель `TelegramVerifyToken`):

1. Пользователь в ЛК жмёт «Подтвердить телеграм» → `issue_verify_token` создаёт
   одноразовый токен (TTL 5 мин), веб-вью строит deep-link `?start=verify_<token>`.
2. Deep-link открывает бота от имени реального Telegram-аккаунта человека. Бот
   показывает «<ФИО> сейчас пытается подтвердить телеграм — да/нет».
3. «Да» → `confirm_verify_token`: реальный `telegram_id` привязывается к аккаунту
   (если раньше был служебный `web:*`), ставится `telegram_verified=True`.
4. «Нет» → `reject_verify_token`: токен гасится, а активные веб-сессии запросившего
   пользователя завершаются (разлогин) — на случай, если вход инициировал не владелец.

Доступ к данным (токены, сессии, поиск по telegram_id) — через `data_controller`.
"""
import datetime

from django.utils import timezone

from data_base import data_controller as dc
from blog.models import TelegramVerifyToken, User  # только для аннотаций типов
from blog.logging_utils import get_web_logger

logger = get_web_logger(__name__)

# Время жизни одноразового токена подтверждения.
VERIFY_TOKEN_TTL = datetime.timedelta(minutes=5)


def issue_verify_token(user: User) -> TelegramVerifyToken:
    """Создаёт одноразовый токен подтверждения для пользователя (вызывается из веб-ЛК).
    Прежние неиспользованные токены того же пользователя гасим — живёт только последний."""
    dc.invalidate_user_verify_tokens(user)
    return dc.create_verify_token(user, expires_at=timezone.now() + VERIFY_TOKEN_TTL)


def get_pending_token(token: str):
    """Возвращает валидный (не использованный, не просроченный) токен или None."""
    obj = dc.get_verify_token(token)
    if obj is None or not obj.is_valid():
        return None
    return obj


def confirm_verify_token(token: str, telegram_id, telegram_username: str = None):
    """Подтверждение «да, это мой аккаунт» (нажал в боте владелец реального Telegram).

    Помечает токен использованным, ставит `telegram_verified=True` и привязывает
    реальный `telegram_id` к аккаунту, если раньше стоял служебный `web:*`. Возвращает
    (user|None, код_ошибки|None). Коды: `invalid` — токен неизвестен/просрочен/использован;
    `conflict` — этот реальный telegram_id уже принадлежит ДРУГОМУ аккаунту (тогда
    подтверждаем факт владения, но id не перепривязываем — коллизию разрулит менеджер)."""
    obj = get_pending_token(token)
    if obj is None:
        return None, 'invalid'

    user = obj.user
    telegram_id = str(telegram_id)
    error = None

    updates = ['telegram_verified']
    user.telegram_verified = True

    # Привязываем реальный telegram_id, если сейчас служебный (web:*) и он свободен.
    current_is_synthetic = (user.telegram_id or '').startswith('web:')
    if user.telegram_id != telegram_id:
        conflict = dc.get_user_by_telegram_id_excluding(telegram_id, exclude_user_id=user.pk)
        if conflict is not None:
            # Реальный id уже за другим аккаунтом — не перепривязываем, только помечаем
            # факт владения. Разведение дублей — вручную менеджером (db.md правило 3).
            error = 'conflict'
            logger.warning(
                'Подтверждение Telegram: коллизия telegram_id=%s — уже у user=%s, '
                'подтверждает user=%s; id не перепривязан.',
                telegram_id, conflict.pk, user.pk,
            )
        elif current_is_synthetic:
            user.telegram_id = telegram_id
            updates.append('telegram_id')

    if telegram_username and not (user.telegram_username or '').strip():
        user.telegram_username = telegram_username.lstrip('@')
        updates.append('telegram_username')

    obj.used_at = timezone.now()
    obj.save(update_fields=['used_at'])
    user.save(update_fields=updates)
    logger.info('Telegram подтверждён: user=%s telegram_id=%s%s',
                user.pk, telegram_id, ' (conflict)' if error else '')
    return user, error


def reject_verify_token(token: str):
    """Подтверждение «нет, это не я»: гасим токен и завершаем активные веб-сессии
    запросившего пользователя (разлогиниваем того, кто инициировал подтверждение).
    Возвращает (user|None, код_ошибки|None)."""
    obj = get_pending_token(token)
    if obj is None:
        return None, 'invalid'
    user = obj.user
    obj.used_at = timezone.now()
    obj.save(update_fields=['used_at'])
    _logout_user_web_sessions(user)
    logger.info('Telegram НЕ подтверждён (нет): user=%s разлогинен из веба.', user.pk)
    return user, None


def _logout_user_web_sessions(user: User):
    """Удаляет все активные веб-сессии пользователя (как при сбросе веб-кредов)."""
    dc.logout_user_web_sessions(user)
