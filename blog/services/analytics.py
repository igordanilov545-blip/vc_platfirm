"""Агрегация событий активности (analytics_*) для дашборда аналитики.

Источники данных — модели `WebSession`/`WebPageView`/`ButtonClickEvent`/`BotSessionPing`
(blog/models.py), заполняемые `blog.middleware.ActivityTrackingMiddleware` (веб),
фронтовым `analytics.js` (клики/время на странице) и `tg_bot.middlewares.ActivityMiddleware`
(бот). Здесь только чтение и ресэмплинг через pandas — без записи.
"""
import math

import pandas as pd
from django.utils import timezone

from data_base import data_controller as dc

ROLE_LABELS = {
    'volunteer': 'Волонтёр',
    'team_leader': 'Тим-лидер',
    'manager': 'Менеджер',
    'guest': 'Гость',
}

# Полный реестр известных кнопок/команд — гистограмма кликов должна показывать
# ВСЕ пункты меню, даже с нулевым числом кликов (не только то, что уже нажималось).
# Держать в синхроне с реальными обработчиками: веб-пункты — data-track="nav:*" в
# blog/templates/blog/base.html; бот — reply-кнопки/команды в tg_bot/handlers/*.py
# и callback-префиксы (до ':') в tg_bot/keyboards.py, нормализуются в
# tg_bot/middlewares.py::_normalize_action_key.
WEB_ACTION_REGISTRY = {
    'nav:dashboard': 'Главная',
    'nav:event_list': 'Мероприятия',
    'nav:application_create': 'Подать заявку',
    'nav:profile_detail': 'Мой профиль',
    'nav:pending_applications': 'Необработанные заявки',
    'nav:import_preview': 'Импорт заявок',
    'nav:user_list': 'Пользователи',
    'nav:organizations_list': 'Организации',
    'nav:organizer_list': 'Организаторы',
    'nav:location_list': 'Локации',
    'nav:requirement_list': 'Требования',
    'nav:report_period': 'Отчёты',
    'nav:dobro_page': 'Добро.ру',
    'nav:analytics_dashboard': 'Аналитика',
}

BOT_ACTION_REGISTRY = {
    'menu:📅 Мероприятия': 'Мероприятия (меню)',
    'cmd:/events': 'Мероприятия (команда)',
    'menu:📝 Мои заявки': 'Мои заявки (меню)',
    'cmd:/myapps': 'Мои заявки (команда)',
    'menu:📊 Статистика': 'Статистика (меню)',
    'cmd:/stats': 'Статистика (команда)',
    'menu:🔔 Подписка': 'Подписка (меню)',
    'cmd:/subscribe': 'Подписка (команда)',
    'menu:🔐 Авторизоваться на сайте': 'Авторизоваться на сайте (меню)',
    'cmd:/weblogin': 'Авторизоваться на сайте (команда)',
    'cmd:/login': 'Вход (команда)',
    'menu:🔐 Доступ к сайту': 'Доступ к сайту (меню)',
    'cmd:/webaccess': 'Доступ к сайту (команда)',
    'menu:👥 Мои мероприятия (ТЛ)': 'Мои мероприятия ТЛ (меню)',
    'cmd:/myevents': 'Мои мероприятия ТЛ (команда)',
    'menu:⚙️ Управление': 'Управление (меню)',
    'cmd:/allapplications': 'Все заявки (команда)',
    'menu:🔔 Заявки: уведомления': 'Уведомления о заявках (меню)',
    'cmd:/appnotify': 'Уведомления о заявках (команда)',
    'menu:📝 Зарегистрироваться': 'Зарегистрироваться (меню)',
    'cmd:/register': 'Зарегистрироваться (команда)',
    'cmd:/help': 'Помощь (команда)',
    'cmd:/start': 'Старт (команда)',
    'cb:apply': 'Подать заявку (кнопка)',
    'cb:app_edit': 'Изменить заявку (кнопка)',
    'cb:app_cancel': 'Отменить заявку (кнопка)',
    'cb:app_approve': 'Одобрить заявку (кнопка)',
    'cb:app_reject': 'В резерв (кнопка)',
    'cb:app_profile': 'Профиль заявителя (кнопка)',
    'cb:event_apps': 'Все заявки меро (кнопка)',
    'cb:event_apps_approve_all': 'Одобрить все заявки (кнопка)',
    'cb:event_attendance': 'Явка (кнопка)',
    'cb:comment': 'Комментарий волонтёру (кнопка)',
    'cb:att': 'Отметка явки (кнопка)',
    'cb:rate': 'Оценка мероприятия (кнопка)',
    'cb:feedback_comment': 'Добавить комментарий (кнопка)',
    'cb:feedback_done': 'Отзыв готов (кнопка)',
    'cb:register': 'Зарегистрироваться (кнопка)',
    'cb:events': 'Посмотреть мероприятия (кнопка)',
}


