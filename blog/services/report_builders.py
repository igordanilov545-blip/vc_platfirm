"""Сборка конкретных отчётов в DOCX (reports_template.md) поверх `DocxBuilder`.

Каждый билдер принимает готовый контекст (те же dict-и, что раньше уходили в
PDF-шаблоны из blog/services/*_report.py и report_exports.py) и возвращает
`DocxBuilder`. Графики — PNG из blog/services/charts.py, вставляются картинками.

Это proof-of-concept: цель — чтобы отчёты формировались и было видно их
содержание, без вылизанной вёрстки.
"""
from blog.services.docx_report import DocxBuilder


def _fmt_dt(value, with_time=True):
    if not value:
        return '—'
    fmt = '%d.%m.%Y %H:%M' if with_time else '%d.%m.%Y'
    try:
        return value.strftime(fmt)
    except AttributeError:
        return str(value)


def _scope_label(scope):
    if scope and scope.get('scoped'):
        return f"период {_fmt_dt(scope['date_from'], False)} — {_fmt_dt(scope['date_to'], False)}"
    return 'всё время'


# ---------------------------------------------------------------------------
# 1. Отчёт по мероприятию
# ---------------------------------------------------------------------------

def build_event_report(rep) -> DocxBuilder:
    b = DocxBuilder()
    event = rep['event']
    b.title('ОТЧЁТ ПО МЕРОПРИЯТИЮ', subtitle=event.title,
            tag=f"Сформирован: {_fmt_dt(rep.get('generated_at'))}")

    b.h2('Шапка')
    b.kv([
        ('Организация', event.organization.name if event.organization else '—'),
        ('Организатор', f"{event.organizer.first_name} {event.organizer.last_name}" if event.organizer else '—'),
        ('Категории', rep['categories']),
        ('Статус', event.get_event_status_display()),
        ('Пост в канале', event.post_in_chanel_link or '—'),
        ('Добро.ру', event.dobro_ru_link or '—'),
        ('Менеджер(ы)', ', '.join(m.full_name for m in rep['managers']) or '—'),
        ('Тим-лидер(ы)', ', '.join(t.full_name for t in rep['team_leads']) or '—'),
    ])

    if rep.get('timeline_chart'):
        b.h2('График «Жизнь мероприятия»')
        b.image_data_uri(rep['timeline_chart'])

    b.h2('Смены')
    for shift in rep['shifts']:
        attended = sum(1 for p in shift['participants'] if p['part_status'] and 'Пришёл' in p['part_status'])
        pct = f" · набрано {len(shift['participants'])}/{shift['needed']}" if shift['needed'] else ''
        b.h3(f"Смена {_fmt_dt(shift['day'], False)} {shift['start_time']}–{shift['end_time']} · "
             f"{shift['location']}{pct}")
        b.table(
            ['Волонтёр', 'Заявка', 'Явка', 'Часы'],
            [[p['name'], p['app_status'], p['part_status'], p['hours']] for p in shift['participants']],
            empty='Участников нет.',
        )

    t = rep['totals']
    b.h2('Итоги')
    b.kv([
        ('Всего заявок', t['submitted']),
        ('Одобрено', t['approved']),
        ('Явка', t['attended']),
        ('% закрытия', f"{t['pct_closed']}%"),
        ('Всего часов', t['total_hours']),
        ('Людей получили помощь', t['people_helped'] if t['people_helped'] is not None else '—'),
        ('Средний рейтинг', f"{t['rating']} ({t['rating_count']} отзывов)" if t['rating'] is not None else '—'),
    ])
    return b


# ---------------------------------------------------------------------------
# 2. Отчёт по человеку (блоки A-F)
# ---------------------------------------------------------------------------

