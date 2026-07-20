"""Справка ВЦ о работе волонтёра для ПГАС. Здесь — вся доменная логика справки:
условия выдачи (заполненный + верифицированный менеджером профиль), сбор
мероприятий волонтёра для тела справки, редактируемый менеджером шаблон и его
рендер, а также сброс верификации при изменении верифицируемых полей.

Сам пайплайн PDF (HTML→WeasyPrint→растр в «картинку») изолирован в
blog/services/pgas_pdf.py (системные зависимости — только там)."""
from django.utils import timezone

from blog.logging_utils import get_web_logger
from blog.models import (
    Application, EventStaff, Participation, PgasCertificateTemplate, User,
)
from blog.services.roles import account_is_complete, account_missing_fields

logger = get_web_logger(__name__)

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


# ---------------------------------------------------------------------------
# Верификация: снимок значений и сброс при изменении
# ---------------------------------------------------------------------------

# Поля, которые менеджер удостоверяет при верификации для справки ПГАС. Меняем в
# одном месте (единый источник правды): факультет/ОП/год поступления → курс —
# это то, что печатается в справке; ФИО — на кого выдана; telegram_username —
# канал связи. Изменил любое — верификация недействительна (человек мог
# перевестись на другую ОП, сменить фамилию и т.п.).
VERIFIED_FIELDS = (
    'first_name', 'last_name', 'middle_name',
    'faculty', 'education_program', 'admission_year', 'telegram_username',
)


def snapshot_verified_fields(user: User) -> dict:
    """Снимок текущих значений VERIFIED_FIELDS — сохраняется в момент верификации
    в user.verified_snapshot. Значения нормализуем к строке/None, чтобы сравнение
    было устойчивым (пустая строка и None считаются одинаковыми)."""
    snap = {}
    for field in VERIFIED_FIELDS:
        value = getattr(user, field, None)
        if isinstance(value, str):
            value = value.strip() or None
        snap[field] = value
    return snap


def verification_invalidated(user: User) -> bool:
    """True, если пользователь верифицирован, но текущие значения верифицируемых
    полей разошлись со снимком (verified_snapshot). Если снимка нет (верификация
    из старого кода) — сравнивать не с чем, считаем неизменённым."""
    if user.verified_by_manager_at is None or not user.verified_snapshot:
        return False
    return snapshot_verified_fields(user) != user.verified_snapshot


def revoke_verification_if_changed(user: User, actor: User = None) -> bool:
    """Если верификация стала недействительной (изменены ФИО/ОП/факультет/год/TG),
    снимаем её (verified_by_manager_at/_by/snapshot → None), логируем, заводим
    инцидент `pgas_verification` и уведомляем менеджеров — чтобы подтвердили заново
    на новых данных. Возвращает True, если верификация была снята.

    Вызывается из точек, где пользователь/менеджер правит профиль (profile_edit)."""
    if not verification_invalidated(user):
        return False

    user.verified_by_manager_at = None
    user.verified_by_manager_by = None
    user.verified_snapshot = None
    user.save(update_fields=['verified_by_manager_at', 'verified_by_manager_by', 'verified_snapshot'])

    logger.info('Верификация ПГАС снята из-за изменения данных: user=%s', user.id)

    # Инцидент в «Главное» менеджера + уведомление активным менеджерам. Импорты
    # локальные — избегаем циклов (incidents/notifications тянут модели/сервисы).
    from blog.services.incidents import create_incident
    from blog.services.notifications import notify_user
    from blog.models import Manager

    create_incident(
        'pgas_verification',
        f'«{user.full_name}» изменил(а) данные профиля — требуется повторная '
        f'верификация для справки ПГАС.',
        related_user=user,
    )
    manager_users = User.objects.filter(
        id__in=Manager.objects.filter(revoked_at__isnull=True).values('user_id')
    )
    for manager in manager_users:
        notify_user(
            manager,
            f'⚠️ Волонтёр «{user.full_name}» изменил(а) верифицированные данные. '
            f'Верификация для справки ПГАС снята — подтвердите профиль заново.',
        )
    return True


