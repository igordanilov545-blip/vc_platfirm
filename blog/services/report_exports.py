"""Сырые построчные выгрузки и данные для отчётов-документов
(reports_template.md §2.1, §2.2, §4, §5).

Отделено от `reports.py` (там — агрегатная аналитика за период). Здесь — построчные
данные: заявки, мероприятия, отчёт по одному меро, простановка часов на Добро.ру,
а также сборка Excel-книг (используется и вьюхой экспорта, и комплексным ZIP-отчётом).
Охват задаётся так же — либо период (date_from/date_to), либо список event_ids.
"""
from django.db.models import Avg, Count, Sum

from blog.models import (
    Application, Event, EventShift, EventStaff, Participation,
)
from blog.services import reports as reports_service


def _fmt_dt(value):
    """openpyxl не умеет tz-aware datetime — отдаём строкой."""
    if value is None:
        return '—'
    if hasattr(value, 'strftime'):
        return value.strftime('%d.%m.%Y %H:%M') if hasattr(value, 'hour') else value.strftime('%d.%m.%Y')
    return str(value)


def _staff_names(event, role):
    names = []
    for st in event.staff.filter(staff_role=role).select_related('user'):
        names.append(st.user.full_name)
    return ', '.join(names) or '—'


def applications_rows(date_from=None, date_to=None, event_ids=None):
    """Сырая построчная выгрузка заявок (reports_template.md §2.1).

    Одна approved-заявка разворачивается в несколько строк — по строке на смену участия
    (participations). new/rejected/cancelled — одна строка без участия."""
    events = reports_service._events_in_scope(date_from, date_to, event_ids)
    if event_ids:
        apps = Application.objects.filter(event__in=events)
    else:
        apps = Application.objects.filter(
            created_at__date__gte=date_from, created_at__date__lte=date_to,
        )
    apps = apps.select_related('event', 'user', 'assigned_by').prefetch_related('selected_shifts')

    rows = []
    for app in apps:
        base = {
            'id': app.id,
            'name': f"{app.first_name or ''} {app.last_name or ''}".strip(),
            'telegram': app.telegram_username or '',
            'phone': app.phone or '',
            'user_id': app.user_id or '—',
            'event': app.event.title,
            'functions': app.functions or '',
            'role': app.role_in_event or '',
            'submitted_at': app.submitted_at,
            'created_at': app.created_at,
            'status': app.get_status_display(),
            'assigned_by': app.assigned_by.full_name if app.assigned_by else '—',
            'assigned_at': app.assigned_at,
        }

        # Участия этого волонтёра по сменам данного меро (если approved и есть профиль).
        parts = []
        if app.user_id:
            parts = list(
                Participation.objects.filter(user_id=app.user_id, event_day__event=app.event)
                .select_related('event_day')
            )
        if parts:
            for p in parts:
                row = dict(base)
                row.update({
                    'shift_day': p.event_day.day,
                    'attended': p.get_status_display(),
                    'full_shift': 'да' if p.full_shift else 'нет',
                    'hours': p.hours,
                })
                rows.append(row)
        else:
            row = dict(base)
            row.update({'shift_day': None, 'attended': '—', 'full_shift': '—', 'hours': '—'})
            rows.append(row)
    return rows


def events_rows(date_from=None, date_to=None, event_ids=None):
    """Сырая построчная выгрузка мероприятий (reports_template.md §2.2)."""
    events = reports_service._events_in_scope(date_from, date_to, event_ids).select_related(
        'organization', 'organizer'
    ).prefetch_related('shifts', 'category_map__category', 'staff__user', 'feedbacks')

    rows = []
    for event in events:
        shifts = list(event.shifts.all())
        days = [s.day for s in shifts]
        needed = sum(s.volunteer_needed or 0 for s in shifts)
        attended = Participation.objects.filter(event_day__event=event, status='attended')
        attended_count = attended.count()
        total_hours = attended.aggregate(s=Sum('hours'))['s'] or 0
        apps = Application.objects.filter(event=event)
        rating = event.feedbacks.aggregate(a=Avg('rating'), c=Count('id'))
        categories = ', '.join(m.category.name for m in event.category_map.all()) or '—'
        locations = ', '.join(sorted({s.location.name for s in shifts if s.location_id})) or '—'
        rows.append({
            'id': event.id,
            'title': event.title,
            'organization': event.organization.name if event.organization else '—',
            'organizer': f"{event.organizer.first_name} {event.organizer.last_name}" if event.organizer else '—',
            'categories': categories,
            'date_from': min(days) if days else None,
            'date_to': max(days) if days else None,
            'shift_count': len(shifts),
            'locations': locations,
            'event_status': event.get_event_status_display(),
            'needed': needed,
            'submitted': apps.count(),
            'approved': apps.filter(status='approved').count(),
            'attended': attended_count,
            'pct_closed': round(attended_count / needed * 100, 1) if needed else 0,
            'total_hours': total_hours,
            'people_helped': event.people_helped if event.people_helped is not None else '—',
            'rating': round(rating['a'], 1) if rating['a'] is not None else '—',
            'rating_count': rating['c'],
            'managers': _staff_names(event, 'manager'),
            'team_leads': _staff_names(event, 'team_lead'),
            'dobro_kind': event.get_dobro_ru_link_kind_display(),
            'dobro_logged': 'да' if event.dobro_ru_hours_logged else 'нет',
        })
    return rows


