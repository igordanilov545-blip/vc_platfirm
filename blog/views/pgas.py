"""Вьюхи домена «pgas». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


def _build_certificate_pdf(user, events, period_label):
    """Общий хвост генерации справки: рендер загруженного .docx-шаблона (с
    сохранением оформления) → LibreOffice в PDF → «картиночный» PDF. Возвращает
    (pdf_bytes, filename). Используется и волонтёрской, и менеджерской вьюхой (одно
    правило генерации — одно место)."""
    from django.utils.text import slugify

    from blog.services.pgas_certificate import render_docx
    from blog.services.pgas_pdf import certificate_pdf_from_docx

    docx_bytes = render_docx(user, events, period_label=period_label)
    pdf_bytes = certificate_pdf_from_docx(docx_bytes)
    filename = f'pgas-{slugify(user.full_name) or user.id}.pdf'
    return pdf_bytes, filename

@login_required
@require_POST
def pgas_certificate_download(request):
    """«Получить справку на ПГАС» (волонтёр на себя). Охват — за сезон (scope=season,
    по умолчанию) или за всё время (scope=all). Условия проверяются (кнопка иначе
    недоступна, но дублируем на бэке). Пайплайн — HTML→WeasyPrint→растр в PDF-картинку
    (blog/services/pgas_pdf.py). Проверяется на проде (локально WeasyPrint нет)."""
    from blog.services.pgas_certificate import (
        collect_events, pgas_certificate_eligibility, season_range,
    )
    from blog.services.pgas_pdf import certificate_response

    result = pgas_certificate_eligibility(request.user)
    if not result['eligible']:
        messages.error(request, f'Не хватает: {", ".join(result["missing"])}.')
        return redirect('profile_detail', user_id=request.user.id)

    scope = request.POST.get('scope', 'season')
    if scope == 'all':
        events = collect_events(request.user)
        period_label = 'всё время'
    else:
        date_from, date_to = season_range()
        events = collect_events(request.user, date_from=date_from, date_to=date_to)
        period_label = 'текущий сезон'

    try:
        pdf_bytes, filename = _build_certificate_pdf(request.user, events, period_label)
    except Exception:
        logger.exception('Ошибка генерации справки ПГАС: user=%s', request.user.id)
        messages.error(request, 'Не удалось сгенерировать справку. Попробуйте позже.')
        return redirect('profile_detail', user_id=request.user.id)

    logger.info('Справка ПГАС выдана: user=%s scope=%s events=%s', request.user.id, scope, len(events))
    return certificate_response(pdf_bytes, filename)

@login_required
def pgas_certificate_issue(request, user_id):
    """Выдача справки ВЦ для ПГАС с выбором периода и конкретных мероприятий (выбор
    n из m — теми же чипами, что и у менеджера при назначении ТЛ). Доступ:
      - менеджер — на любого волонтёра;
      - сам волонтёр — на себя, но только если он вправе получить справку
        (pgas_certificate_eligibility): та же проверка, что была у кнопки в ЛК.
    GET — форма (список посещённых мероприятий за диапазон, все преотмечены),
    POST(generate) — генерация PDF по выбранным. Мероприятия — только те, где была
    явка (collect_events), и попадающие в выбранный период."""
    from blog.services.pgas_certificate import collect_events, pgas_certificate_eligibility
    from blog.services.pgas_pdf import certificate_response

    target = get_object_or_404(User, pk=user_id)
    is_owner = request.user.id == target.id
    is_mgr = is_manager(request.user)
    if not (is_mgr or is_owner):
        return HttpResponseForbidden('Нет доступа к выдаче справки для этого профиля.')
    # Волонтёр может выдать справку себе только при выполнении всех условий (как раньше
    # у кнопки «Получить справку» в ЛК). Менеджер выдаёт без этого ограничения.
    if is_owner and not is_mgr:
        elig = pgas_certificate_eligibility(request.user)
        if not elig['eligible']:
            messages.error(request, f'Не хватает: {", ".join(elig["missing"])}.')
            return redirect('profile_detail', user_id=request.user.id)

    def _parse_date(name):
        raw = (request.POST.get(name) or request.GET.get(name) or '').strip()
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            return None

    date_from = _parse_date('date_from')
    date_to = _parse_date('date_to')

    if request.method == 'POST' and request.POST.get('generate'):
        selected_ids = [int(x) for x in request.POST.getlist('event_ids') if x.isdigit()]
        events = collect_events(
            target, date_from=date_from, date_to=date_to,
            event_ids=selected_ids or None,
        )
        if not events:
            messages.error(request, 'Не выбрано ни одного мероприятия с участием.')
            return redirect('pgas_certificate_issue', user_id=target.id)
        if date_from and date_to:
            period_label = f'{date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}'
        else:
            period_label = 'всё время'
        try:
            pdf_bytes, filename = _build_certificate_pdf(target, events, period_label)
        except Exception:
            logger.exception('Ошибка генерации справки ПГАС: target=%s by=%s', target.id, actor(request.user))
            messages.error(request, 'Не удалось сгенерировать справку. Попробуйте позже.')
            return redirect('pgas_certificate_issue', user_id=target.id)
        logger.info('Справка ПГАС выдана: target=%s by=%s events=%s%s',
                    target.id, actor(request.user), len(events),
                    ' (self)' if is_owner else '')
        return certificate_response(pdf_bytes, filename)

    # GET / выбор диапазона — показываем доступные мероприятия за диапазон.
    available = collect_events(target, date_from=date_from, date_to=date_to)
    return render(request, 'blog/pgas_certificate_issue.html', {
        'target': target,
        'available_events': available,
        'date_from': date_from,
        'date_to': date_to,
        'is_owner': is_owner,
        'is_manager': is_mgr,
    })

@manager_required
def pgas_template_download(request):
    """Скачать текущий .docx-шаблон справки (чтобы менеджер отредактировал его в
    Word и загрузил обратно)."""
    from django.http import HttpResponse

    from blog.services.pgas_certificate import get_template

    template = get_template()
    response = HttpResponse(
        bytes(template.docx_file),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="{template.filename or "pgas_template.docx"}"'
    return response

@login_required
@require_POST
def pgas_request_verification(request):
    """«Запросить верификацию» — профиль полностью заполнен, не хватает только
    ручного подтверждения менеджером; создаёт инцидент в разделе «Главное»."""
    from blog.services.pgas_certificate import only_verification_missing
    from blog.services.incidents import create_incident

    if not only_verification_missing(request.user):
        messages.error(request, 'Сначала заполните профиль полностью.')
        return redirect('profile_detail', user_id=request.user.id)

    create_incident(
        'pgas_verification',
        f'«{request.user.full_name}» запросил(а) верификацию для справки ПГАС.',
        related_user=request.user,
    )
    messages.success(request, 'Заявка на верификацию отправлена менеджеру.')
    return redirect('profile_detail', user_id=request.user.id)

@manager_required
@require_POST
def pgas_verify_user(request, user_id):
    """Менеджер подтверждает верификацию волонтёра для справки ПГАС — с чужого
    профиля. Резолвит связанный инцидент `pgas_verification`, если он есть."""
    from blog.services.pgas_certificate import snapshot_verified_fields
    from blog.services.moderation import verify_user_for_pgas

    target = get_object_or_404(User, pk=user_id)
    # Снимок верифицированных значений — чтобы потом отследить именно их изменение
    # (перевод на другую ОП, смену ФИО и т.п.) и снять верификацию.
    verify_user_for_pgas(target, actor=request.user, snapshot=snapshot_verified_fields(target))

    logger.info('Верификация для ПГАС подтверждена: user=%s by=%s', target.id, actor(request.user))
    messages.success(request, f'«{target.full_name}» верифицирован(а) для справки ПГАС.')
    return redirect('profile_detail', user_id=target.id)

@manager_required
@require_POST
def pgas_unverify_user(request, user_id):
    """Отзыв верификации для справки ПГАС — симметрично выдаче (без капчи: это
    возврат в исходное состояние, а не запуск нового необратимого процесса)."""
    from blog.services.moderation import unverify_user_for_pgas
    target = get_object_or_404(User, pk=user_id)
    unverify_user_for_pgas(target, actor=request.user)

    logger.info('Верификация для ПГАС отозвана: user=%s by=%s', target.id, actor(request.user))
    messages.success(request, f'Верификация «{target.full_name}» для справки ПГАС отозвана.')
    return redirect('profile_detail', user_id=target.id)