def _append_person_card(b, rep, *, as_section=False):
    """Блоки A-D (+E/F при ролях). as_section=True — заголовок карточки для сводных отчётов."""
    user = rep['user']
    scope = rep['scope']
    scoped = scope['scoped']
    stats = rep['stats']

    if as_section:
        b.h2(f"{user.full_name} (@{user.telegram_username or '—'})")
    else:
        b.title('ОТЧЁТ ПО ЧЕЛОВЕКУ', subtitle=f"{user.full_name} (@{user.telegram_username or '—'})",
                tag=f"Охват: {_scope_label(scope)} · сформирован: {_fmt_dt(rep.get('generated_at'))}")

    # A. Профиль
    b.h3('A. Профиль')
    b.kv([
        ('Контакты', ' · '.join(filter(None, [user.phone, user.email, f'@{user.telegram_username}' if user.telegram_username else None])) or '—'),
        ('Дата регистрации', _fmt_dt(user.created_at, False)),
        ('Статус', user.get_status_display()),
        ('⭐ Звёздочка ПГАС', 'да' if rep['is_star'] else 'нет'),
    ])

    # B. Волонтёрская статистика
    b.h3('B. Волонтёрская статистика')
    b.kv([
        ('Часов (всего / сезон)', f"{stats['total_hours']} / {stats['season_hours']}"),
        ('Часов (охват)', stats['scoped_hours'] if scoped else '— (всё время)'),
        ('Мероприятий (всего / сезон)', f"{stats['total_events']} / {stats['season_events']}"),
        ('Мероприятий (охват)', stats['scoped_events'] if scoped else '— (всё время)'),
        ('Ср. часов на меро', stats['avg_hours_per_event']),
        ('Любимые категории', ', '.join(f"{c['name']} ({c['count']})" for c in rep['top_categories']) or '—'),
    ])
    b.table(
        ['Мероприятие', 'Дата', 'Явка', 'Часы'],
        [[p['event'], _fmt_dt(p['day'], False), p['status'], p['hours']] for p in rep['participations']],
        empty='Участий нет.',
    )

    # C. Заявки
    b.h3('C. Заявки')
    b.table(
        ['Мероприятие', 'Подана', 'Статус', 'Обработана'],
        [[a['event'], _fmt_dt(a['submitted_at']), a['status'], _fmt_dt(a['assigned_at'])] for a in rep['applications']],
        empty='Заявок нет.',
    )
    summ = rep['applications_summary']
    b.kv([('Конверсия заявок', f"{summ['conversion_pct']}% ({summ['approved']}/{summ['total']})")])

    # D. Внутреннее
    internal = rep['internal']
    b.h3('D. Внутреннее')
    b.kv([
        ('Churn score', round(internal['churn_score'] or 0, 2)),
        ('Неявки без предупреждения', internal['unexcused_count']),
        ('Внутренних комментариев', len(internal['comments'])),
        ('Исключений из требований', len(internal['exceptions'])),
    ])
    if internal['comments']:
        b.table(
            ['Автор', 'Дата', 'Комментарий'],
            [[c.author.full_name if c.author else '—', _fmt_dt(c.created_at, False), c.text] for c in internal['comments']],
        )

    # E. Тим-лидер
    if rep.get('team_leader'):
        tl = rep['team_leader']
        b.h3('E. Дополнение тим-лидера')
        b.kv([
            ('Меро как ТЛ (всего / сезон)', f"{tl['total_events']} / {tl['season_events']}"),
            ('Дата назначения', _fmt_dt(tl['assigned_at'], False)),
            ('Заявок обработано', tl['applications_processed']),
            ('Ср. время обработки, ч', tl['avg_processing_hours'] if tl['avg_processing_hours'] is not None else '—'),
        ])

    # F. Менеджер
    if rep.get('manager'):
        mg = rep['manager']
        b.h3('F. Дополнение менеджера')
        b.kv([
            ('Меро под управлением (всего / сезон)', f"{mg['total_events']} / {mg['season_events']}"),
            ('Дата назначения', _fmt_dt(mg['assigned_at'], False)),
            ('Заявок обработано', mg['applications_processed']),
            ('Ср. время обработки, ч', mg['avg_processing_hours'] if mg['avg_processing_hours'] is not None else '—'),
        ])

    if rep.get('activity_chart'):
        b.h3('Динамика активности')
        b.image_data_uri(rep['activity_chart'])
    if rep.get('churn_chart'):
        b.h3('Churn по сезонам')
        b.image_data_uri(rep['churn_chart'])


