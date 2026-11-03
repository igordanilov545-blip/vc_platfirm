"""Вьюхи домена «volunteers». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


@manager_required
def user_blacklist(request, user_id):
    """Ручная блокировка волонтёра менеджером — двухфакторное подтверждение (капча
    x+y) и обязательная причина, как и другие необратимые/чувствительные действия
    (event_delete). Причина сохраняется в User.comment (внутреннее поле, видно только
    менеджеру). Пользователь НЕ уведомляется о блокировке."""
    target = get_object_or_404(User, pk=user_id)
    session_key = f'captcha_user_blacklist_{target.id}'

    if request.method == 'POST':
        reason = (request.POST.get('reason') or '').strip()
        if not reason:
            messages.error(request, 'Укажите причину блокировки.')
            return redirect('profile_detail', user_id=target.id)
        if not _check_captcha(request, session_key, request.POST.get('captcha_answer')):
            messages.error(request, 'Неверный ответ на пример — блокировка отменена. Попробуйте ещё раз.')
            return modal_form_response(request, None, None, success_redirect=reverse('profile_detail', args=[target.id]))

        from blog.services.moderation import blacklist_user
        blacklist_user(target, reason, actor=request.user)
        logger.info('Волонтёр внесён в чёрный список: user=%s by=%s reason=%r', target.id, actor(request.user), reason)
        messages.success(request, f'«{target.full_name}» внесён(а) в чёрный список.')
        return modal_form_response(request, None, None, success_redirect=reverse('profile_detail', args=[target.id]))

    return render_captcha_modal(
        request,
        session_key=session_key,
        action_url=reverse('user_blacklist', args=[target.id]),
        confirm_text=f'Внести «{target.full_name}» в чёрный список? Пользователь не будет уведомлён об этом.',
        submit_label='Внести в чёрный список',
        title=f'Блокировка: {target.full_name}',
        reason_field=True,
        reason_label='Причина блокировки (обязательно)',
    )

@manager_required
@require_POST
def user_unblacklist(request, user_id):
    """Вернуть волонтёра из чёрного списка (менеджер). Симметрично блокировке, но без
    капчи — это разблокирующее (безопасное) действие. Ставим статус 'active' и
    ОБНУЛЯЕМ churn_score: иначе, если churn остался ≥ порога, ближайший пересчёт
    (закрытие смены/сезона) снова автоматически отправит пользователя в блэклист —
    ручной вывод из ЧС был бы бессмысленным."""
    target = get_object_or_404(User, pk=user_id)
    from blog.services.moderation import unblacklist_user
    _, was_blacklisted = unblacklist_user(target, actor=request.user)
    if not was_blacklisted:
        messages.info(request, f'«{target.full_name}» не в чёрном списке.')
        return redirect('profile_detail', user_id=target.id)

    logger.info('Волонтёр выведен из чёрного списка: user=%s by=%s', target.id, actor(request.user))
    messages.success(request, f'«{target.full_name}» выведён(а) из чёрного списка (churn обнулён).')
    return redirect('profile_detail', user_id=target.id)

@manager_required
def users_picker_data(request):
    """Компактный JSON-список всех пользователей (id + ФИО + флаги активных ролей) для
    единого JS-виджета выбора в remote-режиме (data-select-remote="users", base.html) — единственный источник
    данных для ЛЮБОГО количества таких виджетов на любой странице: страница требований
    (список исключений на каждое требование) и страница настроек (назначение/снятие
    ролей) раньше рендерили серверный <select> со ВСЕМИ пользователями на КАЖДЫЙ такой
    блок — при нескольких тысячах пользователей и нескольких блоков на странице это
    давало десятки тысяч <option> в HTML и заметно тормозило загрузку. Теперь список
    запрашивается один раз (JS кэширует на странице) и рендерится на клиенте.

    Флаги is_team_lead/is_manager нужны, чтобы виджет мог на клиенте отфильтровать
    список под конкретный блок (напр. «снять роль ТЛ» — показывать только действующих
    ТЛ), не делая для этого отдельный серверный запрос/queryset на каждый блок.

    Ранжирование и лимит (легаси-база копит десятки тысяч пользователей, отдавать всех
    сразу незачем):
      - `?order=recent` (по умолчанию) — сначала те, кто был на меро недавно
        (last_event_at DESC, никогда не участвовавшие — в конце);
      - `?order=name` — по алфавиту (фамилия, имя);
      - без `?all=1` отдаём только первые `users_picker_limit` (константа) записей
        ВЫБРАННОГО порядка + флаг `truncated`, чтобы клиент показал «показать всех»;
      - `?all=1` — весь список (менеджер нажал «показать всех»)."""
    from data_base import data_controller as dc

    tl_ids = set(dc.team_leaders_qs().filter(revoked_at__isnull=True).values_list('user_id', flat=True))
    mgr_ids = set(dc.managers_qs().filter(revoked_at__isnull=True).values_list('user_id', flat=True))

    order = 'name' if request.GET.get('order') == 'name' else 'recent'
    qs = dc.users_ranked_qs(order)

    show_all = request.GET.get('all') == '1'
    limit = int(dc.get_const('users_picker_limit', default=200))
    total = qs.count()
    if not show_all:
        qs = qs[:limit]

    users = qs.values('id', 'first_name', 'last_name')
    data = [
        {
            'id': u['id'],
            'label': f"{u['last_name'] or ''} {u['first_name'] or ''}".strip() or f"#{u['id']}",
            'is_team_lead': u['id'] in tl_ids,
            'is_manager': u['id'] in mgr_ids,
        }
        for u in users
    ]
    return JsonResponse({
        'users': data,
        'truncated': (not show_all) and total > limit,
        'total': total,
        'shown': len(data),
    })

@manager_required
def user_list(request):
    from django.http import HttpResponseNotModified, HttpResponseForbidden
    from django.utils.cache import patch_cache_control, patch_vary_headers
    from django.utils.http import parse_etags
    from blog.services.user_table import user_table_context

    owner = request.GET.get('table_owner')
    if owner and owner != str(request.user.pk):
        return HttpResponseForbidden()
    full = request.GET.get('all') == '1'
    context = user_table_context(full=full, page_number=request.GET.get('page'), owner_id=request.user.pk)
    etag = context['table_etag']
    requested_tags = [tag.removeprefix('W/') for tag in parse_etags(request.headers.get('If-None-Match', ''))]
    if full and etag and (etag in requested_tags or '*' in requested_tags):
        response = HttpResponseNotModified()
    else:
        template = 'blog/partials/_user_list_rows.html' if is_ajax(request) else 'blog/user_list.html'
        response = render(request, template, context)
    if full:
        response['ETag'] = etag
        # Browser keeps the complete table, revalidating permissions/data on every visit.
        patch_cache_control(response, private=True, no_cache=True)
    patch_vary_headers(response, ['Cookie', 'X-Requested-With'])
    return response