# ---------------------------------------------------------------------------
# Сбор мероприятий волонтёра для тела справки
# ---------------------------------------------------------------------------

from blog.services.formatting import fmt_date as _fmt_day  # единый форматтер (audit-reuse §2)


def collect_events(user: User, date_from=None, date_to=None, event_ids=None) -> list:
    """Мероприятия волонтёра для перечисления в справке — по ПОСЕЩЁННЫМ сменам
    (Participation.status='attended'), сгруппированные по мероприятию (одно меро —
    один пункт справки), как в experience.build_experience / person_report.

    Фильтры (складываются): date_from/date_to — по дню смены (EventShift.day);
    event_ids — явный список мероприятий (менеджер выбрал галочками). Волонтёр в
    ЛС передаёт только охват (сезон/всё время), менеджер — диапазон + выбор.

    Каждый пункт:
      {'event_id', 'title', 'dates' (дд.мм.гггг или диапазон), 'format'
       ('волонтёр'/'тим-лидер'), 'hours' ('дд.мм.гггг – N, …'), 'total_hours',
       'scale' (человекочитаемо), 'description'}.
    Порядок — по первой дате мероприятия (ранние сверху), как в справке-образце.
    """
    qs = (
        Participation.objects.filter(user=user, status='attended')
        .select_related('event_day', 'event_day__event')
    )
    if date_from and date_to:
        qs = qs.filter(event_day__day__gte=date_from, event_day__day__lte=date_to)
    if event_ids:
        qs = qs.filter(event_day__event_id__in=event_ids)

    # Роль волонтёра на меро (ТЛ?) — для «формата участия». По умолчанию «волонтёр».
    tl_event_ids = set(
        EventStaff.objects.filter(user=user, staff_role='team_lead')
        .values_list('event_id', flat=True)
    )
    # «Описание деятельности» и уточнение формата берём из заявки на это меро
    # (Application.role_in_event — заполняется при подаче/импорте).
    role_by_event = {
        a.event_id: (a.role_in_event or '').strip()
        for a in Application.objects.filter(user=user).only('event_id', 'role_in_event')
        if (a.role_in_event or '').strip()
    }

    by_event = {}
    for p in qs.order_by('event_day__day'):
        event = p.event_day.event
        entry = by_event.get(event.id)
        if entry is None:
            entry = {
                'event_id': event.id,
                'title': event.title,
                'format': 'тим-лидер' if event.id in tl_event_ids else 'волонтёр',
                'scale': event.get_scale_display() if event.scale else '',
                'description': role_by_event.get(event.id, '') or (event.description or '').strip(),
                '_days': [],  # (day, hours)
            }
            by_event[event.id] = entry
        entry['_days'].append((p.event_day.day, p.hours or 0))

    events = []
    for entry in by_event.values():
        days = sorted(entry.pop('_days'), key=lambda d: d[0])
        first, last = days[0][0], days[-1][0]
        entry['dates'] = _fmt_day(first) if first == last else f'{_fmt_day(first)}–{_fmt_day(last)}'
        # Часы по дням: «дд.мм.гггг – N» через запятую (как в справке-образце).
        entry['hours'] = ', '.join(f'{_fmt_day(day)} – {hours}' for day, hours in days)
        entry['total_hours'] = sum(hours for _, hours in days)
        entry['_first_day'] = first
        events.append(entry)

    events.sort(key=lambda e: e['_first_day'])
    for e in events:
        e.pop('_first_day', None)
    return events


# ---------------------------------------------------------------------------
# Шаблон справки (загружаемый менеджером .docx) и его рендер
# ---------------------------------------------------------------------------

# Строки-маркеры блока перечисления мероприятий (менеджер вставляет их в Word).
EVENTS_BLOCK_START = '### START EVENTS ###'
EVENTS_BLOCK_END = '### END EVENTS ###'

# Путь к дефолтному .docx-шаблону в репозитории (структура справки-образца).
# Загружается лениво в БД при первом обращении (get_template), без data-миграции.
import os
DEFAULT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'pgas_default_template.docx')

