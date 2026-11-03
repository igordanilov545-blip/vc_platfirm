"""Реестр людей и их смен по мероприятию/позиции, включая необработанные заявки."""
from collections import defaultdict
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.formats import date_format
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from data_base import data_controller as dc
from blog.services.applications import application_shifts
from blog.services.requirements import _age_on
from blog.services.roles import can_process_applications, has_manager_access


PROFILE_HEADERS = [
    'Имя', 'Фамилия', 'Возраст', 'Дата рождения', 'Электронная почта',
    'Мобильный телефон', 'Ник в Telegram', 'Ссылка на страницу в ВКонтакте',
    'Ссылка на страницу в Инстаграме', 'Наиболее удобный способ связи',
    'Размер футболки', 'Число смен',
]
STATUS_LABELS = {'new': 'Новая заявка', 'approved': 'Одобрена',
                 'rejected': 'Резерв', 'cancelled': 'Отменена'}


def _profile(source, application, today):
    birthday = getattr(source, 'birthday', None)
    vk = getattr(source, 'vk_profile_url', '') or getattr(source, 'VK_username', '') or ''

    def value(field):
        return getattr(source, field, '') or getattr(application, field, '') or ''

    return [value('first_name'), value('last_name'),
            _age_on(birthday, today) if birthday and birthday <= today else None,
            birthday, getattr(source, 'email', '') or '', value('phone'),
            value('telegram_username'), vk, getattr(source, 'instagram_profile_url', '') or getattr(source, 'instagram_url', '') or '',
            getattr(source, 'preferred_contacts_display', ''), getattr(source, 'tshirt_size', '')]


def _append(ws, values):
    """Пользовательские строки остаются текстом, в том числе начинающиеся с '='."""
    ws.append([ILLEGAL_CHARACTERS_RE.sub('', value) if isinstance(value, str) else value for value in values])
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = 's'


def _format(ws, *, people=False):
    ws.freeze_panes = 'C2' if people else 'B2'
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 62
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='483D8B')
    for row in ws:
        for cell in row:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
    for index in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(index)].width = 36 if people and index > 12 else 24
    if people:
        for row in ws.iter_rows(min_row=2):
            row[3].number_format = 'DD.MM.YYYY'
            row[5].number_format = '@'


def build_roster_workbook(operator, *, group=None, position=None):
    """Один человек на строку; даты МСК, смены и решения — без изменения данных."""
    if position is not None:
        if not can_process_applications(operator, position.pk):
            raise PermissionDenied('Нет доступа к реестру этой позиции.')
        positions = [position]
        title = position.event_group.title if position.event_group_id else position.title
    elif group is not None:
        if not has_manager_access(operator):
            raise PermissionDenied('Реестр всего мероприятия доступен менеджеру.')
        positions = list(dc.events_qs().filter(event_group=group).order_by('title', 'pk'))
        title = group.title
    else:
        raise ValueError('Нужно указать мероприятие или позицию.')
    shifts = list(dc.event_shifts_qs().filter(event__in=positions).select_related('event', 'legacy_source').order_by('start_time', 'pk'))
    shift_by_id = {shift.pk: shift for shift in shifts}
    days = sorted({timezone.localtime(shift.start_time).date() for shift in shifts})
    today = timezone.localdate()
    people = {}

    def person(key, source, application=None):
        if key not in people:
            people[key] = {'profile': _profile(source, application, today), 'assignments': {}, 'position_ids': set()}
        return people[key]

    applications = dc.applications_qs().filter(event__in=positions).select_related('user', 'event').prefetch_related(
        'selected_shifts', 'event__shifts', 'shift_decisions',
    ).order_by('pk')
    for app in applications:
        # Без связанного User нет надёжной идентичности: не склеиваем людей по ФИО.
        key = ('user', app.user_id) if app.user_id else ('application', app.pk)
        row = person(key, app.user or app, app)
        row['position_ids'].add(app.event_id)
        decisions = {decision.shift_id: decision.status for decision in app.shift_decisions.all()}
        for selected in application_shifts(app):
            shift = shift_by_id.get(selected.pk)
            if shift and shift.event_id == app.event_id:
                status = 'cancelled' if app.status == 'cancelled' else decisions.get(shift.pk, app.status)
                row['assignments'][shift.pk] = {'shift': shift, 'status': status, 'attendance': None}
    for part in dc.participations_qs().filter(event_day__event__in=positions).select_related('user'):
        row = person(('user', part.user_id), part.user)
        row['position_ids'].add(shift_by_id[part.event_day_id].event_id)
        row['assignments'][part.event_day_id] = {'shift': shift_by_id[part.event_day_id], 'status': 'approved', 'attendance': part.status}

    wb = Workbook()
    ws = wb.active
    ws.title = 'Участники'
    _append(ws, PROFILE_HEADERS + [f'{title}\n{date_format(day, "j E Y", use_l10n=True)}' for day in days])
    people_rows = sorted(people.values(), key=lambda row: (str(row['profile'][1]).casefold(), str(row['profile'][0]).casefold()))
    for row in people_rows:
        daily = defaultdict(list)
        for item in sorted(row['assignments'].values(), key=lambda item: (item['shift'].start_time, item['shift'].pk)):
            shift = item['shift']
            start, end = timezone.localtime(shift.start_time), timezone.localtime(shift.end_time)
            label = STATUS_LABELS.get(item['status'], item['status'])
            if item['attendance']:
                label += ' · ' + {'pending': 'Не отмечен', 'attended': 'Был', 'absent_excused': 'Не был (уваж.)', 'absent_unexcused': 'Не был'}.get(item['attendance'], item['attendance'])
            end_label = end.strftime('%H:%M') if end.date() == start.date() else end.strftime('%d.%m %H:%M')
            interval = 'время не указано' if shift.time_unknown else f'{start:%H:%M}–{end_label}'
            if shift.date_unknown:
                interval += ' · дата условная'
            legacy = getattr(shift, 'legacy_source', None)
            if legacy:
                interval += ' · ' + ' / '.join(legacy.source_header.splitlines())
            daily[start.date()].append(f'{shift.event.title} · {interval} · {label}')
        _append(ws, row['profile'] + [len(row['assignments'])] + ['\n'.join(daily[day]) or None for day in days])
    _format(ws, people=True)

    summary = wb.create_sheet('Сводка')
    _append(summary, ['Охват', 'Уникальных людей', 'Смен', 'Записей на смены',
                      'Одобрено', 'Новые заявки', 'Резерв', 'Отменено', 'Явка «Был»'])
    for label, event_ids in [(group.title if group else position.title, {event.pk for event in positions})] + [
        (event.title, {event.pk}) for event in positions
    ]:
        scoped = [[item for item in row['assignments'].values() if item['shift'].event_id in event_ids] for row in people_rows]
        items = [item for assignments in scoped for item in assignments]
        unique = sum(bool(row['position_ids'] & event_ids) for row in people_rows)
        _append(summary, [label, unique, sum(shift.event_id in event_ids for shift in shifts), len(items)] +
                [sum(item['status'] == status for item in items) for status in ('approved', 'new', 'rejected', 'cancelled')] +
                [sum(item['attendance'] == 'attended' for item in items)])
    _format(summary)
    return wb
