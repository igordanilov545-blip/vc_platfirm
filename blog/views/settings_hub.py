"""Вьюхи домена «settings_hub». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


ROLE_ACTIONS = {
    'assign_team_lead': ('team_lead', 'assign'),
    'revoke_team_lead': ('team_lead', 'revoke'),
    'assign_manager': ('manager', 'assign'),
    'revoke_manager': ('manager', 'revoke'),
}

ROLE_LABELS = {'team_lead': 'тим-лидера', 'manager': 'менеджера'}

SETTINGS_TABS = [
    {'key': 'locations', 'icon': '📍', 'title': 'Локации', 'desc': 'Площадки проведения мероприятий', 'url': 'location_list'},
    {'key': 'organizers', 'icon': '🤝', 'title': 'Организаторы', 'desc': 'Контактные лица организаций', 'url': 'organizer_list'},
    {'key': 'organizations', 'icon': '🏢', 'title': 'Организации', 'desc': 'Партнёры и заказчики мероприятий', 'url': 'organizations_list'},
    {'key': 'requirements', 'icon': '✅', 'title': 'Требования', 'desc': 'Условия допуска волонтёров', 'url': 'requirement_list'},
    {'key': 'categories', 'icon': '🏷️', 'title': 'Категории', 'desc': 'Категории мероприятий', 'url': 'category_list'},
    {'key': 'perks', 'icon': '🎁', 'title': 'Плюшки', 'desc': 'Бонусы волонтёрам за участие', 'url': 'perk_list'},
    {'key': 'constants', 'icon': '🔢', 'title': 'Константы', 'desc': 'Пороги и коэффициенты системы', 'url': 'settings'},
    {'key': 'seasons', 'icon': '🗓️', 'title': 'Сезоны', 'desc': 'Периоды учёта и закрытие сезона', 'url': 'settings'},
    {'key': 'team_leaders', 'icon': '⭐', 'title': 'Тим-лидеры', 'desc': 'Назначение и снятие роли ТЛ', 'url': 'settings'},
    {'key': 'managers', 'icon': '🛡️', 'title': 'Менеджеры', 'desc': 'Назначение и снятие роли менеджера', 'url': 'settings'},
    {'key': 'pgas_template', 'icon': '📄', 'title': 'Шаблон справки ПГАС', 'desc': 'Текст и плейсхолдеры справки ВЦ', 'url': 'settings'},
]

SETTINGS_NATIVE_PANELS = {
    'constants': 'blog/partials/_settings_constants.html',
    'seasons': 'blog/partials/_settings_seasons.html',
    'team_leaders': 'blog/partials/_settings_team_leaders.html',
    'managers': 'blog/partials/_settings_managers.html',
    'pgas_template': 'blog/partials/_settings_pgas_template.html',
}

SETTINGS_DEFAULT_TAB = 'locations'

def _settings_tabs_context(active_tab):
    """Готовит список вкладок с готовыми URL для шелла настроек. URL справочников ведут
    на их list-вьюхи с ?tab= (для истории/копируемой ссылки шелл всё равно перепишет URL
    на /settings/?tab=…), URL нативных панелей — на settings с ?tab=&partial=1."""
    tabs = []
    for tab in SETTINGS_TABS:
        if tab['url'] == 'settings':
            url = reverse('settings') + f"?tab={tab['key']}&partial=1"
        else:
            url = reverse(tab['url'])
        tabs.append({**tab, 'url': url})
    active_url = next((t['url'] for t in tabs if t['key'] == active_tab), tabs[0]['url'])
    return tabs, active_url

@manager_required
def const_edit(request, const_id):
    """Редактирование константы в модалке (как редактирование мероприятия), с
    двухшаговым подтверждением: капча появляется только когда значение реально
    меняется, и генерируется заново при каждой попытке (нельзя переиспользовать
    подсмотренный пример)."""
    const = get_object_or_404(Const, pk=const_id)

    if request.method == 'POST':
        # ВАЖНО: сохранить исходное значение до form.is_valid() — ModelForm._post_clean()
        # присваивает cleaned_data в instance (construct_instance) уже во время валидации,
        # так что после is_valid() const.value уже равен НОВОМУ значению.
        original_value = const.value
        form = ConstForm(request.POST, instance=const)
        value_changed = form.is_valid() and form.cleaned_data['value'] != original_value

        if not value_changed:
            if form.is_valid():
                # Значение не менялось — сохранять и требовать капчу незачем.
                messages.info(request, 'Значение не изменилось.')
                return modal_form_response(request, None, None, success_redirect=reverse('settings'))
        else:
            session_key = f'captcha_const_{const.id}'
            if 'captcha_answer' in request.POST:
                captcha_ok = _check_captcha(request, session_key, request.POST.get('captcha_answer'))
                if captcha_ok:
                    form.save()
                    messages.success(request, f'Константа «{const.name}» обновлена.')
                    return modal_form_response(request, None, None, success_redirect=reverse('settings'))
                messages.error(request, 'Неверный ответ капчи.')
            # Значение меняется — показываем то же значение формы + новую капчу.
            return modal_form_response(
                request, 'blog/const_form.html',
                {
                    'form': form, 'const': const,
                    'show_captcha': True,
                    'captcha_question': _new_captcha(request, session_key),
                },
                partial_template='blog/partials/_const_form_body.html',
            )

    return modal_form_response(
        request, 'blog/const_form.html',
        {'form': ConstForm(instance=const), 'const': const, 'show_captcha': False},
        partial_template='blog/partials/_const_form_body.html',
    )

def _settings_redirect(tab):
    """Редирект после POST-действия настроек — обратно на нужную вкладку хаба
    (/settings/?tab=…), чтобы пользователь остался в том же разделе, а не был выброшен
    на дефолтную вкладку."""
    return redirect(reverse('settings') + f'?tab={tab}')

def _build_role_sections(request, preselect=None):
    """Секции назначения/снятия ролей для панелей «тим-лидеры» и «менеджеры»: на каждую
    роль — форма-пикер, свежая капча и число доступных пользователей. Вынесено, чтобы
    строить только когда реально рендерим панель ролей (а не на каждый заход в настройки).

    preselect: {action: [User, …]} — заранее выбранные пользователи, которые нужно
    восстановить в пикере (напр. после ошибки капчи, чтобы ввод не сбрасывался).
    Передаются в шаблон как JSON [{id,label},…] через section.preselect_json."""
    import json
    role_sections = {}
    for action, (kind, verb) in ROLE_ACTIONS.items():
        session_key = f'captcha_{action}'
        queryset = (
            roles_service.users_without_role(kind) if verb == 'assign'
            else roles_service.users_with_role(kind)
        )
        pre_users = (preselect or {}).get(action) or []
        # Восстановление выбора после ошибки капчи (одноразово, из сессии).
        if not pre_users:
            pre_ids = request.session.pop(f'role_preselect_{action}', None)
            if pre_ids:
                pre_users = list(queryset.filter(id__in=pre_ids))
        role_sections[action] = {
            # prefix обязателен: без него все 4 формы на странице рендерят <select id="id_users">
            # с одинаковым id, и JS chip-виджет находит только первый по document.getElementById.
            'form': RoleUsersForm(queryset=queryset, prefix=action),
            'captcha_question': _new_captcha(request, session_key),
            'users_count': queryset.count(),
            'preselect_json': json.dumps(
                [{'id': u.id, 'label': u.full_name} for u in pre_users],
                ensure_ascii=False,
            ) if pre_users else '',
        }
    return role_sections

@manager_required
def settings_view(request):
    """Хаб настроек. GET без ?partial=1 отдаёт шелл (хедер-кнопки + пустой блок панели,
    который JS сразу подгружает AJAX'ом). GET с ?partial=1&tab=… отдаёт partial нативной
    панели (константы/сезоны/тим-лидеры/менеджеры). POST обрабатывает действия этих
    панелей (добавить/закрыть сезон, назначить/снять роль) и редиректит на свою вкладку."""
    # --- POST-действия панелей ---
    if request.method == 'POST' and request.POST.get('action') == 'add_season':
        season_form = SeasonForm(request.POST)
        if season_form.is_valid():
            season_form.save()
            messages.success(request, 'Сезон добавлен.')
            return _settings_redirect('seasons')
        # Невалидная форма — покажем панель сезонов с ошибками (partial).
        from data_base import data_controller as dc
        return render(request, 'blog/partials/_settings_seasons.html', {
            'seasons': dc.get_seasons(),
            'season_form': season_form,
        })

    if request.method == 'POST' and request.POST.get('action') == 'close_season':
        from blog.services.stats import close_season
        season = get_object_or_404(Season, pk=request.POST.get('season_id'))
        next_season = close_season(season)
        msg = 'Сезон закрыт: churn зафиксирован в истории, сезонные счётчики обнулены.'
        if next_season:
            msg += ' Создан новый бессрочный сезон — задайте дату его окончания.'
        messages.success(request, msg)
        return _settings_redirect('seasons')

    if request.method == 'POST' and request.POST.get('action') == 'save_pgas_template':
        from blog.services.pgas_certificate import (
            EVENTS_BLOCK_START, EVENTS_BLOCK_END, get_template,
        )
        upload = request.FILES.get('docx_file')
        if not upload or not upload.name.lower().endswith('.docx'):
            messages.error(request, 'Загрузите файл шаблона в формате .docx.')
            return _settings_redirect('pgas_template')
        data = upload.read()
        # Проверяем, что в шаблоне есть оба маркера блока мероприятий — иначе
        # перечисление меро не развернётся. Читаем текст docx через python-docx.
        try:
            import io as _io
            from docx import Document
            doc_text = '\n'.join(p.text for p in Document(_io.BytesIO(data)).paragraphs)
        except Exception:
            messages.error(request, 'Не удалось прочитать .docx — файл повреждён или не Word.')
            return _settings_redirect('pgas_template')
        if EVENTS_BLOCK_START not in doc_text or EVENTS_BLOCK_END not in doc_text:
            messages.error(request, f'В шаблоне должны быть строки «{EVENTS_BLOCK_START}» и '
                                    f'«{EVENTS_BLOCK_END}» вокруг блока мероприятий.')
            return _settings_redirect('pgas_template')

        template = get_template()
        template.docx_file = data
        template.filename = upload.name
        template.updated_by = request.user
        template.save(update_fields=['docx_file', 'filename', 'updated_by', 'updated_at'])
        logger.info('Шаблон справки ПГАС обновлён (.docx): by=%s', actor(request.user))
        messages.success(request, 'Шаблон справки ПГАС загружен.')
        return _settings_redirect('pgas_template')

    if request.method == 'POST' and request.POST.get('action') in ROLE_ACTIONS:
        action = request.POST.get('action')
        kind, verb = ROLE_ACTIONS[action]
        session_key = f'captcha_{action}'
        # Роль ТЛ — на вкладке «тим-лидеры», роль менеджера — на «менеджеры».
        role_tab = 'team_leaders' if kind == 'team_lead' else 'managers'

        queryset = (
            roles_service.users_without_role(kind) if verb == 'assign'
            else roles_service.users_with_role(kind)
        )
        role_form = RoleUsersForm(request.POST, queryset=queryset, prefix=action)
        captcha_ok = _check_captcha(request, session_key, request.POST.get('captcha_answer'))

        if not captcha_ok:
            # Неверная капча: НЕ сбрасываем выбор — запоминаем выбранные id в сессии и
            # редиректим на ту же вкладку. Панель при загрузке восстановит их в пикере
            # (data-preselect), менеджер лишь исправит ответ капчи, а не наберёт заново.
            messages.error(request, 'Неверный ответ капчи. Проверьте пример и попробуйте снова.')
            ids = [str(v) for v in (role_form['users'].value() or [])]
            request.session[f'role_preselect_{action}'] = ids
            return _settings_redirect(role_tab)
        elif role_form.is_valid():
            users = list(role_form.cleaned_data['users'])
            if verb == 'assign':
                affected = roles_service.assign_role(kind, users, assigned_by=request.user)
                verb_text = 'назначены'
            else:
                affected = roles_service.revoke_role(kind, users, revoked_by=request.user)
                verb_text = 'сняты с роли'
            role_word = ROLE_LABELS[kind]
            if affected:
                names = ', '.join(u.full_name for u in affected)
                messages.success(request, f'{role_word.capitalize()} {verb_text}: {names} ({len(affected)}).')
            else:
                messages.info(request, 'Выбранные пользователи уже были в этом статусе — изменений нет.')
            return _settings_redirect(role_tab)
        else:
            messages.error(request, 'Выберите хотя бы одного пользователя.')
        return _settings_redirect(role_tab)

    # --- GET: partial панели или шелл ---
    tab = request.GET.get('tab') or SETTINGS_DEFAULT_TAB
    wants_partial = request.GET.get('partial') == '1' or is_ajax(request)

    if wants_partial and tab in SETTINGS_NATIVE_PANELS:
        template = SETTINGS_NATIVE_PANELS[tab]
        from data_base import data_controller as dc
        context = {}
        if tab == 'constants':
            context['consts'] = dc.get_all_consts()
        elif tab == 'seasons':
            context['seasons'] = dc.get_seasons()
            context['season_form'] = SeasonForm()
        elif tab in ('team_leaders', 'managers'):
            context['role_sections'] = _build_role_sections(request)
        elif tab == 'pgas_template':
            from blog.services.pgas_certificate import get_template
            context['pgas_template'] = get_template()
        return render(request, template, context)

    # Шелл хаба: активная вкладка из ?tab= (или дефолт), если такой нет — дефолт.
    if tab not in {t['key'] for t in SETTINGS_TABS}:
        tab = SETTINGS_DEFAULT_TAB
    tabs, active_url = _settings_tabs_context(tab)
    return render(request, 'blog/settings.html', {
        'tabs': tabs,
        'active_tab': tab,
        'active_url': active_url,
    })

@manager_required
def requirement_list(request):
    """Список требований: описание + компактный список тех, кто не соответствует
    (не грузим весь список волонтёров на экран — только тех, кто в исключениях, плюс
    маленькая форма добавления с поиском по select)."""
    from data_base import data_controller as dc
    requirements = dc.requirements_qs().order_by('title')
    sections = []
    for req in requirements:
        exceptions = req.user_exceptions.select_related('user').order_by('-created_at')
        sections.append({
            'requirement': req,
            'exceptions': exceptions,
            'exception_form': RequirementExceptionForm(requirement=req),
        })

    # Панель хаба настроек (см. location_list): AJAX → partial, прямой заход → редирект.
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_requirements.html', {
            'sections': sections,
            'requirement_form': RequirementForm(),
        })
    return redirect(reverse('settings') + '?tab=requirements')

@manager_required
def requirement_create(request):
    form = RequirementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Требование добавлено.')
        return modal_form_response(request, None, None, success_redirect=reverse('settings') + '?tab=requirements')
    return modal_form_response(
        request, 'blog/requirement_form.html',
        {'form': form, 'title': 'Новое требование', 'submit_label': 'Добавить'},
    )

@manager_required
def requirement_edit(request, requirement_id):
    requirement = get_object_or_404(EventRequirement, pk=requirement_id)
    form = RequirementEditForm(request.POST or None, instance=requirement)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Требование обновлено.')
        return modal_form_response(request, None, None, success_redirect=reverse('settings') + '?tab=requirements')
    return modal_form_response(
        request, 'blog/requirement_form.html',
        {'form': form, 'title': f'Редактировать: {requirement.title}', 'submit_label': 'Сохранить'},
    )

@manager_required
def requirement_delete(request, requirement_id):
    requirement = get_object_or_404(EventRequirement, pk=requirement_id)
    if request.method == 'POST':
        requirement.delete()
        messages.success(request, f'Требование «{requirement.title}» удалено.')
    return redirect('requirement_list')

@manager_required
def category_list(request):
    # Панель хаба настроек (см. location_list): AJAX → partial, прямой заход → редирект.
    from data_base import data_controller as dc
    categories = dc.event_categories_qs().order_by('name')
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_categories.html', {'categories': categories})
    return redirect(reverse('settings') + '?tab=categories')

@manager_required
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Категория создана.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('settings') + '?tab=categories',
        )
    return modal_form_response(
        request, 'blog/category_form.html',
        {'form': form, 'title': 'Новая категория'},
    )

@manager_required
def category_edit(request, category_id):
    category = get_object_or_404(EventCategory, pk=category_id)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Категория обновлена.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('settings') + '?tab=categories',
        )
    return modal_form_response(
        request, 'blog/category_form.html',
        {'form': form, 'title': f'Редактировать: {category.name}', 'submit_label': 'Сохранить'},
    )

@manager_required
def category_delete(request, category_id):
    category = get_object_or_404(EventCategory, pk=category_id)
    if request.method == 'POST':
        category.delete()
        messages.success(request, f'Категория «{category.name}» удалена.')
    return redirect(reverse('settings') + '?tab=categories')

@manager_required
def perk_list(request):
    # Панель хаба настроек (см. category_list): AJAX → partial, прямой заход → редирект.
    from data_base import data_controller as dc
    perks = dc.event_perks_qs().order_by('name')
    if is_ajax(request):
        return render(request, 'blog/partials/_settings_perks.html', {'perks': perks})
    return redirect(reverse('settings') + '?tab=perks')

@manager_required
def perk_create(request):
    form = PerkForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Плюшка создана.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('settings') + '?tab=perks',
        )
    return modal_form_response(
        request, 'blog/perk_form.html',
        {'form': form, 'title': 'Новая плюшка'},
    )

@manager_required
def perk_edit(request, perk_id):
    perk = get_object_or_404(EventPerk, pk=perk_id)
    form = PerkForm(request.POST or None, instance=perk)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Плюшка обновлена.')
        return modal_form_response(
            request, None, None,
            success_redirect=reverse('settings') + '?tab=perks',
        )
    return modal_form_response(
        request, 'blog/perk_form.html',
        {'form': form, 'title': f'Редактировать: {perk.name}', 'submit_label': 'Сохранить'},
    )

@manager_required
def perk_delete(request, perk_id):
    perk = get_object_or_404(EventPerk, pk=perk_id)
    if request.method == 'POST':
        perk.delete()
        messages.success(request, f'Плюшка «{perk.name}» удалена.')
    return redirect(reverse('settings') + '?tab=perks')

@manager_required
def requirement_exception_add(request, requirement_id):
    """Отметить волонтёра как НЕ соответствующего требованию (белый список исключений,
    db.md правило 6) — освобождает тим-лидеров от повторной обработки его заявок:
    при подаче на меро с этим требованием заявка сразу уйдёт в резерв."""
    requirement = get_object_or_404(EventRequirement, pk=requirement_id)
    if request.method == 'POST':
        form = RequirementExceptionForm(request.POST, requirement=requirement)
        if form.is_valid():
            form.save()
            messages.success(request, f'{form.instance.user.full_name}: отмечен(а) как не соответствующий(ая) требованию «{requirement.title}».')
        else:
            messages.error(request, 'Не удалось добавить — выберите волонтёра из списка.')
    return redirect('requirement_list')

@manager_required
def requirement_exception_remove(request, exception_id):
    exception = get_object_or_404(dc.user_requirement_exceptions_qs().select_related('user', 'requirement'), pk=exception_id)
    if request.method == 'POST':
        name = exception.user.full_name
        title = exception.requirement.title
        exception.delete()
        messages.success(request, f'{name}: отметка о несоответствии требованию «{title}» снята.')
        return redirect('requirement_list')
    return redirect('requirement_list')