# Плейсхолдеры полей волонтёра — общие (вне блока мероприятий). {course}/{graduation_year}
# считаются из admission_year (compute_course_and_graduation). Документированы в
# гайде на странице выдачи (partials/_pgas_placeholder_guide.html).
FIELD_PLACEHOLDERS_HELP = [
    ('{full_name}', 'ФИО волонтёра'),
    ('{faculty}', 'Факультет'),
    ('{education_program}', 'Образовательная программа (ОП)'),
    ('{course}', 'Текущий курс (из года поступления)'),
    ('{graduation_year}', 'Год выпуска'),
    ('{admission_year}', 'Год поступления'),
    ('{date}', 'Дата выдачи справки'),
    ('{period}', 'Охват (сезон / диапазон / всё время)'),
]

# Гендерные плейсхолдеры: (мужская, женская) форма. Подставляются по user.gender;
# если пол не указан — мужская форма (с предупреждением в лог). Документированы в
# гайде. Так менеджер пишет {student} вместо «студент(ка)».
GENDER_PLACEHOLDERS = {
    '{student}': ('студент', 'студентка'),
    '{participated}': ('принял', 'приняла'),
    '{he_she}': ('он', 'она'),
    '{his_her}': ('его', 'её'),
    '{studying}': ('обучающийся', 'обучающаяся'),
}

# Плейсхолдеры внутри блока мероприятия (подставляются в каждой итерации).
EVENT_PLACEHOLDERS_HELP = [
    ('{n}', 'Порядковый номер мероприятия'),
    ('{title}', 'Название мероприятия'),
    ('{dates}', 'Дата(ы) проведения'),
    ('{format}', 'Формат участия (волонтёр / тим-лидер)'),
    ('{hours}', 'Количество часов по дням'),
    ('{scale}', 'Масштаб мероприятия'),
    ('{description}', 'Описание деятельности'),
]


def get_template() -> PgasCertificateTemplate:
    """Синглтон-шаблон (pk=1). При первом обращении (или если файл ещё не загружен)
    лениво заполняется дефолтным .docx из репозитория — чтобы менеджер сразу видел
    рабочий шаблон и мог его скачать/заменить, без data-миграции."""
    template = PgasCertificateTemplate.objects.first()
    if template is None:
        template = PgasCertificateTemplate.objects.create()
    if not template.docx_file:
        with open(DEFAULT_TEMPLATE_PATH, 'rb') as f:
            template.docx_file = f.read()
        template.filename = 'pgas_default_template.docx'
        template.save(update_fields=['docx_file', 'filename'])
    return template


def _gender_value(placeholder_forms, gender: str) -> str:
    """Выбор формы слова по полу: female → вторая форма, иначе (male/None) — первая."""
    male, female = placeholder_forms
    return female if gender == 'female' else male


def build_replacements(user: User, *, period_label: str, issue_date) -> dict:
    """Плейсхолдеры «шапки» (поля волонтёра + гендерные + дата/период) → значения.
    Единый источник для рендера. Блоковые плейсхолдеры мероприятия — отдельно."""
    course_info = compute_course_and_graduation(user)
    if not user.gender:
        logger.warning('Пол не указан для справки ПГАС (user=%s) — берём мужскую форму', user.id)

    repl = {
        '{full_name}': user.full_name,
        '{faculty}': (user.faculty or '').strip(),
        '{education_program}': (user.education_program or '').strip(),
        '{course}': str(course_info['course']) if course_info['course'] else '',
        '{graduation_year}': str(course_info['graduation_year']) if course_info['graduation_year'] else '',
        '{admission_year}': str(user.admission_year) if user.admission_year else '',
        '{date}': issue_date.strftime('%d.%m.%Y'),
        '{period}': period_label,
    }
    for placeholder, forms in GENDER_PLACEHOLDERS.items():
        repl[placeholder] = _gender_value(forms, user.gender)
    return repl


