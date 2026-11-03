"""Вьюхи домена «reports». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


def _report_period_range(request):
    """Диапазон дат для отчёта: пресет (`period`) или произвольный диапазон
    (`date_from`/`date_to` — brandbook §6.3, date range picker, стиль Booking.com)."""
    today = timezone.localdate()

    raw_from = request.GET.get('date_from')
    raw_to = request.GET.get('date_to')
    if raw_from and raw_to:
        try:
            date_from = datetime.date.fromisoformat(raw_from)
            date_to = datetime.date.fromisoformat(raw_to)
            if date_from <= date_to:
                return 'custom', date_from, date_to
        except ValueError:
            pass

    period = request.GET.get('period', 'season')
    if period == 'yesterday':
        date_from = date_to = today - datetime.timedelta(days=1)
        return period, date_from, date_to
    if period == 'today':
        return period, today, today
    if period == 'week':
        return period, today - datetime.timedelta(days=7), today
    if period == 'month':
        return period, today - datetime.timedelta(days=30), today
    from data_base import data_controller as dc
    if period == 'season':
        current = dc.seasons_qs().filter(start_season__lte=today).order_by('-start_season').first()
        if current:
            return period, current.start_season, current.end_season or today
        return period, today - datetime.timedelta(days=120), today
    if period == 'last_season':
        current = dc.seasons_qs().filter(start_season__lte=today).order_by('-start_season').first()
        previous_qs = dc.seasons_qs().order_by('-start_season')
        if current:
            previous_qs = previous_qs.filter(start_season__lt=current.start_season)
        previous = previous_qs.first()
        if previous:
            return period, previous.start_season, previous.end_season or (current.start_season - datetime.timedelta(days=1) if current else today)
        return period, today - datetime.timedelta(days=240), today - datetime.timedelta(days=120)

    # Фоллбэк, если сезонов в базе ещё нет вовсе.
    period = 'season'
    return period, today - datetime.timedelta(days=120), today

def _report_scope(request):
    """Охват отчёта — два взаимоисключающих режима (reports_template.md «Выбор охвата»):
    `scope=events` + `event_ids=1,2,3` — по явному списку мероприятий (даты игнорируются),
    иначе — по периоду через `_report_period_range`. Возвращает
    (scope_mode, period, date_from, date_to, event_ids).

    Оставлено для генераторов экспорта (report_*_export), которые ходят по старой схеме
    `?scope=events&event_ids=…`. Экранный ERP-дашборд использует `_report_erp_scope`."""
    raw_event_ids = request.GET.get('event_ids', '').strip()
    if request.GET.get('scope') == 'events' and raw_event_ids:
        event_ids = [int(x) for x in raw_event_ids.split(',') if x.strip().isdigit()]
        if event_ids:
            return 'events', None, None, None, event_ids

    period, date_from, date_to = _report_period_range(request)
    return 'period', period, date_from, date_to, None

def _parse_int_csv(raw):
    return [int(x) for x in (raw or '').split(',') if x.strip().lstrip('-').isdigit()]

def _report_erp_scope(request):
    """Охват ERP-дашборда «Отчёты»: диапазон дат + статус-режим пула меро
    (all/ongoing/past) + список УБРАННЫХ пользователем меро (`exclude`). Пул строится от
    дат, из него исключаются `exclude` — так ссылка компактна (даты+исключения), переживает
    появление новых меро и совпадает с механикой чипов-«убирания» на странице.

    Возвращает dict: period, date_from, date_to, event_status, exclude_ids, event_ids
    (итоговый охват — id меро пула минус исключённые)."""
    period, date_from, date_to = _report_period_range(request)
    event_status = request.GET.get('event_status', 'all')
    if event_status not in reports_service.EVENT_SCOPE_MODES:
        event_status = 'all'
    exclude_ids = _parse_int_csv(request.GET.get('exclude'))
    event_ids = reports_service.events_pool(date_from, date_to, event_status, exclude_ids)
    return {
        'period': period,
        'date_from': date_from,
        'date_to': date_to,
        'event_status': event_status,
        'exclude_ids': exclude_ids,
        'event_ids': event_ids,
    }

REPORT_VIEWS = [
    {'key': 'dashboard', 'icon': '📊', 'title': 'Дашборд', 'desc': 'Ключевые показатели и графики за охват'},
    {'key': 'tables', 'icon': '🗂️', 'title': 'Таблицы', 'desc': 'Детальные списки: волонтёры, меро, набор, персонал'},
    {'key': 'dobro', 'icon': '❤️', 'title': 'Добро.ру', 'desc': 'Простановка часов и выгрузка отчёта'},
]

REPORT_TABLES = [
    {'key': 'volunteers', 'title': 'Волонтёры'},
    {'key': 'events', 'title': 'Мероприятия'},
    {'key': 'teamleaders', 'title': 'Тим-лидеры'},
    {'key': 'managers', 'title': 'Менеджеры'},
    {'key': 'applications', 'title': 'Заявки'},
]

def _report_event_chips(date_from, date_to, event_status, exclude_ids):
    """Данные для чипов охвата (выбор/убирание мероприятий, как чипы категорий): весь пул
    периода данного статус-режима, с флагом excluded по каждому. Пользователь «убирает»
    ненужные — их id уходят в ?exclude=."""
    from data_base import data_controller as dc
    exclude_set = set(exclude_ids or [])
    pool_all = reports_service.events_pool(date_from, date_to, event_status, exclude_ids=None)
    chips = []
    for event in dc.events_qs().filter(id__in=pool_all).prefetch_related('shifts'):
        first_day = event.shifts.order_by('day').values_list('day', flat=True).first()
        chips.append({
            'id': event.id,
            'title': event.title,
            'date': first_day.strftime('%d.%m.%Y') if first_day else None,
            'excluded': event.id in exclude_set,
        })
    # Свежие сверху (по первой смене).
    chips.sort(key=lambda c: c['date'] or '', reverse=True)
    return chips

@manager_required
def report_period(request):
    """ERP-хаб «Отчёты». GET без ?partial=1 — шелл (переключатель режимов + строка охвата,
    панель подгружается AJAX'ом). GET с ?partial=1&view=… — partial активного режима."""
    view_key = request.GET.get('view', 'dashboard')
    if view_key not in {v['key'] for v in REPORT_VIEWS}:
        view_key = 'dashboard'
    scope = _report_erp_scope(request)
    wants_partial = request.GET.get('partial') == '1' or is_ajax(request)

    # Смена охвата (даты/статус/исключения) обновляет весь блок «строка охвата»
    # AJAX'ом целиком (пресеты/лейбл диапазона/статус-режим/чипы) — сервер остаётся
    # единственным источником истины для того, какая кнопка активна и что показано
    # в лейбле диапазона; раньше окно перезагружалось целиком, и браузер прыгал
    # наверх. Панель режима обновляется отдельным запросом тем же fetch'ем.
    if request.GET.get('scope_partial') == '1':
        chips = _report_event_chips(scope['date_from'], scope['date_to'], scope['event_status'], scope['exclude_ids'])
        return render(request, 'blog/partials/_report_scope.html', {
            'period': scope['period'],
            'date_from': scope['date_from'],
            'date_to': scope['date_to'],
            'event_status': scope['event_status'],
            'event_chips': chips,
        })

    if wants_partial:
        return _report_render_panel(request, view_key, scope)

    # Шелл: строка охвата (даты/статус-режим/чипы) + переключатель режимов.
    chips = _report_event_chips(scope['date_from'], scope['date_to'], scope['event_status'], scope['exclude_ids'])
    return render(request, 'blog/report_period.html', {
        'views': REPORT_VIEWS,
        'active_view': view_key,
        'period': scope['period'],
        'date_from': scope['date_from'],
        'date_to': scope['date_to'],
        'event_status': scope['event_status'],
        'exclude_ids': scope['exclude_ids'],
        'event_chips': chips,
    })

def _report_scope_querystring(scope, extra=None):
    """Собрать query-string охвата (даты/статус/исключения) для ссылок экспорта и
    AJAX-подгрузок панелей — чтобы панель считалась по тому же охвату, что на экране."""
    from urllib.parse import urlencode
    params = {
        'date_from': scope['date_from'].isoformat(),
        'date_to': scope['date_to'].isoformat(),
        'event_status': scope['event_status'],
    }
    if scope['exclude_ids']:
        params['exclude'] = ','.join(str(i) for i in scope['exclude_ids'])
    if extra:
        params.update(extra)
    return urlencode(params)

def _report_render_panel(request, view_key, scope):
    """Рендер partial активного режима хаба (дашборд/таблицы/добро)."""
    if view_key == 'dobro':
        return _report_dobro_panel(request, scope)
    if view_key == 'tables':
        return _report_tables_panel(request, scope)
    return _report_dashboard_panel(request, scope)

def _report_dashboard_panel(request, scope):
    """Панель «Дашборд»: KPI-плитки + графики (набор по меро, явка-бублик, топ волонтёров,
    оценки). Воронка/динамика/категории убраны из UI, поэтому не считаем (dynamics больше
    не нужен). Считаем только то, что показывается на экране."""
    event_ids = scope['event_ids']
    date_from, date_to = scope['date_from'], scope['date_to']
    data = reports_service.period_report(date_from, date_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    return render(request, 'blog/partials/_report_dashboard.html', {
        'report': data,
        'efficiency': efficiency,
        'scope_qs': _report_scope_querystring(scope),
        'event_count': len(event_ids),
    })

def _report_tables_panel(request, scope):
    """Панель «Таблицы» (ERP): под-выбор таблицы + сама таблица. Каждая таблица считает
    только свою функцию (ленивость), выбор таблицы — в ?table=."""
    table_key = request.GET.get('table', 'volunteers')
    if table_key not in {t['key'] for t in REPORT_TABLES}:
        table_key = 'volunteers'
    event_ids = scope['event_ids']
    date_from, date_to = scope['date_from'], scope['date_to']

    context = {
        'tables': REPORT_TABLES,
        'active_table': table_key,
        'scope_qs': _report_scope_querystring(scope),
        'event_count': len(event_ids),
    }
    if table_key == 'volunteers':
        context['rows'] = reports_service.volunteers_table(date_from, date_to, event_ids=event_ids)
    elif table_key == 'events':
        rows, max_shifts = reports_service.events_table(date_from, date_to, event_ids=event_ids)
        # Дополняем список смен до max_shifts пустыми ячейками — шаблон тогда просто
        # итерирует по row.shift_cells и рисует ровно N колонок «Смена k» у всех строк.
        for r in rows:
            r['shift_cells'] = list(r['shift_cells']) + ['—'] * (max_shifts - len(r['shift_cells']))
        context['rows'] = rows
        context['shift_columns'] = range(1, max_shifts + 1)
    elif table_key == 'teamleaders':
        context['rows'] = reports_service.team_leaders_table(date_from, date_to, event_ids=event_ids)
    elif table_key == 'managers':
        context['rows'] = reports_service.managers_table(date_from, date_to, event_ids=event_ids)
    elif table_key == 'applications':
        context['rows'] = reports_service.applications_table(date_from, date_to, event_ids=event_ids)
    return render(request, 'blog/partials/_report_tables.html', context)

def _report_dobro_panel(request, scope):
    """Панель «Добро.ру»: перенос страницы dobro_page — таблица ссылок с чекбоксом
    «часы проставлены» (переключается AJAX'ом) + кнопка выгрузки отчёта.

    Фильтруется тем же охватом (event_ids), что дашборд/таблицы — раньше показывала
    вообще все ссылки/меро в системе независимо от выбранного периода/исключений.

    Дополнительные фильтры хедера: ?only_unlogged=1 (часы не проставлены) и
    ?has_link=yes|no (есть/нет URL у ссылки)."""
    only_unlogged = request.GET.get('only_unlogged') == '1'
    has_link = request.GET.get('has_link')  # 'yes' | 'no' | None
    if has_link not in ('yes', 'no'):
        has_link = None
    rows, unlogged_event_ids = _dobro_rows(
        only_unlogged=only_unlogged, event_ids=scope['event_ids'], has_link=has_link,
    )
    return render(request, 'blog/partials/_report_dobro.html', {
        'rows': rows,
        'only_unlogged': only_unlogged,
        'has_link': has_link,
        'unlogged_event_ids': unlogged_event_ids,
        'scope_qs': _report_scope_querystring(scope),
    })

@manager_required
def report_events_search(request):
    """Поиск мероприятий для модалки выбора охвата «по мероприятиям» (reports_template.md).
    Полный список без поиска теперь грузится сразу со страницей (report_period,
    recent_events_json) — этот эндпоинт используется только при вводе текста в поиск."""
    from data_base import data_controller as dc
    query = request.GET.get('q', '').strip()
    events = dc.events_qs().order_by('-created_at')
    if query:
        events = events.filter(title__icontains=query)

    def _brief(event):
        day = event.shifts.order_by('day').values_list('day', flat=True).first()
        return {
            'id': event.id, 'title': event.title,
            'date': day.strftime('%d.%m.%Y') if day else None,
            'dobro_unlogged': event.dobro_ru_link_kind != 'none' and not event.dobro_ru_hours_logged,
        }

    return JsonResponse({'events': [_brief(e) for e in events]})

def _xlsx_response(workbook, filename):
    from django.http import HttpResponse
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response

@manager_required
def report_period_export(request):
    """Excel-отчёт за охват (.xlsx): по листу на каждую экранную таблицу ERP-раздела
    (Волонтёры / Мероприятия / Тим-лидеры / Менеджеры / Заявки). Охват — тот же, что на
    экране (даты + статус-режим + убранные меро), поэтому парсим ERP-охват."""
    scope = _report_erp_scope(request)
    wb = report_exports.build_period_workbook(
        scope['date_from'], scope['date_to'], scope['event_ids'],
        scope_mode='events', compare_mode='adjacent',
    )
    filename = f"report_{scope['date_from']}_{scope['date_to']}.xlsx"
    return _xlsx_response(wb, filename)

@manager_required
def report_period_pdf(request, variant):
    """PDF-отчёт за охват (reports_template.md, «Отчёт за период (общий)»).
    variant='external' — обезличенный (для руководства), 'internal' — с именами
    и операционными данными (нагрузка персонала, retention/churn, проблемные зоны)."""
    if variant not in ('external', 'internal'):
        raise PermissionDenied('Неизвестная вариация отчёта.')

    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    compare_mode = request.GET.get('compare', 'adjacent')
    if compare_mode not in ('adjacent', 'year_ago'):
        compare_mode = 'adjacent'

    prev_from = prev_to = None
    if scope_mode == 'period':
        prev_from, prev_to = reports_service.previous_period_range(date_from, date_to, compare_mode)

    data = reports_service.period_report(date_from, date_to, prev_from, prev_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    timing = reports_service.application_timing(date_from, date_to, event_ids=event_ids)
    post_timing = reports_service.post_publication_timing(date_from, date_to, event_ids=event_ids)
    weekly = reports_service.weekly_dynamics(date_from, date_to, event_ids=event_ids)

    context = {
        'variant': variant,
        'is_internal': variant == 'internal',
        'scope_mode': scope_mode,
        'date_from': date_from,
        'date_to': date_to,
        'compare_mode': compare_mode,
        'generated_at': timezone.now(),
        'report': data,
        'efficiency': efficiency,
        'timing': timing,
        'post_timing': post_timing,
    }
    if variant == 'internal':
        context['staff'] = reports_service.staff_load(date_from, date_to, event_ids=event_ids)

    if data['category_breakdown']:
        context['category_chart'] = charts_service.bar_chart(
            [c['name'] or 'Без категории' for c in data['category_breakdown']],
            [c['volunteers'] for c in data['category_breakdown']],
            title='Распределение по категориям', ylabel='Волонтёров',
        )
    context['funnel_chart'] = charts_service.funnel_chart([
        ('Подано', data['funnel']['submitted']),
        ('Одобрено', data['funnel']['approved']),
        ('Явка', data['funnel']['attended']),
        ('Неявка без предупр.', data['funnel']['unexcused']),
    ])
    if weekly:
        context['weekly_chart'] = charts_service.bar_chart(
            [w['from'].strftime('%d.%m') for w in weekly], [w['hours'] for w in weekly],
            title='Динамика по неделям', ylabel='Часы',
        )
    if timing['density']:
        context['timing_chart'] = charts_service.bar_chart(
            [d['label'] for d in timing['density']], [d['count'] for d in timing['density']],
            title='Отклик на мероприятие', ylabel='Заявок',
        )
    if variant == 'internal':
        context['churn_chart'] = charts_service.histogram_chart(
            [b['label'] for b in data['churn_histogram']], [b['count'] for b in data['churn_histogram']],
            title='Распределение churn_score',
        )

    builder = report_builders_service.build_period_report(context)
    return docx_response(builder, f'period_report_{variant}.docx')

@manager_required
def report_event_export(request, event_id):
    """Excel-отчёт по одному мероприятию (reports_template.md §4)."""
    event = get_object_or_404(Event, pk=event_id)
    wb = report_exports.build_event_workbook(event.id)
    return _xlsx_response(wb, f"event_{event.id}_report.xlsx")

@manager_required
def report_event_pdf(request, event_id):
    """PDF-отчёт по одному мероприятию (reports_template.md §4), включая график
    «Жизнь мероприятия» (события меро засечками + заявки точками, кластеризация)."""
    event = get_object_or_404(Event, pk=event_id)
    rep = report_exports.event_report(event.id)
    rep['generated_at'] = timezone.now()

    timeline = event_timeline_service.event_timeline_data(event)
    rep['timeline_chart'] = charts_service.event_timeline_chart(
        timeline['milestones'], timeline['applications']
    )
    builder = report_builders_service.build_event_report(rep)
    return docx_response(builder, f'event_{event.id}_report.docx')

def _person_report_context(user_id, date_from, date_to):
    rep = person_report_service.person_report(user_id, date_from, date_to)
    charts = {}
    if rep['scope']['scoped'] and rep['participations']:
        by_month = {}
        for p in rep['participations']:
            key = p['day'].strftime('%Y-%m') if p['day'] else '—'
            by_month[key] = by_month.get(key, 0) + (p['hours'] or 0)
        months = sorted(by_month.keys())
        charts['activity_chart'] = charts_service.bar_chart(
            months, [by_month[m] for m in months], title='Часы по месяцам', ylabel='Часы',
        )
    if rep['internal']['churn_history']:
        seasons = [h.season.start_season.strftime('%d.%m.%Y') for h in rep['internal']['churn_history']]
        scores = [h.churn_score for h in rep['internal']['churn_history']]
        charts['churn_chart'] = charts_service.line_chart(
            seasons, scores, title='Churn по сезонам', ylabel='Churn score',
        )
    rep.update(charts)
    return rep

@manager_required
def report_person_pdf(request, user_id):
    """PDF-отчёт по человеку (reports_template.md «Отчёт по человеку»): блоки A-D
    у всех, E/F добавляются автоматически при наличии активной роли ТЛ/менеджера.
    Охват — «за всё время» (без параметров) либо «за период» (date_from/date_to)."""
    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    rep = _person_report_context(user_id, date_from, date_to)
    context = {
        'rep': rep,
        'user': rep['user'],
        'scope': rep['scope'],
        'generated_at': timezone.now(),
    }
    builder = report_builders_service.build_person_report(rep)
    return docx_response(builder, f'person_{user_id}_report.docx')

@manager_required
def report_volunteers_pdf(request):
    """PDF-отчёт по волонтёрам: сводка сверху + карточки подряд по алфавиту
    (reports_template.md «Отчёт по волонтёрам»). Охват — всё время/период,
    выборка — по умолчанию все с хотя бы одной заявкой, либо явный список ?user_ids=."""
    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    raw_ids = request.GET.get('user_ids', '').strip()
    user_ids = [int(x) for x in raw_ids.split(',') if x.strip().isdigit()] if raw_ids else None

    rep = volunteers_report_service.volunteers_report(date_from, date_to, user_ids=user_ids)
    if rep['hours_distribution']:
        rep['hours_hist_chart'] = charts_service.histogram_chart(
            [str(i) for i in range(len(rep['hours_distribution']))],
            sorted(rep['hours_distribution'], reverse=True),
            title='Распределение часов волонтёров (по убыванию)',
        )
    if rep['top_volunteers']:
        rep['top_chart'] = charts_service.funnel_chart(
            [(f"{v['user'].full_name}", v['hours'] or 0) for v in rep['top_volunteers']],
            title='Топ-10 волонтёров по часам',
        )
    rep['churn_chart'] = charts_service.histogram_chart(
        [b['label'] for b in rep['churn_histogram']],
        [b['count'] for b in rep['churn_histogram']],
        title='Распределение churn_score',
    )
    rep['generated_at'] = timezone.now()
    builder = report_builders_service.build_volunteers_report(rep)
    return docx_response(builder, 'volunteers_report.docx')

@manager_required
def report_volunteers_export(request):
    """Excel-отчёт по волонтёрам: лист «Сводка» + лист «Волонтёры» + лист «Участия»."""
    from openpyxl import Workbook

    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    rep = volunteers_report_service.volunteers_report(date_from, date_to)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Сводка'
    ws.append(['Показатель', 'Значение'])
    for key, label in [
        ('total_volunteers', 'Всего волонтёров'), ('total_hours', 'Суммарно часов'),
        ('total_events', 'Суммарно участий'), ('avg_hours', 'Ср. часов на волонтёра'),
        ('new_count', 'Новых за охват'), ('star_count', 'Со звёздочкой ПГАС'),
        ('blacklisted_count', 'В блэклисте'), ('at_risk_count', 'На грани блэклиста'),
    ]:
        ws.append([label, rep['summary'][key]])

    ws_v = wb.create_sheet('Волонтёры')
    ws_v.append(['ФИО', 'Telegram', 'Телефон', 'Часов', 'Мероприятий', 'Заявок', 'Конверсия %', 'Churn', 'Статус'])
    for card in rep['cards']:
        u = card['user']
        stats = card['stats']
        ws_v.append([
            u.full_name, u.telegram_username or '—', u.phone or '—',
            stats['scoped_hours'] if rep['scope']['scoped'] else stats['total_hours'],
            stats['scoped_events'] if rep['scope']['scoped'] else stats['total_events'],
            card['applications_summary']['total'], card['applications_summary']['conversion_pct'],
            round(u.churn_score or 0, 2), u.get_status_display(),
        ])

    ws_p = wb.create_sheet('Участия')
    ws_p.append(['Волонтёр', 'Мероприятие', 'Дата', 'Статус', 'Часы'])
    for card in rep['cards']:
        u = card['user']
        for p in card['participations']:
            ws_p.append([u.full_name, p['event'], p['day'].isoformat() if p['day'] else '—', p['status'], p['hours']])

    return _xlsx_response(wb, 'volunteers_report.xlsx')

@manager_required
def report_organization_pdf(request, org_id):
    """PDF-отчёт по организации (reports_template.md «Отчёт по организации»):
    профиль, контакты, статистика, все мероприятия подряд, история взаимодействия."""
    date_from = date_to = None
    raw_from, raw_to = request.GET.get('date_from'), request.GET.get('date_to')
    if raw_from and raw_to:
        date_from = datetime.date.fromisoformat(raw_from)
        date_to = datetime.date.fromisoformat(raw_to)

    rep = organization_report_service.organization_report(org_id, date_from, date_to)
    if rep['categories_breakdown']:
        rep['categories_chart'] = charts_service.bar_chart(
            [c[0] for c in rep['categories_breakdown']], [c[1] for c in rep['categories_breakdown']],
            title='Мероприятия по категориям',
        )
    rep['generated_at'] = timezone.now()
    builder = report_builders_service.build_organization_report(rep)
    return docx_response(builder, f'organization_{org_id}_report.docx')

@manager_required
def report_people_search(request):
    """Поиск человека для карточки выбора отчёта «по человеку» (по ФИО/username)."""
    from data_base import data_controller as dc
    query = request.GET.get('q', '').strip()
    users = dc.users_qs()
    if query:
        users = users.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
            | Q(telegram_username__icontains=query)
        )
    users = users.order_by('last_name', 'first_name')[:30]
    return JsonResponse({'users': [
        {'id': u.id, 'name': u.full_name, 'telegram': u.telegram_username or ''} for u in users
    ]})

@manager_required
def report_organizations_search(request):
    """Поиск организации для карточки выбора отчёта «по организации»."""
    from data_base import data_controller as dc
    query = request.GET.get('q', '').strip()
    orgs = sorted(dc.get_organizations(name_filter=query or None), key=lambda o: o.name)[:30]
    return JsonResponse({'organizations': [{'id': o.id, 'name': o.name} for o in orgs]})

@manager_required
def report_complex_pdf(request):
    """Комплексный отчёт за период (PDF-пакет, reports_template.md): часть 1 —
    сводная аналитика (переиспользует данные report_period_pdf/internal), часть 2 —
    все мероприятия периода подряд с таймлайнами, часть 3 — таблица работы с
    заявками за период, часть 4 — карточки волонтёров периода подряд по алфавиту."""
    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    compare_mode = request.GET.get('compare', 'adjacent')
    if compare_mode not in ('adjacent', 'year_ago'):
        compare_mode = 'adjacent'

    prev_from = prev_to = None
    if scope_mode == 'period':
        prev_from, prev_to = reports_service.previous_period_range(date_from, date_to, compare_mode)

    data = reports_service.period_report(date_from, date_to, prev_from, prev_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    staff = reports_service.staff_load(date_from, date_to, event_ids=event_ids)
    timing = reports_service.application_timing(date_from, date_to, event_ids=event_ids)
    post_timing = reports_service.post_publication_timing(date_from, date_to, event_ids=event_ids)
    weekly = reports_service.weekly_dynamics(date_from, date_to, event_ids=event_ids)

    events_scope = reports_service._events_in_scope(date_from, date_to, event_ids)
    events_reports = []
    for event in events_scope.order_by('shifts__day').distinct():
        rep = report_exports.event_report(event.id)
        timeline = event_timeline_service.event_timeline_data(event)
        rep['timeline_chart'] = charts_service.event_timeline_chart(
            timeline['milestones'], timeline['applications']
        )
        events_reports.append(rep)

    applications_rows = report_exports.applications_rows(date_from, date_to, event_ids)
    lags = [
        (row['assigned_at'] - row['created_at']).total_seconds() / 3600
        for row in applications_rows if row.get('assigned_at') and row.get('created_at')
    ]
    applications_summary = {
        'total': len(applications_rows),
        'approved': sum(1 for r in applications_rows if r['status'] == 'Одобрена'),
        'rejected': sum(1 for r in applications_rows if r['status'] == 'Отклонена/резерв'),
        'new': sum(1 for r in applications_rows if r['status'] == 'Новая'),
        'avg_lag_hours': round(sum(lags) / len(lags), 1) if lags else None,
    }

    volunteers = volunteers_report_service.volunteers_report(date_from, date_to, user_ids=None)

    context = {
        'scope_mode': scope_mode,
        'date_from': date_from,
        'date_to': date_to,
        'generated_at': timezone.now(),
        'report': data,
        'efficiency': efficiency,
        'staff': staff,
        'timing': timing,
        'post_timing': post_timing,
        'weekly': weekly,
        'events_reports': events_reports,
        'applications_rows': applications_rows,
        'applications_summary': applications_summary,
        'volunteers': volunteers,
    }
    builder = report_builders_service.build_complex_report(context)
    return docx_response(builder, 'complex_report.docx')

@manager_required
def dobro_page(request):
    """Страница «Добро.ру»: все ссылки Добро.ру таблицей — общие (DobroRuSharedLink) и
    уникальные (заданные прямо у мероприятия), их тип, к каким мероприятиям привязана
    ссылка (чипами сбоку) и статус простановки часов (выставлены/нет) по каждому меро.

    Мероприятия с типом учёта 'none' в таблицу не попадают (часы не ведём).

    Фильтр `?only_unlogged=1` оставляет только ссылки, по которым часы ещё НЕ полностью
    проставлены (есть хотя бы одно незакрытое меро)."""
    # Добро.ру переехало во вкладку ERP-хаба «Отчёты» (?view=dobro). Прямой заход на
    # /dobro/ редиректим туда, чтобы не держать вторую копию страницы.
    return redirect(reverse('report_period') + '?view=dobro')

@manager_required
def report_dobro_toggle(request, event_id):
    """AJAX-переключение «часы на Добро.ру проставлены» из таблицы Добро.ру внутри
    ERP-хаба (галочка в строке). Те же инварианты, что у event_dobro_toggle (только
    завершённые меро с ведением учёта), но ответ — JSON для обновления галочки без
    перезагрузки панели."""
    event = get_object_or_404(Event, pk=event_id)
    if request.method != 'POST':
        return JsonResponse({'error': 'method'}, status=405)
    if event.event_status != 'finished':
        return JsonResponse({'error': 'Статус доступен только после завершения мероприятия.'}, status=400)
    if event.dobro_ru_link_kind == 'none':
        return JsonResponse({'error': 'У мероприятия учёт часов на Добро.ру не ведётся.'}, status=400)
    event.dobro_ru_hours_logged = not event.dobro_ru_hours_logged
    event.dobro_ru_logged_by = request.user if event.dobro_ru_hours_logged else None
    event.save(update_fields=['dobro_ru_hours_logged', 'dobro_ru_logged_by'])
    return JsonResponse({'logged': event.dobro_ru_hours_logged})

@manager_required
def report_dobro_set_link(request, event_id):
    """AJAX: задать/изменить уникальную ссылку Добро.ру мероприятию прямо из таблицы
    Добро.ру (двойной клик по ячейке «нет ссылки» → модалка ввода URL). Ставит
    dobro_ru_link_kind='unique' и dobro_ru_link=<url>. Пустой URL — снимает ссылку
    (kind='none'). Общие (shared) ссылки отсюда не трогаем — их источник DobroRuSharedLink,
    менять её здесь было бы неожиданно (она общая на несколько меро)."""
    event = get_object_or_404(Event, pk=event_id)
    if request.method != 'POST':
        return JsonResponse({'error': 'method'}, status=405)
    if event.dobro_ru_link_kind == 'shared':
        return JsonResponse({'error': 'У мероприятия общая ссылка Добро.ру — измените её в справочнике общих ссылок.'}, status=400)
    url = (request.POST.get('url') or '').strip()
    if url:
        # Мягкая валидация: ждём http(s)-ссылку.
        validator = URLValidator()
        try:
            validator(url)
        except ValidationError:
            return JsonResponse({'error': 'Введите корректную ссылку (http/https).'}, status=400)
        event.dobro_ru_link = url
        event.dobro_ru_link_kind = 'unique'
    else:
        event.dobro_ru_link = None
        event.dobro_ru_link_kind = 'none'
        event.dobro_ru_hours_logged = False
    event.save(update_fields=['dobro_ru_link', 'dobro_ru_link_kind', 'dobro_ru_hours_logged'])
    return JsonResponse({'url': event.dobro_ru_link or '', 'kind': event.dobro_ru_link_kind})

def _dobro_rows(only_unlogged=False, event_ids=None, has_link=None):
    """Строки таблицы Добро.ру — ПО ОДНОМУ МЕРОПРИЯТИЮ охвата (не по ссылке): в таблице
    присутствует каждое меро из охвата, даже если у него нет ссылки Добро.ру (тогда в
    колонке «Ссылка» явно пишется «нет ссылки»). Раньше таблица была link-центричной и
    меро без учёта Добро.ру (kind='none') в неё вообще не попадали — из-за чего при
    выбранном периоде таблица выглядела пустой, хотя мероприятия в охвате были.

    Для каждого меро колонка «Ссылка» = его уникальный URL (kind='unique'), либо URL
    общей ссылки (kind='shared'), либо пусто (kind='none'). Чекбокс «часы проставлены»
    доступен только у завершённых меро с ведением учёта (kind != 'none').

    event_ids — охват (даты/статус/исключения). None → все меро (прямой заход).
    has_link — 'yes'|'no'|None (фильтр по наличию URL). only_unlogged — только меро с
    непроставленными часами."""
    from data_base import data_controller as dc
    events = dc.events_qs().select_related('dobro_ru_shared_link').order_by('-created_at')
    if event_ids is not None:
        events = events.filter(id__in=event_ids)

    KIND_DISPLAY = {'none': 'Нет учёта', 'unique': 'Уникальная', 'shared': 'Общая'}
    rows = []
    for event in events:
        if event.dobro_ru_link_kind == 'unique':
            url = event.dobro_ru_link or ''
        elif event.dobro_ru_link_kind == 'shared':
            url = event.dobro_ru_shared_link.url if event.dobro_ru_shared_link else ''
        else:
            url = ''
        tracks_hours = event.dobro_ru_link_kind != 'none'
        rows.append({
            'event': event,
            'title': event.title,
            'url': url,
            'kind': event.dobro_ru_link_kind,
            'kind_display': KIND_DISPLAY.get(event.dobro_ru_link_kind, event.dobro_ru_link_kind),
            'tracks_hours': tracks_hours,
            'logged': event.dobro_ru_hours_logged,
            # Чекбокс доступен только у завершённого меро с ведением учёта.
            'toggle_enabled': tracks_hours and event.event_status == 'finished',
        })

    if only_unlogged:
        # «Не проставленные» = ведём учёт и часы ещё не отмечены.
        rows = [r for r in rows if r['tracks_hours'] and not r['logged']]
    if has_link == 'yes':
        rows = [r for r in rows if r['url'].strip()]
    elif has_link == 'no':
        rows = [r for r in rows if not r['url'].strip()]

    # Для кнопки выгрузки — id завершённых меро с непроставленными часами (отчёт берёт
    # в охват только их).
    unlogged_event_ids = sorted(
        r['event'].id for r in rows
        if r['tracks_hours'] and not r['logged'] and r['event'].event_status == 'finished'
    )
    return rows, unlogged_event_ids

@manager_required
def report_dobro_export(request):
    """Excel-отчёт простановки часов на Добро.ру (reports_template.md §5):
    листы «По ссылке», «По человеку», «Сводка»."""
    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    show_logged = request.GET.get('show_logged') == '1'
    wb = report_exports.build_dobro_workbook(date_from, date_to, event_ids, show_logged)
    return _xlsx_response(wb, "dobro_ru_logging.xlsx")

@manager_required
def report_bundle(request):
    """Комплексный отчёт (reports_template.md §3): ZIP из внешнего DOCX, внутреннего DOCX
    и Excel-книги за охват."""
    import io
    import zipfile
    from django.http import HttpResponse

    scope_mode, period, date_from, date_to, event_ids = _report_scope(request)
    compare_mode = request.GET.get('compare', 'adjacent')
    if compare_mode not in ('adjacent', 'year_ago'):
        compare_mode = 'adjacent'

    prev_from = prev_to = None
    if scope_mode == 'period':
        prev_from, prev_to = reports_service.previous_period_range(date_from, date_to, compare_mode)
    data = reports_service.period_report(date_from, date_to, prev_from, prev_to, event_ids=event_ids)
    efficiency = reports_service.recruitment_efficiency(date_from, date_to, event_ids=event_ids)
    timing = reports_service.application_timing(date_from, date_to, event_ids=event_ids)
    post_timing = reports_service.post_publication_timing(date_from, date_to, event_ids=event_ids)

    base_ctx = {
        'scope_mode': scope_mode, 'date_from': date_from, 'date_to': date_to,
        'compare_mode': compare_mode, 'generated_at': timezone.now(),
        'report': data, 'efficiency': efficiency, 'timing': timing, 'post_timing': post_timing,
    }
    external_docx = report_builders_service.build_period_report({
        **base_ctx, 'variant': 'external', 'is_internal': False,
    }).build_bytes()
    internal_docx = report_builders_service.build_period_report({
        **base_ctx, 'variant': 'internal', 'is_internal': True,
        'staff': reports_service.staff_load(date_from, date_to, event_ids=event_ids),
    }).build_bytes()

    wb = report_exports.build_period_workbook(date_from, date_to, event_ids, scope_mode, compare_mode)
    xlsx_buf = io.BytesIO()
    wb.save(xlsx_buf)

    scope_slug = f'{date_from}_{date_to}' if scope_mode == 'period' else 'events'

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'report_external_{scope_slug}.docx', external_docx)
        zf.writestr(f'report_internal_{scope_slug}.docx', internal_docx)
        zf.writestr(f'report_{scope_slug}.xlsx', xlsx_buf.getvalue())
    zip_buf.seek(0)

    response = HttpResponse(zip_buf.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="report_bundle_{scope_slug}.zip"'
    return response
