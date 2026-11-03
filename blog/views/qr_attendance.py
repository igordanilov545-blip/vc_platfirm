"""Личный QR и сканер; бизнес-правила и ACL находятся в общем сервисе."""
from ._common import *  # noqa: F401,F403
from django.views.decorators.cache import never_cache
from blog.forms import ScannerGrantForm
from blog.services import qr_attendance as qr


@login_required
@never_cache
def personal_qr(request):
    """Существующая модалка, содержащая только личный QR авторизованного пользователя."""
    template = 'blog/partials/_personal_qr.html' if is_ajax(request) else 'blog/personal_qr.html'
    return render(request, template)


@login_required
@never_cache
def personal_qr_png(request):
    """Приватное изображение без токена в URL; не кэшировать между аккаунтами."""
    response = HttpResponse(qr.personal_qr_png(request.user), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def qr_scanner(request):
    """Раздел Управление → Сканер QR, включая выданные отдельные права."""
    if not qr.can_scan(request.user):
        raise PermissionDenied('Нет доступа к сканеру.')
    grants = dc.scanner_grants_qs().filter(revoked_at=None).select_related('user', 'event_group') if has_manager_access(request.user) else []
    return render(request, 'blog/qr_scanner.html', {'scanner_grants': grants})


@login_required
@require_POST
@never_cache
def qr_scan(request):
    """Расшифрованный токен принимается POST, без изменения явки при просмотре."""
    try:
        context = qr.scan_context(request.user, request.POST.get('token', ''))
    except ValidationError as error:
        return HttpResponse(error.messages[0], status=400)
    return render(request, 'blog/partials/_qr_scan_result.html', context)


@login_required
@require_POST
@never_cache
def qr_mark(request):
    """Явный вход или выход; повторный запрос безопасен, ACL проверяется заново."""
    try:
        shift_id = int(request.POST.get('shift_id', ''))
        token = request.POST.get('token', '')
        qr.mark_scan(request.user, token, shift_id, request.POST.get('action', ''))
        context = qr.scan_context(request.user, token)
    except (ValueError, ValidationError) as error:
        message = error.messages[0] if isinstance(error, ValidationError) else 'Некорректная смена.'
        return HttpResponse(message, status=400)
    return render(request, 'blog/partials/_qr_scan_result.html', context)


@manager_required
def qr_scanner_grant(request):
    """Менеджер выдаёт доступ на мероприятие через существующую AJAX-форму."""
    form = ScannerGrantForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        qr.grant_scanner(request.user, form.cleaned_data['user'], form.cleaned_data['event_group'])
        return modal_form_response(request, None, None, success_redirect=reverse('qr_scanner'))
    return modal_form_response(request, 'blog/qr_grant_form.html', {'form': form, 'title': 'Доступ к сканеру'})


@manager_required
@require_POST
def qr_scanner_revoke(request, grant_id):
    """Отозвать назначение с сохранением истории."""
    try:
        qr.revoke_scanner(request.user, grant_id)
    except ValidationError as error:
        return HttpResponse(error.messages[0], status=400)
    return redirect('qr_scanner')