def event_report(event_id):
    """Данные для отчёта по одному мероприятию (reports_template.md §4)."""
    event = Event.objects.select_related('organization', 'organizer', 'letter').prefetch_related(
        'shifts__location', 'category_map__category', 'staff__user'
    ).get(pk=event_id)

    categories = ', '.join(m.category.name for m in event.category_map.all()) or '—'
    managers = [st.user for st in event.staff.filter(staff_role='manager')]
    team_leads = [st.user for st in event.staff.filter(staff_role='team_lead')]

    shifts_data = []
    for shift in event.shifts.all().order_by('day', 'start_time'):
        participants = []
        parts = Participation.objects.filter(event_day=shift).select_related('user')
        for p in parts:
            app = (
                Application.objects.filter(event=event, user=p.user)
                .order_by('-created_at').first()
            )
            participants.append({
                'name': p.user.full_name,
                'submitted_at': app.submitted_at if app else None,
                'app_status': app.get_status_display() if app else '—',
                'part_status': p.get_status_display(),
                'hours': p.hours,
                'full_shift': p.full_shift,
            })
        shifts_data.append({
            'day': shift.day,
            'start_time': shift.start_time,
            'end_time': shift.end_time,
            'location': shift.location.name if shift.location else '—',
            'needed': shift.volunteer_needed,
            'participants': participants,
        })

    apps = Application.objects.filter(event=event)
    attended = Participation.objects.filter(event_day__event=event, status='attended')
    needed_total = sum(s.volunteer_needed or 0 for s in event.shifts.all())
    attended_count = attended.count()
    rating = event.feedbacks.aggregate(a=Avg('rating'), c=Count('id'))

    return {
        'event': event,
        'categories': categories,
        'managers': managers,
        'team_leads': team_leads,
        'shifts': shifts_data,
        'totals': {
            'submitted': apps.count(),
            'approved': apps.filter(status='approved').count(),
            'attended': attended_count,
            'needed': needed_total,
            'pct_closed': round(attended_count / needed_total * 100, 1) if needed_total else 0,
            'total_hours': attended.aggregate(s=Sum('hours'))['s'] or 0,
            'people_helped': event.people_helped,
            'rating': round(rating['a'], 1) if rating['a'] is not None else None,
            'rating_count': rating['c'],
        },
    }