def build_person_report(rep) -> DocxBuilder:
    b = DocxBuilder()
    _append_person_card(b, rep, as_section=False)
    return b


# ---------------------------------------------------------------------------
# 3. Отчёт по волонтёрам (сводка + карточки подряд)
# ---------------------------------------------------------------------------

def build_volunteers_report(rep) -> DocxBuilder:
    b = DocxBuilder()
    scope = rep['scope']
    b.title('ОТЧЁТ ПО ВОЛОНТЁРАМ',
            subtitle=f"Охват: {_scope_label(scope)} · волонтёров в отчёте: {rep['count']}",
            tag=f"Сформирован: {_fmt_dt(rep.get('generated_at'))}")

    s = rep['summary']
    b.h2('Сводка по выборке')
    b.kv([
        ('Всего волонтёров', s['total_volunteers']),
        ('Суммарно часов', s['total_hours']),
        ('Суммарно участий', s['total_events']),
        ('Ср. часов на волонтёра', s['avg_hours']),
        ('Новых за охват', s['new_count']),
        ('Со звёздочкой ПГАС', s['star_count']),
        ('В блэклисте', s['blacklisted_count']),
        ('На грани блэклиста', s['at_risk_count']),
    ])
    for key, title in [('hours_hist_chart', 'Распределение часов'),
                       ('top_chart', 'Топ-10 по часам'),
                       ('churn_chart', 'Распределение churn_score')]:
        if rep.get(key):
            b.h3(title)
            b.image_data_uri(rep[key])

    b.page_break()
    b.h2('Карточки волонтёров')
    for card in rep['cards']:
        _append_person_card(b, card, as_section=True)
        b.page_break()
    return b


# ---------------------------------------------------------------------------
# 4. Отчёт по организации
# ---------------------------------------------------------------------------

def build_organization_report(rep) -> DocxBuilder:
    b = DocxBuilder()
    org = rep['organization']
    scope = rep['scope']
    b.title('ОТЧЁТ ПО ОРГАНИЗАЦИИ', subtitle=org.name,
            tag=f"Охват: {_scope_label(scope)} · сформирован: {_fmt_dt(rep.get('generated_at'))}")

    b.h2('A. Профиль организации')
    b.kv([
        ('Описание', org.description or '—'),
        ('Внутренний рейтинг', f"{org.internal_rating}/10" if getattr(org, 'internal_rating', None) is not None else '—'),
        ('В базе с', _fmt_dt(org.created_at, False)),
        ('Категории/тематики', ', '.join(rep['categories']) or '—'),
        ('Внутренние комментарии', getattr(org, 'comment', None) or '—'),
    ])

    b.h2('B. Контактные лица')
    b.table(
        ['ФИО', 'Телефон', 'Email', 'Telegram'],
        [[
            f"{link.organizer.first_name} {link.organizer.last_name}",
            link.organizer.phone or '—', link.organizer.email or '—',
            f"@{link.organizer.telegram_username}" if link.organizer.telegram_username else '—',
        ] for link in rep['contacts']],
        empty='Контактных лиц нет.',
    )

    st = rep['stats']
    b.h2('C. Статистика')
    b.kv([
        ('Мероприятий проведено', st['events_count']),
        ('Уникальных волонтёров', st['unique_volunteers']),
        ('Закрытых смен', st['closed_shifts']),
        ('Всего волонтёро-часов', st['total_hours']),
        ('Людям помогли', st['people_helped']),
        ('Средний рейтинг меро', st['avg_rating'] if st['avg_rating'] is not None else '—'),
    ])

    b.h2('D. Все мероприятия организации')
    b.table(
        ['Мероприятие', 'Даты', 'Статус', 'Волонтёров', 'Рейтинг'],
        [[
            row['event'].title,
            f"{_fmt_dt(row['date_from'], False)} — {_fmt_dt(row['date_to'], False)}",
            row['status'], row['volunteers_count'],
            row['rating'] if row['rating'] is not None else '—',
        ] for row in rep['events']],
        empty='Мероприятий нет.',
    )

    if rep.get('categories_chart'):
        b.h2('Мероприятия по категориям')
        b.image_data_uri(rep['categories_chart'])
    return b


