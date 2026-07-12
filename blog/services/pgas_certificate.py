"""Справка ВЦ о работе волонтёра для ПГАС (за сезон). Условия выдачи: полностью
заполненный и верифицированный профиль. Сама генерация документа (PDF/текст) не
реализована — только реальная проверка условий доступности кнопки (см. views.py)."""
from blog.models import User
from blog.services.roles import account_is_complete, account_missing_fields


def pgas_certificate_eligibility(user: User) -> dict:
    """Возвращает {'eligible': bool, 'missing': list[str]} — что не хватает для
    получения справки. `missing` — человекочитаемые причины, в порядке проверки."""
    missing = list(account_missing_fields(user)) if not account_is_complete(user) else []

    if not (user.faculty or '').strip():
        missing.append('факультет')
    if not (user.education_program or '').strip():
        missing.append('образовательная программа (ОП)')
    if not user.admission_year:
        missing.append('год поступления')
    if user.verified_by_manager_at is None:
        missing.append('верификация менеджером ВЦ')

    return {'eligible': not missing, 'missing': missing}


def only_verification_missing(user: User) -> bool:
    """Всё заполнено, не хватает только ручной верификации менеджером — тогда
    показываем кнопку «Запросить верификацию» вместо простого списка недостающего."""
    result = pgas_certificate_eligibility(user)
    return result['missing'] == ['верификация менеджером ВЦ']