def dobro_logging_report(date_from=None, date_to=None, event_ids=None, show_logged=False):
    """Отчёт простановки часов на Добро.ру в двух разрезах (reports_template.md §5,
    reports.md §8). В отчёт попадают attended-участия (hours>0) на меро с
    dobro_ru_link_kind ∈ {shared, unique}; kind='none' исключаются."""
    events = reports_service._events_in_scope(date_from, date_to, event_ids).exclude(
        dobro_ru_link_kind='none'
    ).select_related('dobro_ru_shared_link')

    parts_qs = Participation.objects.filter(
        event_day__event__in=events, status='attended', hours__gt=0,
    ).select_related('user', 'event_day', 'event_day__event', 'event_day__event__dobro_ru_shared_link')
    if not show_logged:
        parts_qs = parts_qs.filter(dobro_ru_logged=False)

    # Разрез «по ссылке»: ключ — (kind, link_url, title)
    by_link = {}
    # Разрез «по человеку»: ключ — user_id
    by_person = {}

    for p in parts_qs:
        event = p.event_day.event
        if event.dobro_ru_link_kind == 'unique':
            link_key = f'event:{event.id}'
            link_url = event.dobro_ru_link or '—'
            link_title = event.title
        else:  # shared
            shared = event.dobro_ru_shared_link
            link_key = f'shared:{shared.id}' if shared else 'shared:none'
            link_url = shared.url if shared else '—'
            link_title = shared.title if shared else 'Общая ссылка (не задана)'

        row = {
            'user': p.user.full_name,
            'user_id': p.user_id,
            'event': event.title,
            'day': p.event_day.day,
            'hours': p.hours,
            'logged': p.dobro_ru_logged,
            'participation_id': p.id,
            'link_kind': event.dobro_ru_link_kind,
            'link_url': link_url,
            'link_title': link_title,
        }

        link = by_link.setdefault(link_key, {
            'title': link_title, 'url': link_url, 'kind': event.dobro_ru_link_kind,
            'rows': [], 'total_hours': 0, 'logged_count': 0,
        })
        link['rows'].append(row)
        link['total_hours'] += p.hours
        if p.dobro_ru_logged:
            link['logged_count'] += 1

        person = by_person.setdefault(p.user_id, {
            'name': p.user.full_name, 'telegram': p.user.telegram_username or '',
            'rows': [], 'total_hours': 0,
        })
        person['rows'].append(row)
        person['total_hours'] += p.hours

    excluded_none = reports_service._events_in_scope(date_from, date_to, event_ids).filter(
        dobro_ru_link_kind='none'
    ).count()

    all_parts = Participation.objects.filter(
        event_day__event__in=events, status='attended', hours__gt=0,
    )
    return {
        'by_link': list(by_link.values()),
        'by_person': list(by_person.values()),
        'summary': {
            'to_log': all_parts.filter(dobro_ru_logged=False).count(),
            'logged': all_parts.filter(dobro_ru_logged=True).count(),
            'excluded_none': excluded_none,
        },
    }


# ---------------------------------------------------------------------------
# Сборка Excel-книг (reports_template.md §2, §4, §5)
# ---------------------------------------------------------------------------

def build_period_workbook(date_from, date_to, event_ids, scope_mode, compare_mode):
    """Книга отчёта за охват: по ЛИСТУ на каждую экранную таблицу ERP-раздела
    (Волонтёры / Мероприятия / Тим-лидеры / Менеджеры / Заявки) с теми же колонками,
    что и на экране. Пользователь переключается между таблицами на странице, а скачивает
    сразу всё за выбранный период — по листу на таблицу."""
    from openpyxl import Workbook

    wb = Workbook()

    # --- Волонтёры ---
    ws = wb.active
    ws.title = 'Волонтёры'
    ws.append([
        'ФИО', 'Телефон', 'Telegram', 'Часы (охват)', 'Часы за сезон', 'Часы за всё время',
        'Меро за сезон', 'Меро за всё время', 'Ср. часов на меро', 'Смен всего', 'Смен за сезон',
        'Ср. длит. смены, ч', 'Первое меро', 'Дней с нами', 'Последнее меро', 'Последняя заявка',
        'Дней с посл. меро', 'Churn',
    ])
    for r in reports_service.volunteers_table(date_from, date_to, event_ids=event_ids):
        ws.append([
            r['name'], r['phone'], r['telegram'], r['hours_total'], r['hours_season'], r['hours_total'],
            r['events_season'], r['events_attended'], r['avg_hours_per_event'], r['shifts_total'],
            r['shifts_season'], r['avg_shift_hours'], r['first_event'],
            r['days_with_us'] if r['days_with_us'] is not None else '—', r['last_event'],
            r['last_application'], r['days_since_last_event'] if r['days_since_last_event'] is not None else '—',
            r['churn'],
        ])

    # --- Мероприятия (посменные колонки) ---
    ev_rows, max_shifts = reports_service.events_table(date_from, date_to, event_ids=event_ids)
    ws_ev = wb.create_sheet('Мероприятия')
    ws_ev.append(
        ['Название', 'Статус', 'Смен']
        + [f'Смена {i}' for i in range(1, max_shifts + 1)]
        + ['Нужно человек', 'Заявок', 'Принято', 'Отклонено', 'Осталось',
           'Организация', 'Организатор', 'TG организатора', 'Телефон организатора']
    )
    for r in ev_rows:
        cells = list(r['shift_cells']) + ['—'] * (max_shifts - len(r['shift_cells']))
        ws_ev.append(
            [r['title'], r['status_display'], r['shifts_count']]
            + cells
            + [r['needed'], r['submitted'], r['approved'], r['rejected'], r['remaining'],
               r['organization'], r['organizer'], r['organizer_tg'], r['organizer_phone']]
        )

    # --- Тим-лидеры / Менеджеры ---
    for sheet_name, builder, role_word in (
        ('Тим-лидеры', reports_service.team_leaders_table, 'ТЛ'),
        ('Менеджеры', reports_service.managers_table, 'менеджером'),
    ):
        ws_r = wb.create_sheet(sheet_name)
        ws_r.append([
            'ФИО', 'Телефон', 'Telegram', f'Меро {role_word} за сезон', f'Меро {role_word} всего',
            'Назначен', 'Дней в роли', 'Первое меро в роли', 'Последнее меро в роли',
            'Дней с первого меро', 'Дней с последнего меро', 'Людей на его меро (сумма)',
            'Людей на меро (среднее)', 'Заявок обработано', 'Из них принято', 'Из них отклонено',
            'Часы волонтёром (всё)', 'Часы волонтёром (сезон)', 'Меро волонтёром (всё)',
            'Смен волонтёром', 'Churn',
        ])
        for r in builder(date_from, date_to, event_ids=event_ids):
            def _d(key):
                v = r.get(key)
                return v if v is not None else '—'
            ws_r.append([
                r.get('name', '—'), r.get('phone', '—'), r.get('telegram', '—'),
                r['role_events_season'], r['role_events_total'], r['role_assigned_at'],
                _d('role_days_since_assigned'), r['role_first_event'], r['role_last_event'],
                _d('role_days_since_first'), _d('role_days_since_last'), r['role_people_total'],
                r['role_people_avg'], r['role_apps_processed'], r['role_apps_approved'],
                r['role_apps_rejected'], r.get('hours_total', 0), r.get('hours_season', 0),
                r.get('events_attended', 0), r.get('shifts_total', 0), r.get('churn', 0),
            ])

    # --- Заявки ---
    ws_apps = wb.create_sheet('Заявки')
    ws_apps.append([
        'ID', 'ФИО', 'Телефон', 'Telegram', 'Мероприятие', 'Функция', 'Роль', 'Статус',
        'Источник', 'Когда подал', 'Кто обработал', 'Когда обработано', 'Ожидание, ч',
    ])
    for r in reports_service.applications_table(date_from, date_to, event_ids=event_ids):
        ws_apps.append([
            r['id'], r['name'], r['phone'], r['telegram'], r['event'], r['functions'], r['role'],
            r['status'], r['source'], r['submitted_at'], r['assigned_by'], r['assigned_at'], r['wait_hours'],
        ])

    return wb