# ---------------------------------------------------------------------------
# 5. Отчёт за период (общий) — блоки 1-8
# ---------------------------------------------------------------------------

def _append_period_analytics(b, context):
    """Блоки 1-8 сводной аналитики — общий для «за период» и «комплексного»."""
    data = context['report']
    is_internal = context.get('is_internal', True)

    # 1. Общие достижения
    b.h2('1. Общие достижения сообщества')
    b.kv([
        ('Всего часов', data['total_hours']),
        ('Всего мероприятий', data['total_events']),
        ('Активных волонтёров', data['unique_volunteers']),
        ('Закрытых смен', data['closed_shifts']),
        ('Новых волонтёров', data['new_volunteers']),
        ('Людей получили помощь', data['people_helped']),
    ])
    if is_internal and data['top_volunteers']:
        b.h3('Топ волонтёров по часам')
        b.table(
            ['Волонтёр', 'Часы'],
            [[v.get('name') or v.get('nickname') or '—', v.get('hours', 0)] for v in data['top_volunteers']],
        )

    # 2. Воронка набора
    f = data['funnel']
    b.h2('2. Воронка набора')
    b.kv([
        ('Подано заявок', f['submitted']),
        ('Одобрено', f['approved']),
        ('Отклонено (резерв)', f['rejected']),
        ('Явка', f['attended']),
        ('Неявка без предупреждения', f['unexcused']),
        ('Конверсия подал → явка', f"{f['conversion_pct']}%"),
    ])
    if context.get('funnel_chart'):
        b.image_data_uri(context['funnel_chart'])

    # 3. Эффективность набора
    if context.get('efficiency'):
        b.h2('3. Эффективность набора (по сменам)')
        b.table(
            ['Меро · смена', 'Нужно', 'Пришло', '% закрытия'],
            [[f"{s['title']} · {_fmt_dt(s['day'], False)}", s['needed'], s['attended'], f"{s['pct_closed']}%"]
             for s in context['efficiency']['shifts']],
            empty='Данных по сменам нет.',
        )

    # 4. Нагрузка персонала (только внутренний)
    if is_internal and context.get('staff'):
        staff = context['staff']
        b.h2('4. Нагрузка персонала')
        b.h3('Менеджеры')
        b.table(
            ['ФИО', 'Меро', 'Заявок обработано', 'Ср. время, ч'],
            [[m['name'], m['event_count'], m['applications_processed'],
              m['avg_processing_hours'] if m['avg_processing_hours'] is not None else '—'] for m in staff['managers']],
            empty='Нет данных.',
        )
        b.h3('Тим-лидеры')
        b.table(
            ['ФИО', 'Меро', 'Заявок обработано', 'Ср. время, ч'],
            [[t['name'], t['event_count'], t['applications_processed'],
              t['avg_processing_hours'] if t['avg_processing_hours'] is not None else '—'] for t in staff['team_leads']],
            empty='Нет данных.',
        )

    # 5. Retention и churn (только внутренний)
    if is_internal:
        ret = data['retention']
        b.h2('5. Retention и churn')
        b.kv([
            ('Churn rate', f"{ret['churn_rate_pct']}%"),
            ('Новых в блэклисте', ret['new_blacklisted']),
        ])
        if context.get('churn_chart'):
            b.image_data_uri(context['churn_chart'])

    # 6. Проблемные зоны (только внутренний)
    if is_internal:
        pz = data['problem_zones']
        b.h2('6. Проблемные зоны')
        b.kv([
            ('Меро с низким рейтингом', len(pz['low_rated_events'])),
            ('Волонтёров на грани блэклиста', len(pz['at_risk_users'])),
        ])

    # 7. Сравнение
    if data.get('comparison'):
        c = data['comparison']
        b.h2('7. Сравнение с прошлым периодом')
        b.kv([
            ('База', f"{_fmt_dt(c['date_from'], False)} — {_fmt_dt(c['date_to'], False)}"),
            ('Δ часов', f"{c['hours_delta']:+} ({c['hours_delta_pct']}%)" if c['hours_delta_pct'] is not None else c['hours_delta']),
            ('Δ мероприятий', f"{c['events_delta']:+}"),
            ('Δ волонтёров', f"{c['volunteers_delta']:+}"),
            ('Δ новых', f"{c['new_volunteers_delta']:+}"),
        ])

    # 8. Графики-дополнение
    for key, title in [('weekly_chart', 'Динамика по неделям'),
                       ('timing_chart', 'Отклик на мероприятие'),
                       ('category_chart', 'Распределение по категориям')]:
        if context.get(key):
            b.h3(title)
            b.image_data_uri(context[key])


