"""Вьюхи домена «letters» — конструктор благодарственных писем (letter-templates.md).

Менеджер загружает PDF-фон и расставляет поверх поля-заглушки (ФИО/меро/часы/…);
конфигурация полей хранится в ThankYouLetterTemplate.fields_json, итоговый PDF
штампуется PyMuPDF в blog.services.letter_render (кросс-платформенно).

Общие импорты/хелперы — из ._common. Здесь только вьюхи этого домена.
"""
import json

from ._common import *  # noqa: F401,F403

from blog.services import letter_render


@manager_required
def letter_template_list(request):
    """Панель хаба настроек «Шаблоны писем» (agent-workflow §4): AJAX → partial,
    прямой заход → редирект в хаб на нужную вкладку."""
    templates = dc.letter_templates_qs().order_by('title')
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_letters.html', {'templates': templates})
    return redirect(reverse('settings') + '?tab=letters')


@manager_required
def letter_template_create(request):
    """Создание шаблона: название + (опц.) PDF-фон. После создания ведём в редактор."""
    form = LetterTemplateForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        template = dc.create_letter_template(form.cleaned_data['title'], actor_user=request.user)
        if form.cleaned_data.get('background_pdf_file'):
            _save_background(template, form, request.user)
        messages.success(request, 'Шаблон письма создан. Разместите поля поверх фона.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('letter_template_editor', args=[template.id]),
        )
    return modal_form_response(
        request, 'blog/letter_template_form.html',
        {'form': form, 'title': 'Новый шаблон письма', 'submit_label': 'Создать',
         'form_enctype': 'multipart/form-data'},
    )


@manager_required
def letter_template_editor(request, template_id):
    """Страница-редактор: подложка (PNG первой страницы PDF) + перетаскиваемые поля.
    Конфигурация полей сохраняется отдельной AJAX-вьюхой letter_template_save_fields."""
    template = get_object_or_404(ThankYouLetterTemplate, pk=template_id)
    letter_render.ensure_builtin_fonts()
    fonts = dc.get_letter_fonts()
    context = {
        'template': template,
        'fonts': fonts,
        'fonts_json': json.dumps([{'id': f.id, 'name': f.name} for f in fonts], ensure_ascii=False),
        'fields_json': json.dumps(template.fields_json or []),
        'field_keys': letter_render.FIELD_KEYS,
        'field_keys_json': json.dumps(letter_render.FIELD_KEYS, ensure_ascii=False),
        'upload_form': LetterTemplateForm(instance=template),
        'font_form': LetterFontForm(),
    }
    return render(request, 'blog/letter_template_editor.html', context)


@manager_required
def letter_template_background(request, template_id):
    """PNG-подложка первой страницы PDF-фона (для canvas редактора). 404, если фона нет."""
    template = get_object_or_404(ThankYouLetterTemplate, pk=template_id)
    if not template.has_background:
        raise Http404('Фон не загружен')
    png = letter_render.background_page_png(template)
    return HttpResponse(png, content_type='image/png')


@manager_required
def letter_template_upload_bg(request, template_id):
    """Загрузка/замена PDF-фона у существующего шаблона (форма на странице редактора)."""
    template = get_object_or_404(ThankYouLetterTemplate, pk=template_id)
    form = LetterTemplateForm(request.POST or None, request.FILES or None, instance=template)
    if request.method == 'POST' and form.is_valid():
        form.save()  # title
        if form.cleaned_data.get('background_pdf_file'):
            _save_background(template, form, request.user)
            messages.success(request, 'PDF-фон обновлён.')
        else:
            messages.info(request, 'Файл не выбран — фон не изменён.')
    return redirect(reverse('letter_template_editor', args=[template.id]))


@manager_required
@require_POST
def letter_template_save_fields(request, template_id):
    """AJAX: сохранение конфигурации полей (JSON из редактора). Возвращает JSON-статус."""
    template = get_object_or_404(ThankYouLetterTemplate, pk=template_id)
    try:
        fields = json.loads(request.body.decode('utf-8'))
        if not isinstance(fields, list):
            raise ValueError('fields must be a list')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Некорректные данные полей.'}, status=400)
    dc.set_letter_fields(template, fields, actor_user=request.user)
    return JsonResponse({'ok': True})


@manager_required
def letter_template_preview(request, template_id):
    """PDF-превью с демо-данными (как письмо будет выглядеть). Inline в браузере."""
    template = get_object_or_404(ThankYouLetterTemplate, pk=template_id)
    if not template.has_background:
        raise Http404('Фон не загружен')
    pdf = letter_render.render_letter_pdf(template, letter_render.demo_context())
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="preview_{template.id}.pdf"'
    return resp


@manager_required
def letter_template_delete(request, template_id):
    template = get_object_or_404(ThankYouLetterTemplate, pk=template_id)
    if request.method == 'POST':
        title = template.title
        dc.delete_letter_template(template, actor_user=request.user)
        messages.success(request, f'Шаблон письма «{title}» удалён.')
    return redirect(reverse('settings') + '?tab=letters')


@manager_required
@require_POST
def letter_font_upload(request):
    """Загрузка своего шрифта. Отдаёт JSON (для панели редактора) или редиректит
    (обычная форма) — по X-Requested-With."""
    form = LetterFontForm(request.POST, request.FILES)
    if form.is_valid():
        font = dc.create_letter_font(
            name=form.cleaned_data['name'],
            data=form.cleaned_data['font_bytes'],
            filename=form.cleaned_data['font_filename'],
            actor_user=request.user,
        )
        if is_ajax(request):
            return JsonResponse({'ok': True, 'id': font.id, 'name': font.name})
        messages.success(request, f'Шрифт «{font.name}» добавлен.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('settings'))
    if is_ajax(request):
        errors = {k: [e for e in v] for k, v in form.errors.items()}
        return JsonResponse({'ok': False, 'errors': errors}, status=400)
    messages.error(request, 'Не удалось добавить шрифт. Проверьте файл и название.')
    return redirect(request.META.get('HTTP_REFERER') or reverse('settings'))


@manager_required
def letter_font_delete(request, font_id):
    font = get_object_or_404(LetterFont, pk=font_id)
    if request.method == 'POST':
        if font.is_builtin:
            messages.error(request, 'Встроенный шрифт нельзя удалить.')
        else:
            name = font.name
            dc.delete_letter_font(font, actor_user=request.user)
            messages.success(request, f'Шрифт «{name}» удалён.')
    return redirect(reverse('letter_template_editor', args=[request.GET.get('back', 0)])
                    if request.GET.get('back') else reverse('settings') + '?tab=letters')


def _save_background(template, form, user):
    """Общая запись PDF-фона: размеры страницы читаем PyMuPDF, байты кладём в БД."""
    data = form.cleaned_data['background_pdf_bytes']
    name = form.cleaned_data['background_pdf_name']
    width, height = letter_render.read_pdf_page_size(data)
    dc.set_letter_background(template, data, name, width, height, actor_user=user)
