"""Справка ВЦ о работе волонтёра для ПГАС (за сезон). Условия выдачи: полностью
заполненный и верифицированный профиль. Сама генерация документа (PDF/текст) не
реализована — только реальная проверка условий доступности кнопки (см. views.py)."""
from django.utils import timezone

from blog.models import User
from blog.services.roles import account_is_complete, account_missing_fields

# Длительность обучения по образовательной программе, лет. Жёсткий словарь без
# UI-управления (по требованию — всё по умолчанию 4 года, точечные исключения
# добавляются сюда вручную по мере необходимости).
PROGRAM_YEARS = {}
DEFAULT_PROGRAM_YEARS = 4


def program_duration_years(education_program: str) -> int:
    return PROGRAM_YEARS.get((education_program or '').strip(), DEFAULT_PROGRAM_YEARS)


def compute_course_and_graduation(user: User) -> dict:
    """Возвращает {'course': int|None, 'graduation_year': int|None} по
    admission_year/education_program. `course` — текущий курс обучения (не выше
    длительности программы); None, если admission_year не заполнен."""
    if not user.admission_year:
        return {'course': None, 'graduation_year': None}
    years = program_duration_years(user.education_program)
    current_year = timezone.now().year
    course = max(1, current_year - user.admission_year + 1)
    graduation_year = user.admission_year + years
    return {'course': min(course, years), 'graduation_year': graduation_year}


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