def build_period_report(context) -> DocxBuilder:
    b = DocxBuilder()
    variant = 'внутренний' if context.get('is_internal') else 'внешний (обезличенный)'
    b.title('ОТЧЁТ ВОЛОНТЁРСКОГО ЦЕНТРА',
            subtitle=f"Период: {_fmt_dt(context['date_from'], False)} — {_fmt_dt(context['date_to'], False)} · вариация: {variant}",
            tag=f"Сформирован: {_fmt_dt(context.get('generated_at'))}")
    _append_period_analytics(b, context)
    return b


# ---------------------------------------------------------------------------
# 6. Комплексный отчёт за период (блоки 1-11)
# ---------------------------------------------------------------------------

def build_complex_report(context) -> DocxBuilder:
    b = DocxBuilder()
    b.title('КОМПЛЕКСНЫЙ ОТЧЁТ ЗА ПЕРИОД',
            subtitle=f"Период: {_fmt_dt(context['date_from'], False)} — {_fmt_dt(context['date_to'], False)}",
            tag=f"Сформирован: {_fmt_dt(context.get('generated_at'))}")

    # Часть 1 — сводная аналитика (блоки 1-8), всегда внутренняя.
    context = {**context, 'is_internal': True}
    _append_period_analytics(b, context)

    # Часть 2 — мероприятия периода подряд (блок 9).
    b.page_break()
    b.h2('9. Мероприятия периода')
    for rep in context.get('events_reports', []):
        b.h3(rep['event'].title)
        if rep.get('timeline_chart'):
            b.image_data_uri(rep['timeline_chart'])
        t = rep['totals']
        b.kv([
            ('Заявок / одобрено / явка', f"{t['submitted']} / {t['approved']} / {t['attended']}"),
            ('% закрытия', f"{t['pct_closed']}%"),
            ('Всего часов', t['total_hours']),
        ])

    # Часть 3 — таблица работы с заявками (блок 10).
    b.page_break()
    b.h2('10. Работа с заявками за период')
    rows = context.get('applications_rows', [])
    b.table(
        ['Мероприятие', 'Волонтёр', 'Подана', 'Статус', 'Обработал'],
        [[r['event'], r['name'] or '—', _fmt_dt(r['submitted_at'] or r['created_at']), r['status'], r['assigned_by']]
         for r in rows],
        empty='Заявок за период нет.',
    )
    summ = context.get('applications_summary')
    if summ:
        b.kv([
            ('Всего заявок', summ['total']),
            ('Одобрено / резерв', f"{summ['approved']} / {summ['rejected']}"),
            ('Не обработано (new)', summ['new']),
            ('Ср. время обработки, ч', summ['avg_lag_hours'] if summ['avg_lag_hours'] is not None else '—'),
        ])

    # Часть 4 — волонтёры периода подряд (блок 11).
    volunteers = context.get('volunteers')
    if volunteers:
        b.page_break()
        b.h2('11. Волонтёры периода')
        s = volunteers['summary']
        b.kv([
            ('Волонтёров', s['total_volunteers']),
            ('Суммарно часов', s['total_hours']),
            ('Новых', s['new_count']),
            ('Со звёздочкой', s['star_count']),
        ])
        for card in volunteers['cards']:
            _append_person_card(b, card, as_section=True)
            b.page_break()
    return b