def build_event_workbook(event_id):
    """Книга отчёта по одному мероприятию (reports_template.md §4 Excel-версия)."""
    from openpyxl import Workbook

    rep = event_report(event_id)
    event = rep['event']
    wb = Workbook()

    ws = wb.active
    ws.title = 'Шапка'
    ws.append(['Отчёт по мероприятию', event.title])
    ws.append([])
    ws.append(['Организация', rep['event'].organization.name if event.organization else '—'])
    ws.append(['Организатор', f"{event.organizer.first_name} {event.organizer.last_name}" if event.organizer else '—'])
    ws.append(['Категории', rep['categories']])
    ws.append(['Локация', ', '.join(sorted({s['location'] for s in rep['shifts']}))])
    ws.append(['Статус', event.get_event_status_display()])
    ws.append(['Ссылка на чат', event.chat_link or '—'])
    ws.append(['Пост в канале', event.post_in_chanel_link or '—'])
    ws.append(['Добро.ру', event.dobro_ru_link or '—'])
    ws.append(['Менеджеры', ', '.join(u.full_name for u in rep['managers']) or '—'])
    ws.append(['Тим-лидеры', ', '.join(u.full_name for u in rep['team_leads']) or '—'])

    ws_sh = wb.create_sheet('Смены и участники')
    ws_sh.append(['Смена (день)', 'Волонтёр', 'Когда подал', 'Статус заявки', 'Статус участия', 'Полная смена', 'Часы'])
    for shift in rep['shifts']:
        if not shift['participants']:
            ws_sh.append([shift['day'].isoformat(), '— нет участников —', '', '', '', '', ''])
        for p in shift['participants']:
            ws_sh.append([
                shift['day'].isoformat(), p['name'], _fmt_dt(p['submitted_at']),
                p['app_status'], p['part_status'], 'да' if p['full_shift'] else 'нет', p['hours'],
            ])

    ws_t = wb.create_sheet('Итоги')
    t = rep['totals']
    ws_t.append(['Показатель', 'Значение'])
    ws_t.append(['Всего заявок', t['submitted']])
    ws_t.append(['Одобрено', t['approved']])
    ws_t.append(['Явка', t['attended']])
    ws_t.append(['Нужно волонтёров', t['needed']])
    ws_t.append(['% закрытия', t['pct_closed']])
    ws_t.append(['Всего часов', t['total_hours']])
    ws_t.append(['Людей получили помощь', t['people_helped'] if t['people_helped'] is not None else '—'])
    ws_t.append(['Средний рейтинг', f"{t['rating']} ({t['rating_count']} отзывов)" if t['rating'] is not None else '—'])
    ws_t.append(['Внутренние комментарии', event.internal_comment or '—'])

    return wb