def _event_replacements(event: dict, index: int) -> dict:
    return {
        '{n}': str(index),
        '{title}': event['title'],
        '{dates}': event['dates'],
        '{format}': event['format'],
        '{hours}': event['hours'],
        '{scale}': event['scale'],
        '{description}': event['description'],
    }


def _replace_in_paragraph(paragraph, replacements: dict):
    """Подстановка плейсхолдеров в параграфе. Плейсхолдер `{...}` в Word часто
    разбит на несколько runs — поэтому склеиваем текст всего параграфа, делаем
    замену и переписываем текст в первый run (остальные очищаем). Стиль абзаца и
    первого run сохраняются — этого достаточно для справки (плейсхолдеры набирают
    единым стилем)."""
    full = ''.join(run.text for run in paragraph.runs)
    if '{' not in full:
        return
    new_text = full
    for key, value in replacements.items():
        if key in new_text:
            new_text = new_text.replace(key, value or '')
    if new_text == full:
        return
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ''
    else:
        paragraph.add_run(new_text)


def render_docx(user: User, events: list, *, period_label: str, issue_date=None) -> bytes:
    """Рендер справки в .docx С СОХРАНЕНИЕМ оформления загруженного шаблона.

    Открываем шаблонный docx, подставляем плейсхолдеры «шапки» во всех параграфах,
    а блок между строками ### START EVENTS ### / ### END EVENTS ### разворачиваем в
    цикл: параграфы-шаблоны блока клонируем (копия XML-элемента — сохраняет
    оформление строки) под каждое мероприятие, подставляя {n}/{title}/… Строки-
    маркеры удаляем. Возвращает байты готового docx (для конвертации в PDF)."""
    import copy
    import io

    from docx import Document
    from docx.text.paragraph import Paragraph

    issue_date = issue_date or timezone.now().date()
    replacements = build_replacements(user, period_label=period_label, issue_date=issue_date)

    doc = Document(io.BytesIO(get_template().docx_file))
    body = doc.element.body

    # 1) Найти границы блока мероприятий по параграфам-маркерам.
    paragraphs = doc.paragraphs
    start_idx = end_idx = None
    for i, p in enumerate(paragraphs):
        text = p.text.strip()
        if text == EVENTS_BLOCK_START:
            start_idx = i
        elif text == EVENTS_BLOCK_END:
            end_idx = i
            break

    if start_idx is not None and end_idx is not None and end_idx > start_idx:
        # Параграфы-шаблоны между маркерами (сам блок, без строк-маркеров).
        template_paragraphs = paragraphs[start_idx + 1:end_idx]
        template_elems = [copy.deepcopy(p._p) for p in template_paragraphs]
        anchor = paragraphs[end_idx]._p  # маркер END — точка вставки (перед ним)

        # Для каждого мероприятия вставляем клон блока перед END-маркером.
        for idx, event in enumerate(events, start=1):
            ev_repl = _event_replacements(event, idx)
            for elem in template_elems:
                clone = copy.deepcopy(elem)
                anchor.addprevious(clone)
                # Подставить плейсхолдеры мероприятия в клоне.
                _replace_in_paragraph(Paragraph(clone, paragraphs[end_idx]._parent), ev_repl)

        # Удалить исходные строки-маркеры и параграфы-шаблоны блока.
        for p in [paragraphs[start_idx], *template_paragraphs, paragraphs[end_idx]]:
            p._p.getparent().remove(p._p)

    # 2) Подставить плейсхолдеры «шапки» во всех оставшихся параграфах и таблицах.
    for p in doc.paragraphs:
        _replace_in_paragraph(p, replacements)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    _replace_in_paragraph(p, replacements)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def season_range():
    """Границы текущего сезона (start, end) для охвата «за сезон» в ЛС. end берётся
    как end_season, либо сегодня, если сезон ещё не закрыт. None, если сезона нет."""
    from data_base import data_controller

    season = data_controller.get_current_season()
    if season is None:
        return None, None
    return season.start_season, (season.end_season or timezone.now().date())