def _empty_series():
    return {'timestamps': [], 'values': []}


def online_series_web(minutes=60):
    """Уникальные веб-сессии с heartbeat в каждом минутном бакете за последние `minutes`."""
    since = timezone.now() - pd.Timedelta(minutes=minutes)
    rows = list(
        dc.web_sessions_qs().filter(last_seen_at__gte=since).values('session_key', 'last_seen_at')
    )
    return _bucket_online(rows, 'last_seen_at', 'session_key', minutes)


def online_series_bot(minutes=60):
    """Уникальные пользователи с пингом в каждом минутном бакете за последние `minutes`."""
    since = timezone.now() - pd.Timedelta(minutes=minutes)
    rows = list(
        dc.bot_session_pings_qs().filter(created_at__gte=since).values('created_at', 'user_id')
    )
    return _bucket_online(rows, 'created_at', 'user_id', minutes)


def _bucket_online(rows, time_field, id_field, minutes):
    now = timezone.now()
    # Индекс бакетов должен быть выровнен на начало минуты (floor), иначе он не
    # совпадёт с метками, которые расставляет `resample('1min')` ниже, и reindex
    # даст одни нули даже при наличии свежих событий.
    end = now.replace(second=0, microsecond=0)
    full_index = pd.date_range(end=end, periods=minutes, freq='1min', tz=now.tzinfo)
    if not rows:
        return {'timestamps': [ts.isoformat() for ts in full_index], 'values': [0] * minutes}
    df = pd.DataFrame(rows)
    df[time_field] = pd.to_datetime(df[time_field])
    df = df.set_index(time_field)
    bucketed = df[id_field].resample('1min').nunique()
    bucketed = bucketed.reindex(full_index, fill_value=0)
    return {
        'timestamps': [ts.isoformat() for ts in bucketed.index],
        'values': [int(v) for v in bucketed.values],
    }


def _registry_for(source):
    if source == 'web':
        return dict(WEB_ACTION_REGISTRY)
    if source == 'bot':
        return dict(BOT_ACTION_REGISTRY)
    merged = dict(WEB_ACTION_REGISTRY)
    merged.update(BOT_ACTION_REGISTRY)
    return merged


def click_distribution(source=None, role=None, date_from=None, date_to=None, limit=25):
    """Клики по кнопкам/командам за период, с опциональным фильтром источника/роли.
    Всегда включает весь известный реестр кнопок (см. WEB_ACTION_REGISTRY/
    BOT_ACTION_REGISTRY) — даже с нулём кликов, плюс любые незарегистрированные
    action_key, реально встретившиеся в данных (напр. новые кнопки, ещё не
    добавленные в реестр)."""
    qs = dc.button_click_events_qs().all()
    if source:
        qs = qs.filter(source=source)
    if role:
        qs = qs.filter(role_snapshot=role)
    if date_from:
        qs = qs.filter(created_at__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__lte=date_to)

    rows = list(qs.values('action_key', 'label'))
    registry = _registry_for(source)
    counts = {key: 0 for key in registry}
    labels_by_key = dict(registry)

    if rows:
        df = pd.DataFrame(rows)
        grouped = df.groupby('action_key').agg(count=('action_key', 'size'), label=('label', 'first'))
        for key, row in grouped.iterrows():
            counts[key] = counts.get(key, 0) + int(row['count'])
            if key not in labels_by_key:
                labels_by_key[key] = row['label'] or key

    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {
        'labels': [labels_by_key.get(key, key) for key, _ in ordered],
        'values': [v for _, v in ordered],
    }


