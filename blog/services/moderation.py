"""Модерация пользователей: блэклист, вывод из ЧС, верификация для справки ПГАС.

Бизнес-правила (coding-principles §1, §4) живут здесь, а не во вьюхах; доступ к
данным — через `data_controller`. Вьюхи (`user_blacklist`, `pgas_verify_user`, …)
разбирают запрос и зовут эти функции.
"""
from data_base import data_controller as dc
from blog.services.stats import log_churn_change


def blacklist_user(user, reason: str, *, actor):
    """Блокировка волонтёра менеджером. Ставит статус 'blacklisted' + причину в comment
    (внутреннее поле, видно только менеджеру; пользователь НЕ уведомляется).
    Фиксирует событие в журнале churn (delta=0, force — важен сам факт блокировки, а не
    изменение числа; db.md, правило 9)."""
    dc.set_user_status(user, 'blacklisted', comment=reason, actor_user=actor)
    log_churn_change(
        user, 'blacklist', 0, actor=actor, note=reason, force=True,
    )
    return user


def unblacklist_user(user, *, actor):
    """Вывод из чёрного списка. Ставит статус 'active' и ОБНУЛЯЕТ churn_score: иначе,
    если churn остался ≥ порога, ближайший пересчёт снова автоматически отправит
    пользователя в блэклист — ручной вывод был бы бессмысленным (db.md, правило 9).
    Возвращает (user, было_в_чс: bool)."""
    if user.status != 'blacklisted':
        return user, False
    before = user.churn_score or 0
    dc.set_user_status(user, 'active', churn_score=0, actor_user=actor)
    log_churn_change(
        user, 'unblacklist', -before, actor=actor,
        note='Вывод из ЧС, churn обнулён', force=True,
    )
    return user, True


def verify_user_for_pgas(user, *, actor, snapshot):
    """Менеджер подтверждает верификацию волонтёра для справки ПГАС. Сохраняет снимок
    верифицированных полей (для отслеживания их последующего изменения) и резолвит
    связанный инцидент `pgas_verification`, если он есть."""
    from django.utils import timezone
    dc.set_user_verification(user, verified_at=timezone.now(), verified_by=actor, snapshot=snapshot)
    dc.resolve_incidents('pgas_verification', user, resolved_by=actor)
    return user


def unverify_user_for_pgas(user, *, actor):
    """Отзыв верификации для справки ПГАС — симметрично выдаче, без капчи (возврат в
    исходное состояние, а не запуск нового необратимого процесса)."""
    dc.set_user_verification(user, verified_at=None, verified_by=None, snapshot=None)
    return user
