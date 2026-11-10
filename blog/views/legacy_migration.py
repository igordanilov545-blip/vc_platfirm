"""Миграция старых баз (менеджер): хаб → база → мероприятие. Вьюхи тонкие —
разбирают ввод и зовут blog/services/legacy_migration.py; см. legacy-migration.md."""
from datetime import date

from django.db import IntegrityError
from django.views.decorators.cache import never_cache

from ._common import *  # noqa: F401,F403
from blog.forms import LegacyBaseUploadForm, FapUploadForm
from blog.services import legacy_migration as lm


def _error_text(error):
    return ' '.join(error.messages) if isinstance(error, ValidationError) else str(error)


@manager_required
@never_cache
def legacy_migration(request):
    form = LegacyBaseUploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and request.POST.get('action') == 'upload_base' and form.is_valid():
        upload = form.cleaned_data['workbook']
        try:
            base = lm.upload_base(request.user, upload.read(), upload.name, form.cleaned_data['year'])
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, _error_text(error))
        else:
            messages.success(request, f'База {base.year} сохранена. Следующий шаг — загрузить людей.')
            return redirect('legacy_migration_base', base.pk)
    return render(request, 'blog/legacy_migration_hub.html', {'form': form, **lm.hub_overview()})


@manager_required
@never_cache
def legacy_migration_base(request, base_id):
    base = get_object_or_404(dc.legacy_bases_qs().defer('content', 'parsed'), pk=base_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'load_people':
                result = lm.load_people(request.user, dc.legacy_bases_qs().get(pk=base.pk))
                messages.success(request, f'Люди загружены: новых {result["created"]}, найдено существующих {result["existing"]}, '
                                          f'обновлено полей {result["updated"]}, уточнений у людей {result["conflicts"]}, '
                                          f'пропущено строк без ФИО {result["skipped"]}.')
            elif action == 'create_event':
                group_id = request.POST.get('group')
                group = get_object_or_404(dc.event_groups_qs(), pk=group_id) if group_id else None
                group = lm.create_event_from_columns(request.user, base, request.POST.getlist('columns'),
                                                     request.POST.get('title', ''), group=group)
                return redirect('legacy_migration_group', group.pk)
            elif action == 'skip':
                column = get_object_or_404(dc.legacy_base_columns_qs(), pk=request.POST.get('column'), base=base)
                lm.set_column(request.user, column, skipped=request.POST.get('value') == '1')
        except (ValidationError, IntegrityError) as error:
            messages.error(request, _error_text(error))
        return redirect('legacy_migration_base', base.pk)
    return render(request, 'blog/legacy_migration_base.html', lm.base_overview(base))


@manager_required
@never_cache
def legacy_migration_group(request, group_id):
    group = get_object_or_404(dc.event_groups_qs(), pk=group_id)
    fap_form = FapUploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'attach_fap':
                if fap_form.is_valid():
                    upload = fap_form.cleaned_data['workbook']
                    document = lm.attach_fap(request.user, group, upload.read(), upload.name)
                    messages.success(request, f'ФиП версии {document.version} применён.')
                else:
                    messages.error(request, ' '.join(e for errors in fap_form.errors.values() for e in errors))
            elif action == 'save_mappings':
                items, index = [], 0
                while f'key_{index}' in request.POST:
                    items.append({'key': request.POST[f'key_{index}'], 'raw': request.POST.get(f'raw_{index}', ''),
                                  'target': request.POST.get(f'target_{index}', ''), 'role': request.POST.get(f'role_{index}'),
                                  'title': request.POST.get(f'title_{index}', '')})
                    index += 1
                lm.save_mappings(request.user, group, items)
                messages.success(request, 'Сопоставление сохранено.')
            elif action in ('set_day', 'skip', 'unload'):
                column = get_object_or_404(dc.legacy_base_columns_qs(), pk=request.POST.get('column'), event_group=group)
                if action == 'set_day':
                    raw = request.POST.get('day', '')
                    try:
                        day = date.fromisoformat(raw) if raw else None
                    except ValueError:
                        raise ValidationError('Неверная дата колонки.')
                    lm.set_column(request.user, column, day=day)
                elif action == 'skip':
                    lm.set_column(request.user, column, skipped=request.POST.get('value') == '1')
                else:
                    result = lm.unload_column(request.user, column)
                    if result['conflicts']:
                        messages.warning(request, f'Не откачено {len(result["conflicts"])} участий: их изменили сотрудники.')
            elif action == 'load':
                columns = list(dc.legacy_base_columns_qs().filter(event_group=group, pk__in=request.POST.getlist('columns')))
                result = lm.load_columns(request.user, columns)
                messages.success(request, f'Загружено участий: {result["participations"]}, перенесено: {result["moved"]}, '
                                          f'новых тим-лидеров: {result["team_leads"]}.')
                if result['conflicts']:
                    messages.warning(request, f'Не перенесено {len(result["conflicts"])} участий: их изменили сотрудники.')
        except (ValidationError, IntegrityError) as error:
            messages.error(request, _error_text(error))
        return redirect('legacy_migration_group', group.pk)
    return render(request, 'blog/legacy_migration_group.html', {'fap_form': fap_form, **lm.group_page(group)})
