"""Миграция старых баз (менеджер): хаб → база → мероприятие. Вьюхи тонкие —
разбирают ввод и зовут blog/services/legacy_migration.py и migration_jobs.py;
см. documentation/legacy-migration.md."""
from django.db import IntegrityError
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from ._common import *  # noqa: F401,F403
# После звёздочного импорта: _common экспортирует модуль datetime, он перекрыл бы класс.
from datetime import date, datetime  # noqa: E402
from blog.forms import LegacyBaseUploadForm, FapUploadForm, FapLibraryForm
from blog.services import legacy_migration as lm
from blog.services import migration_jobs


def _error_text(error):
    return ' '.join(error.messages) if isinstance(error, ValidationError) else str(error)


def _parse_day(raw):
    """Дата из поля календаря (ISO) или ручного ввода ДД.ММ.ГГГГ; пусто — None."""
    raw = (raw or '').strip()
    if not raw:
        return None
    for pattern in ('%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    raise ValidationError('Дата колонки в формате ДД.ММ.ГГГГ.')


def _report_fap_uploads(request, results):
    for name, document, error in results:
        if document and not error:
            messages.success(request, f'ФиП «{name}» загружен: дней {len(document.plan.get("dates", []))}, позиций {len(document.plan.get("directions", []))}.')
        elif document:
            messages.info(request, f'ФиП «{name}»: {error}')
        else:
            messages.error(request, f'ФиП «{name}» не загружен: {error}')


def _form_errors(request, form, what):
    """Ошибки формы загрузки — сообщением вверху страницы и в лог vc.web."""
    text = ' '.join(str(e) for errors in form.errors.values() for e in errors)
    logger.warning('Migration upload form invalid: %s errors=%s by=%s', what, text, actor(request.user))
    messages.error(request, f'{what}: {text}')


def _route_uploads(request, uploads, *, year=None, default_year=None):
    """Каждый файл — туда, где он нужен, по его листам: «База» → база, «Смены» → ФиП.
    Так ФиП, отправленный через форму базы (и наоборот), не теряется.
    Возвращает загруженную базу (если была) — для перехода на её страницу."""
    base, faps = None, []
    for upload in uploads:
        content = upload.read()
        kind = lm.workbook_kind(content)
        if kind == 'base':
            try:
                base = lm.upload_base(request.user, content, upload.name, year)
            except (ValidationError, IntegrityError) as error:
                messages.error(request, f'База «{upload.name}»: {_error_text(error)}')
            else:
                messages.success(request, f'База {base.year} «{upload.name}» сохранена. Следующий шаг — загрузить людей.')
        elif kind == 'fap':
            faps.append((upload.name, content))
        else:
            messages.error(request, f'«{upload.name}»: нет листа «База» или «Смены» — это не база и не ФиП.')
    if faps:
        _report_fap_uploads(request, lm.upload_fap_files(request.user, faps, default_year=default_year))
    return base


def _last_job(**filters):
    job = dc.migration_jobs_qs().filter(**filters).select_related('base', 'event_group').first()
    return {'job': job, 'status': migration_jobs.status(job)} if job else None


@manager_required
@never_cache
def legacy_migration(request):
    action = request.POST.get('action') if request.method == 'POST' else None
    form = LegacyBaseUploadForm(request.POST if action == 'upload_base' else None, request.FILES if action == 'upload_base' else None)
    fap_form = FapLibraryForm(request.POST if action == 'upload_fap' else None, request.FILES if action == 'upload_fap' else None)
    if action == 'upload_base':
        if form.is_valid():
            base = _route_uploads(request, [form.cleaned_data['workbook']], year=form.cleaned_data['year'])
            if base:
                return redirect('legacy_migration_base', base.pk)
            return redirect('legacy_migration')
        _form_errors(request, form, 'Загрузка базы')
    elif action == 'upload_fap':
        if fap_form.is_valid():
            _route_uploads(request, fap_form.cleaned_data['workbooks'])
            return redirect(reverse('legacy_migration') + '#fap-library')
        _form_errors(request, fap_form, 'Загрузка ФиП')
    return render(request, 'blog/legacy_migration_hub.html', {'form': form, 'fap_form': fap_form, **lm.hub_overview()})


@manager_required
@never_cache
def legacy_migration_base(request, base_id):
    base = get_object_or_404(dc.legacy_bases_qs().defer('content', 'parsed'), pk=base_id)
    fap_form = FapLibraryForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'load_people':
                migration_jobs.start_people(request.user, dc.legacy_bases_qs().get(pk=base.pk))
                messages.info(request, 'Загрузка людей запущена в фоне — можно переходить на другие страницы.')
            elif action == 'upload_fap':
                if fap_form.is_valid():
                    _route_uploads(request, fap_form.cleaned_data['workbooks'], default_year=base.year)
                else:
                    _form_errors(request, fap_form, 'Загрузка ФиП')
            elif action == 'map_fap':
                choices = {key.removeprefix('fap_'): value for key, value in request.POST.items() if key.startswith('fap_')}
                lm.map_columns_to_fap(request.user, base, choices)
                days = {key.removeprefix('day_'): _parse_day(value) for key, value in request.POST.items() if key.startswith('day_')}
                for column in dc.legacy_base_columns_qs().filter(base=base, pk__in=days.keys(), fap_document__isnull=True, loaded_at__isnull=True):
                    if column.day != days[str(column.pk)]:
                        lm.set_column(request.user, column, day=days[str(column.pk)])
                messages.success(request, 'Колонки сохранены.')
            elif action == 'create_event':
                group_id = request.POST.get('group')
                group = get_object_or_404(dc.event_groups_qs(), pk=group_id) if group_id else None
                group = lm.create_event_from_columns(request.user, base, request.POST.getlist('columns'),
                                                     request.POST.get('title', ''), group=group)
                return redirect('legacy_migration_group', group.pk)
            elif action in ('skip', 'set_day'):
                column = get_object_or_404(dc.legacy_base_columns_qs(), pk=request.POST.get('column'), base=base)
                if action == 'skip':
                    lm.set_column(request.user, column, skipped=request.POST.get('value') == '1')
                else:
                    lm.set_column(request.user, column, day=_parse_day(request.POST.get('day')))
        except (ValidationError, IntegrityError) as error:
            messages.error(request, _error_text(error))
        return redirect('legacy_migration_base', base.pk)
    context = lm.base_overview(base)
    context.update(fap_form=fap_form, last_job=_last_job(base=base))
    return render(request, 'blog/legacy_migration_base.html', context)


@manager_required
@never_cache
def legacy_migration_group(request, group_id):
    group = get_object_or_404(dc.event_groups_qs(), pk=group_id)
    fap_form = FapUploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        action = request.POST.get('action')
        anchor = ''
        try:
            if action == 'attach_fap':
                if fap_form.is_valid():
                    upload = fap_form.cleaned_data['workbook']
                    document = lm.attach_fap(request.user, group, upload.read(), upload.name)
                    messages.success(request, f'ФиП версии {document.version} применён.')
                else:
                    _form_errors(request, fap_form, 'Загрузка ФиП')
            elif action == 'save_mappings':
                items, index = [], 0
                while f'key_{index}' in request.POST:
                    items.append({'key': request.POST[f'key_{index}'], 'raw': request.POST.get(f'raw_{index}', ''),
                                  'target': request.POST.get(f'target_{index}', ''), 'role': request.POST.get(f'role_{index}'),
                                  'title': request.POST.get(f'title_{index}', ''),
                                  'function': request.POST.get(f'function_{index}', ''),
                                  'function_name': request.POST.get(f'function_name_{index}', '')})
                    index += 1
                lm.save_mappings(request.user, group, items)
                messages.success(request, 'Сопоставление сохранено.')
                anchor = '#migration-mapping'
            elif action in ('set_day', 'skip', 'unload'):
                column = get_object_or_404(dc.legacy_base_columns_qs(), pk=request.POST.get('column'), event_group=group)
                if action == 'set_day':
                    lm.set_column(request.user, column, day=_parse_day(request.POST.get('day')))
                elif action == 'skip':
                    lm.set_column(request.user, column, skipped=request.POST.get('value') == '1')
                else:
                    result = lm.unload_column(request.user, column)
                    if result['conflicts']:
                        messages.warning(request, f'Не откачено {len(result["conflicts"])} участий: их изменили сотрудники.')
            elif action == 'load':
                columns = list(dc.legacy_base_columns_qs().filter(event_group=group, pk__in=request.POST.getlist('columns')).order_by('day', 'index'))
                migration_jobs.start_columns(request.user, group, columns)
                messages.info(request, 'Загрузка колонок запущена в фоне — можно переходить на другие страницы.')
        except (ValidationError, IntegrityError) as error:
            messages.error(request, _error_text(error))
        return redirect(reverse('legacy_migration_group', args=[group.pk]) + anchor)
    context = lm.group_page(group)
    context.update(fap_form=fap_form, last_job=_last_job(event_group=group))
    return render(request, 'blog/legacy_migration_group.html', context)


@manager_required
@never_cache
def legacy_migration_job(request, job_id):
    """GET — JSON состояния фоновой загрузки; POST action=cancel — отмена."""
    job = get_object_or_404(dc.migration_jobs_qs().select_related('base', 'event_group'), pk=job_id)
    if request.method == 'POST' and request.POST.get('action') == 'cancel':
        migration_jobs.request_cancel(request.user, job)
        messages.info(request, 'Загрузка отменяется: созданное ею будет удалено.')
        target = request.POST.get('next', '')
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            target = reverse('legacy_migration')
        return redirect(target)
    return JsonResponse(migration_jobs.status(job))