def page_load_stats(date_from=None, date_to=None, limit=20):
    """Boxplot-статистика (min/q1/median/q3/max) времени ответа сервера по view_name."""
    qs = dc.web_page_views_qs().exclude(load_ms__isnull=True)
    if date_from:
        qs = qs.filter(entered_at__gte=date_from)
    if date_to:
        qs = qs.filter(entered_at__lte=date_to)

    rows = list(qs.values('view_name', 'load_ms'))
    if not rows:
        return {'series': []}
    df = pd.DataFrame(rows)
    df['view_name'] = df['view_name'].replace('', '(без имени)')
    top_views = df['view_name'].value_counts().head(limit).index
    df = df[df['view_name'].isin(top_views)]

    series = []
    for name, group in df.groupby('view_name'):
        q1, median, q3 = group['load_ms'].quantile([0.25, 0.5, 0.75])
        series.append({
            'x': name,
            'y': [
                int(group['load_ms'].min()),
                int(q1),
                int(median),
                int(q3),
                int(group['load_ms'].max()),
            ],
        })
    series.sort(key=lambda s: s['y'][2], reverse=True)
    return {'series': series}


def page_duration_histogram(date_from=None, date_to=None):
    """Логарифмические бакеты времени, проведённого на странице (секунды): 0-1с, 1-2с, 2-4с, ...
    вплоть до >30мин, чтобы забытая открытой вкладка не искажала линейную шкалу.
    Все бакеты присутствуют в ответе всегда, даже с нулевым числом просмотров."""
    edges = [0, 1, 2, 4, 8, 15, 30, 60, 120, 300, 600, 1800, math.inf]
    labels = ['0-1с', '1-2с', '2-4с', '4-8с', '8-15с', '15-30с', '30-60с',
              '1-2мин', '2-5мин', '5-10мин', '10-30мин', '>30мин']
    counts = [0] * len(labels)

    qs = dc.web_page_views_qs().exclude(duration_ms__isnull=True).filter(duration_ms__gt=0)
    if date_from:
        qs = qs.filter(entered_at__gte=date_from)
    if date_to:
        qs = qs.filter(entered_at__lte=date_to)

    for ms in qs.values_list('duration_ms', flat=True):
        sec = ms / 1000
        for i in range(len(edges) - 1):
            if edges[i] <= sec < edges[i + 1]:
                counts[i] += 1
                break
    return {'labels': labels, 'values': counts}


def top_pages(date_from=None, date_to=None, limit=15):
    """Топ страниц (веб) по числу просмотров за период — «что смотрят чаще всего»."""
    qs = dc.web_page_views_qs().all()
    if date_from:
        qs = qs.filter(entered_at__gte=date_from)
    if date_to:
        qs = qs.filter(entered_at__lte=date_to)
    rows = list(qs.values('view_name'))
    if not rows:
        return {'labels': [], 'values': []}
    df = pd.DataFrame(rows)
    df['view_name'] = df['view_name'].replace('', '(без имени)')
    counts = df['view_name'].value_counts().head(limit)
    return {'labels': list(counts.index), 'values': [int(v) for v in counts.values]}


def top_bot_commands(date_from=None, date_to=None, limit=15):
    """Топ команд/кнопок бота по числу кликов за период — только реально встретившиеся
    (не полный реестр с нулями, как click_distribution: здесь именно топ, для читаемости),
    отсортировано по убыванию, подписи обрезаны до разумной длины."""
    qs = dc.button_click_events_qs().filter(source='bot')
    if date_from:
        qs = qs.filter(created_at__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__lte=date_to)

    rows = list(qs.values('action_key', 'label'))
    if not rows:
        return {'labels': [], 'values': []}

    df = pd.DataFrame(rows)
    grouped = df.groupby('action_key').agg(count=('action_key', 'size'), label=('label', 'first'))
    grouped = grouped.sort_values('count', ascending=False).head(limit)

    labels = []
    for key, row in grouped.iterrows():
        label = row['label'] or BOT_ACTION_REGISTRY.get(key, key)
        labels.append(label[:40])
    return {'labels': labels, 'values': [int(v) for v in grouped['count']]}