def dobro_matrix_data(date_from=None, date_to=None, event_ids=None, show_logged=False):
    """Данные для матричных листов простановки Добро.ру (reports_template.md,
    «Отчёт простановки часов на Добро.ру»): часы каждого человека по каждому
    мероприятию (сумма по всем сменам) + группировка мероприятий по ссылкам.

    Возвращает:
      users        — [{'user_id','name','telegram'}], по алфавиту;
      events       — [{'event_id','title','url','link_key','link_title'}], по названию;
      links        — {link_key: {'title','url','kind','event_ids':[...]}};
      hours[(user_id, event_id)] — часы (сумма по сменам) на пересечении;
      flat         — построчные записи для страницы 3.
    """
    events_qs = reports_service._events_in_scope(date_from, date_to, event_ids).exclude(
        dobro_ru_link_kind='none'
    ).select_related('dobro_ru_shared_link')

    parts_qs = Participation.objects.filter(
        event_day__event__in=events_qs, status='attended', hours__gt=0,
    ).select_related('user', 'event_day', 'event_day__event', 'event_day__event__dobro_ru_shared_link')
    if not show_logged:
        parts_qs = parts_qs.filter(dobro_ru_logged=False)

    users = {}
    events = {}
    links = {}
    hours = {}
    flat = []

    # Наличие заявки этого человека на это меро (для чекбокса на странице 3).
    applied = set(
        Application.objects.filter(event__in=events_qs, user__isnull=False)
        .values_list('user_id', 'event_id')
    )

    for p in parts_qs:
        event = p.event_day.event
        uid, eid = p.user_id, event.id

        if event.dobro_ru_link_kind == 'unique':
            link_key = f'event:{eid}'
            link_url = event.dobro_ru_link or '—'
            link_title = event.title
        else:  # shared
            shared = event.dobro_ru_shared_link
            link_key = f'shared:{shared.id}' if shared else 'shared:none'
            link_url = shared.url if shared else '—'
            link_title = shared.title if shared else 'Общая ссылка (не задана)'

        users.setdefault(uid, {'user_id': uid, 'name': p.user.full_name, 'telegram': p.user.telegram_username or ''})
        events.setdefault(eid, {
            'event_id': eid, 'title': event.title, 'url': event.dobro_ru_link or link_url,
            'link_key': link_key, 'link_title': link_title, 'kind': event.dobro_ru_link_kind,
        })
        link = links.setdefault(link_key, {'title': link_title, 'url': link_url, 'kind': event.dobro_ru_link_kind, 'event_ids': set()})
        link['event_ids'].add(eid)

        hours[(uid, eid)] = hours.get((uid, eid), 0) + p.hours
        flat.append({
            'event': event.title, 'event_url': event.dobro_ru_link or link_url,
            'user': p.user.full_name, 'hours': p.hours, 'logged': p.dobro_ru_logged,
            'applied': (uid, eid) in applied,
        })

    users_sorted = sorted(users.values(), key=lambda u: u['name'].lower())
    events_sorted = sorted(events.values(), key=lambda e: e['title'].lower())
    return {
        'users': users_sorted,
        'events': events_sorted,
        'links': links,
        'hours': hours,
        'flat': flat,
    }


