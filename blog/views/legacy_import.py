"""Менеджерская загрузка базы: файл → предпросмотр → подтверждение."""
import uuid
from django.db import IntegrityError
from django.utils import timezone
from django.views.decorators.cache import never_cache
from ._common import *  # noqa: F401,F403
from blog.forms import LegacyBaseUploadForm, LegacyDatesForm
from blog.services.legacy_workbook import read_legacy_workbook
from blog.services.legacy_import import preview_context, commit_legacy_base


@manager_required
@never_cache
def legacy_base_upload(request):
    upload_form = LegacyBaseUploadForm(request.POST or None, request.FILES or None)
    context = {'upload_form': upload_form}
    if request.method == 'POST' and request.POST.get('action') == 'commit':
        preview = request.session.get('legacy_base_preview')
        if not preview or preview['id'] != request.POST.get('preview_id') or preview['operator'] != request.user.pk:
            return HttpResponse('Предпросмотр не найден. Загрузите файл заново.', status=400)
        if timezone.now().timestamp() - preview['at'] > dc.get_const('legacy_import_preview_minutes', default=60) * 60:
            request.session.pop('legacy_base_preview', None)
            return HttpResponse('Предпросмотр устарел. Загрузите файл заново.', status=400)
        plan = preview['plan']
        dates = LegacyDatesForm(plan, request.POST)
        if dates.is_valid():
            try:
                result = commit_legacy_base(request.user, plan, date_overrides=dates.date_overrides())
            except (ValidationError, IntegrityError) as error:
                dates.add_error(None, error if isinstance(error, ValidationError) else 'Данные изменились во время загрузки. Повторите подтверждение.')
            else:
                request.session.pop('legacy_base_preview', None)
                return render(request, 'blog/legacy_base_upload.html', {'result': result})
        context.update(preview_context(request.user, plan))
        context.update({'dates_form': dates, 'preview_id': preview['id']})
    elif request.method == 'POST' and upload_form.is_valid():
        try:
            plan = read_legacy_workbook(upload_form.cleaned_data['workbook'].read(),
                                        max_rows=int(dc.get_const('legacy_import_max_rows', default=10000)))
            details = preview_context(request.user, plan)
        except ValidationError as error:
            upload_form.add_error(None, error)
        else:
            preview = {'id': uuid.uuid4().hex, 'operator': request.user.pk, 'at': timezone.now().timestamp(), 'plan': plan}
            request.session['legacy_base_preview'] = preview
            context.update(details)
            context.update({'dates_form': LegacyDatesForm(plan), 'preview_id': preview['id']})
    return render(request, 'blog/legacy_base_upload.html', context)
