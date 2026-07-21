"""Вьюхи домена «analytics». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


@require_POST
def analytics_ping(request):
    """Heartbeat активной вкладки — обновляет last_seen_at сессии и duration_ms
    текущего просмотра страницы. Вызывается раз в ~20с, пока вкладка видима."""
    session_key = request.session.session_key
    if not session_key:
        return JsonResponse({'ok': False}, status=204)
    page_view_id = request.POST.get('page_view_id')
    duration_ms = request.POST.get('duration_ms')

    now = timezone.now()
    dc.touch_web_session(session_key, now)
    if page_view_id and duration_ms and duration_ms.isdigit():
        dc.set_page_view_duration(page_view_id, session_key, int(duration_ms))
    return JsonResponse({'ok': True})

@require_POST
def analytics_leave(request):
    """Финальная длительность просмотра при уходе со страницы (sendBeacon)."""
    session_key = request.session.session_key
    page_view_id = request.POST.get('page_view_id')
    duration_ms = request.POST.get('duration_ms')
    if session_key and page_view_id and duration_ms and duration_ms.isdigit():
        dc.set_page_view_duration(page_view_id, session_key, int(duration_ms))
    return JsonResponse({'ok': True})

@require_POST
def analytics_click(request):
    """Клик по элементу с data-track (или кнопке/ссылке) — фиксируем для дашборда.
    Привязываем к текущей WebSession (по session_key), чтобы позже можно было
    восстановить последовательность действий гостя, у которого нет user_id."""
    action_key = (request.POST.get('action_key') or '').strip()[:150]
    if not action_key:
        return JsonResponse({'ok': False}, status=400)
    label = (request.POST.get('label') or '').strip()[:200]
    user = request.user if request.user.is_authenticated else None
    web_session = dc.get_web_session(request.session.session_key)
    dc.create_button_click(
        source='web',
        user=user,
        web_session=web_session,
        role_snapshot=roles_service.role_slug(user) if user else 'guest',
        action_key=action_key,
        label=label,
    )
    return JsonResponse({'ok': True})

def _analytics_period(request):
    """Читает date_from/date_to из query (ISO-даты) с фолбэком на последние 7 дней."""
    raw_from = request.GET.get('date_from')
    raw_to = request.GET.get('date_to')
    date_to = timezone.now()
    date_from = date_to - datetime.timedelta(days=7)
    if raw_from:
        try:
            date_from = datetime.datetime.fromisoformat(raw_from)
            if timezone.is_naive(date_from):
                date_from = timezone.make_aware(date_from)
        except ValueError:
            pass
    if raw_to:
        try:
            date_to = datetime.datetime.fromisoformat(raw_to)
            if timezone.is_naive(date_to):
                date_to = timezone.make_aware(date_to)
        except ValueError:
            pass
    return date_from, date_to

@tech_admin_required
def analytics_dashboard(request):
    return render(request, 'blog/analytics_dashboard.html', {})

@tech_admin_required
def analytics_online_data(request):
    source = request.GET.get('source', 'web')
    minutes = min(int(request.GET.get('minutes', 60)), 24 * 60)
    if source == 'bot':
        data = analytics_service.online_series_bot(minutes=minutes)
    else:
        data = analytics_service.online_series_web(minutes=minutes)
    return JsonResponse(data)

@tech_admin_required
def analytics_clicks_data(request):
    """`source` обязателен ('web' или 'bot') — веб и бот показываются двумя отдельными
    графиками (разный функционал, разные кнопки), общий график не имеет смысла."""
    date_from, date_to = _analytics_period(request)
    source = request.GET.get('source')
    if source not in ('web', 'bot'):
        return JsonResponse({'error': 'source must be web or bot'}, status=400)
    role = request.GET.get('role') or None
    data = analytics_service.click_distribution(source=source, role=role, date_from=date_from, date_to=date_to)
    return JsonResponse(data)

@tech_admin_required
def analytics_load_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.page_load_stats(date_from=date_from, date_to=date_to)
    return JsonResponse(data)

@tech_admin_required
def analytics_duration_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.page_duration_histogram(date_from=date_from, date_to=date_to)
    return JsonResponse(data)

@tech_admin_required
def analytics_top_pages_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.top_pages(date_from=date_from, date_to=date_to)
    return JsonResponse(data)

@tech_admin_required
def analytics_top_bot_commands_data(request):
    date_from, date_to = _analytics_period(request)
    data = analytics_service.top_bot_commands(date_from=date_from, date_to=date_to)
    return JsonResponse(data)

@tech_admin_required
def analytics_downtimes_data(request):
    """Периоды простоя (для красных/жёлтых зон на графиках онлайна) за последние `hours`."""
    hours = min(int(request.GET.get('hours', 24)), 24 * 30)
    since = timezone.now() - datetime.timedelta(hours=hours)
    downtimes = dc.downtimes_since(since)
    return JsonResponse({
        'downtimes': [
            {
                'kind': d.kind,
                'started_at': d.started_at.isoformat(),
                'ended_at': d.ended_at.isoformat(),
                'comment': d.comment,
            }
            for d in downtimes
        ],
    })

@manager_required
@require_POST
def analytics_downtime_add(request):
    kind = request.POST.get('kind')
    if kind not in ('crash', 'planned'):
        return JsonResponse({'error': 'kind must be crash or planned'}, status=400)
    started_raw = request.POST.get('started_at')
    ended_raw = request.POST.get('ended_at')
    started = datetime.datetime.fromisoformat(started_raw) if started_raw else None
    ended = datetime.datetime.fromisoformat(ended_raw) if ended_raw else None
    if not started or not ended:
        return JsonResponse({'error': 'started_at/ended_at обязательны (ISO 8601)'}, status=400)
    if timezone.is_naive(started):
        started = timezone.make_aware(started)
    if timezone.is_naive(ended):
        ended = timezone.make_aware(ended)
    if ended <= started:
        return JsonResponse({'error': 'ended_at должен быть позже started_at'}, status=400)

    downtime = dc.create_downtime(
        kind, started, ended,
        comment=(request.POST.get('comment') or '').strip()[:255],
    )
    return JsonResponse({'ok': True, 'id': downtime.id})

@manager_required
@require_POST
def analytics_downtime_delete(request, downtime_id):
    dc.delete_downtime(downtime_id)
    return JsonResponse({'ok': True})

LOG_CHANNELS = {'web': 'web.log', 'bot': 'bot.log', 'db': 'db.log'}

LOG_TAIL_BATCH = 150

def _log_file_path(channel):
    filename = LOG_CHANNELS.get(channel)
    if not filename:
        raise Http404('Неизвестный канал логов.')
    path = Path(settings.LOG_DIR) / filename
    if not path.exists():
        raise Http404('Файл лога ещё не создан.')
    return path

@tech_admin_required
def analytics_log_download(request, channel):
    path = _log_file_path(channel)
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)

@tech_admin_required
def analytics_log_tail(request, channel):
    """Батч из LOG_TAIL_BATCH строк лога, читаемый с конца файла (для infinite scroll
    снизу вверх). `before_line` — курсор: номер строки (с конца, 0-based), с которой
    продолжать чтение более старых строк; без параметра отдаёт самый свежий батч."""
    path = _log_file_path(channel)
    with open(path, encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()

    total = len(all_lines)
    before_line = request.GET.get('before_line')
    end_offset = int(before_line) if before_line and before_line.isdigit() else 0
    start_index = max(total - end_offset - LOG_TAIL_BATCH, 0)
    end_index = total - end_offset
    batch = all_lines[start_index:end_index]

    return JsonResponse({
        'lines': [line.rstrip('\n') for line in batch],
        'next_cursor': total - start_index,
        'has_more': start_index > 0,
    })