def build_dobro_workbook(date_from, date_to, event_ids, show_logged=False):
    """Книга простановки часов на Добро.ру — 4 листа (reports_template.md,
    «Отчёт простановки часов на Добро.ру»):
      1. Матрица «человек × ссылка» (ссылко-ориентированная): в шапке колонки —
         ссылка + через запятую все меро под ней; на пересечении — сумма часов
         человека по всем меро этой ссылки. Колонки «часов в сумме»/«меро в сумме» —
         формулами СУММ/СЧЁТ.
      2. Матрица «человек × мероприятие» (меро-ориентированная): одна колонка = одно
         меро + ссылка на него; общая ссылка повторяется на каждом своём меро.
      3. Плоская таблица: меро · ссылка · человек · часы · [проставлено] · [подавал заявку].
      4. Сводка.
    """
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    data = dobro_matrix_data(date_from, date_to, event_ids, show_logged)
    users = data['users']
    events = data['events']
    links = data['links']
    hours = data['hours']

    wb = Workbook()

    # ---- Лист 1: человек × ссылка (ссылко-ориентированный) ----
    ws1 = wb.active
    ws1.title = '1. По ссылкам'
    link_items = sorted(links.items(), key=lambda kv: kv[1]['title'].lower())
    # Заголовок: ФИО | часов в сумме | меро в сумме | <ссылка: меро1, меро2, ...> ...
    header = ['ФИО', 'Часов в сумме', 'Мероприятий в сумме']
    for _, link in link_items:
        titles = ', '.join(e['title'] for e in events if e['event_id'] in link['event_ids'])
        header.append(f"{link['url']}\n({titles})")
    ws1.append(header)

    first_link_col = 4  # D
    last_link_col = first_link_col + len(link_items) - 1
    for ui, u in enumerate(users):
        row_excel = ui + 2
        row = [u['name'], None, None]
        for _, link in link_items:
            total = sum(hours.get((u['user_id'], eid), 0) for eid in link['event_ids'])
            row.append(total or None)
        ws1.append(row)
        if link_items:
            rng = f"{get_column_letter(first_link_col)}{row_excel}:{get_column_letter(last_link_col)}{row_excel}"
            ws1.cell(row=row_excel, column=2).value = f"=SUM({rng})"
            ws1.cell(row=row_excel, column=3).value = f"=COUNT({rng})"

    # ---- Лист 2: человек × мероприятие (меро-ориентированный) ----
    ws2 = wb.create_sheet('2. По мероприятиям')
    header2 = ['ФИО', 'Часов в сумме', 'Мероприятий в сумме']
    for e in events:
        header2.append(f"{e['title']}\n{e['url']}")
    ws2.append(header2)
    last_ev_col = first_link_col + len(events) - 1
    for ui, u in enumerate(users):
        row_excel = ui + 2
        row = [u['name'], None, None]
        for e in events:
            row.append(hours.get((u['user_id'], e['event_id'])) or None)
        ws2.append(row)
        if events:
            rng = f"{get_column_letter(first_link_col)}{row_excel}:{get_column_letter(last_ev_col)}{row_excel}"
            ws2.cell(row=row_excel, column=2).value = f"=SUM({rng})"
            ws2.cell(row=row_excel, column=3).value = f"=COUNT({rng})"

    # ---- Лист 3: плоская таблица с чекбоксом «Проставлено» ----
    # «Проставлено» — булев чекбокс: значение ячейки ИСТИНА/ЛОЖЬ (кликается, сортируется),
    # а выпадающий список Excel (data validation) ограничивает ввод TRUE/FALSE — менеджер
    # кликает ячейку и переключает галочку прямо в файле.
    from openpyxl.worksheet.datavalidation import DataValidation

    ws3 = wb.create_sheet('3. Список')
    ws3.append(['Мероприятие', 'Ссылка на меро', 'ФИО', 'Часы', 'Проставлено'])
    flat_sorted = sorted(data['flat'], key=lambda x: (x['event'].lower(), x['user'].lower()))
    for r in flat_sorted:
        ws3.append([
            r['event'], r['event_url'], r['user'], r['hours'],
            bool(r['logged']),
        ])
    if flat_sorted:
        checkbox_col = 'E'
        dv = DataValidation(type='list', formula1='"TRUE,FALSE"', allow_blank=False)
        dv.add(f'{checkbox_col}2:{checkbox_col}{len(flat_sorted) + 1}')
        ws3.add_data_validation(dv)

    # ---- Лист 4: сводка ----
    ws4 = wb.create_sheet('4. Сводка')
    ws4.append(['Показатель', 'Значение'])
    ws4.append(['Человек в отчёте', len(users)])
    ws4.append(['Мероприятий в отчёте', len(events)])
    ws4.append(['Ссылок Добро.ру', len(links)])
    ws4.append([])
    ws4.append(['Мероприятие', 'Людей на мероприятии'])
    for e in events:
        people = sum(1 for u in users if (u['user_id'], e['event_id']) in hours)
        ws4.append([e['title'], people])

    return wb
