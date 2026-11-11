"""Формы домена «events». Часть пакета blog.forms (см. README.md).

Формы мероприятий: создание/редактирование меро, смены, комментарии,
оценка. Вспомогательные поля выбора ТЛ/менеджера.

Общие импорты (django.forms, модели) — из ._common.
"""
from ._common import *  # noqa: F401,F403
from django.db import transaction
from blog.models import EventGroup


def _intervals_overlap(start_a, end_a, start_b, end_b):
    """Пересекаются ли два полуинтервала времени [start, end). Смежные (конец одной =
    начало другой) пересечением НЕ считаются — можно ставить смены встык."""
    return start_a < end_b and start_b < end_a


def _shifts_overlap(shifts):
    """shifts — список кортежей (day, start_time, end_time). True, если хотя бы две
    смены в один и тот же день пересекаются по времени. Используется и при создании
    меро (несколько смен разом), и при добавлении/редактировании отдельной смены."""
    for i in range(len(shifts)):
        day_i, start_i, end_i = shifts[i]
        for j in range(i + 1, len(shifts)):
            day_j, start_j, end_j = shifts[j]
            if day_i == day_j and _intervals_overlap(start_i, end_i, start_j, end_j):
                return True
    return False


class TeamLeadChoiceField(forms.ModelMultipleChoiceField):
    """Выбор тим-лидеров: показываем только «Фамилия Имя», без telegram."""
    def label_from_instance(self, obj):
        name = f'{obj.last_name or ""} {obj.first_name or ""}'.strip()
        return name or (obj.telegram_username or str(obj.telegram_id))

class ManagerChoiceField(forms.ModelChoiceField):
    """Выбор ответственного менеджера (ровно один) — та же подпись, что у ТЛ."""
    def label_from_instance(self, obj):
        name = f'{obj.last_name or ""} {obj.first_name or ""}'.strip()
        return name or (obj.telegram_username or str(obj.telegram_id))

class EventGroupForm(forms.ModelForm):
    """Название мероприятия и его менеджеры; роли и позиции не изменяются."""
    managers = TeamLeadChoiceField(
        queryset=dc.active_manager_users_qs(), required=False,
        label='Менеджеры', widget=forms.SelectMultiple,
    )
    workbook = forms.FileField(required=False, label='Загрузить таблицу (.xlsx)', widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))
    google_url = forms.URLField(required=False, label='Ссылка на Google Таблицу', widget=forms.URLInput(attrs={'placeholder': 'https://docs.google.com/spreadsheets/d/…/edit'}))

    class Meta:
        model = EventGroup
        fields = ['title', 'dobro_ru_link', 'managers']
        labels = {'title': 'Название', 'dobro_ru_link': 'Ссылка на Добро.ру'}
        widgets = {'dobro_ru_link': forms.URLInput(attrs={'placeholder': 'https://dobro.ru/…'})}
        help_texts = {'dobro_ru_link': 'Одна ссылка на всё мероприятие: каждая смена каждой позиции учитывается по ней.'}

    def __init__(self, *args, assigned_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assigned_by = assigned_by
        self.prepared_sheet = None

    def clean(self):
        cleaned = super().clean()
        if not self.errors:
            from .event_sheets import prepare_form_sheet
            self.prepared_sheet = prepare_form_sheet(self)
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        group = super().save(commit=False)
        if commit:
            dc.save_event_group(group, list(self.cleaned_data['managers']), assigned_by=self.assigned_by)
            dc.apply_group_dobro_link(group, self.assigned_by)
            # Желающие, записанные раньше названием, получают ссылку на это мероприятие.
            from blog.services.volunteer_wishes import link_wishes_to_group
            link_wishes_to_group(group, self.assigned_by)
            if self.prepared_sheet:
                from blog.services.event_sheets import apply_prepared_sheet
                apply_prepared_sheet(self.assigned_by, group, self.prepared_sheet)
        return group


class EventForm(forms.ModelForm):
    """Форма создания/редактирования мероприятия.

    На этапе создания (cjm-event-lifecycle.md, этап 2) заполняются только: название, описание,
    локация, организация/организатор, категории, ссылки и тип учёта Добро.ру. Поля закрытия/
    пост-меро (`people_helped`, `internal_comment`, `letter`) появляются только при редактировании
    уже существующего меро (`show_closing_fields`), чтобы не засорять форму создания.
    """
    # Мероприятие → функции → позиции (решение 2026-11-11): позиция создаётся внутри
    # одной функции. Сначала функции этого мероприятия, затем общий пул, «＋ новая».
    function = forms.ChoiceField(label='Функция', required=False)
    function_name = forms.CharField(label='Название новой функции', required=False, max_length=100,
                                    widget=forms.TextInput(attrs={'placeholder': 'Например: Организация выдачи пакетов участников'}))
    categories = forms.ModelMultipleChoiceField(
        queryset=dc.event_categories_qs().order_by('name'),
        required=False,
        label='Функции',
        widget=forms.SelectMultiple,
    )
    perks = forms.ModelMultipleChoiceField(
        queryset=dc.event_perks_qs().order_by('name'),
        required=False,
        label='Плюшки',
        widget=forms.SelectMultiple,
    )
    requirements = forms.ModelMultipleChoiceField(
        queryset=dc.requirements_qs().order_by('title'),
        required=False,
        label='Требования к волонтёрам',
        widget=forms.SelectMultiple,
    )
    team_leads = TeamLeadChoiceField(
        # Только пользователи с активной ролью тим-лидера (см. dc.active_team_leader_users_qs:
        # фильтр по id из TeamLeader, а не LEFT JOIN — иначе ложные NULL-совпадения).
        queryset=dc.active_team_leader_users_qs(),
        required=False,
        label='Тим-лидеры',
        widget=forms.SelectMultiple,
    )
    manager = ManagerChoiceField(
        # Только активные менеджеры (managers, revoked_at IS NULL) — тот же паттерн, что у team_leads.
        queryset=dc.active_manager_users_qs(),
        required=False,
        label='Ответственный менеджер',
        widget=forms.Select,
    )

    class Meta:
        model = Event
        fields = [
            # Масштаб, организация, контактное лицо, пост в канале и Добро.ру убраны из
            # UI (2026-11-11); поля модели остаются. Добро.ру — у мероприятия.
            'event_group', 'title', 'description', 'location', 'chat_link',
            'people_helped', 'internal_comment', 'letter',
        ]
        labels = {
            'title': 'Название',
            'description': 'Описание',
            'scale': 'Масштаб позиции',
            'location': 'Локация',
            'chat_link': 'Ссылка на чат',
            'post_in_chanel_link': 'Ссылка на пост в канале',
            'dobro_ru_link': 'Ссылка на Добро.ру',
            'organization': 'Организация',
            'organizer': 'Контактное лицо',
            'people_helped': 'Людей получили помощь',
            'internal_comment': 'Внутренний комментарий',
            'letter': 'Шаблон благодарственного письма',
        }
        widgets = {
            # list → <datalist id="position-pool">: подсказки типовых позиций из пула функций.
            'title': forms.TextInput(attrs={'maxlength': 255, 'placeholder': 'Название позиции — начните вводить, будут подсказки из пула', 'list': 'position-pool', 'autocomplete': 'off'}),
            'description': forms.Textarea(attrs={'rows': 3, 'maxlength': 250, 'placeholder': 'Кратко опишите позицию (до 250 символов)'}),
            'internal_comment': forms.Textarea(attrs={'rows': 3}),
            'chat_link': forms.URLInput(attrs={'placeholder': 'https://t.me/…'}),
            'post_in_chanel_link': forms.URLInput(attrs={'placeholder': 'https://t.me/…'}),
            'dobro_ru_link': forms.URLInput(attrs={'placeholder': 'https://dobro.ru/…'}),
            'people_helped': forms.NumberInput(attrs={'min': 0}),
        }

    # Поля, относящиеся к закрытию/пост-меро — не показываются при создании.
    CLOSING_FIELDS = ('people_helped', 'internal_comment', 'letter')

    def __init__(self, *args, show_closing_fields=False, assigned_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_closing_fields = show_closing_fields
        self.assigned_by = assigned_by
        self.fields['event_group'].queryset = dc.event_groups_qs().order_by('title')
        if not self.instance.pk and not self.initial.get('event_group'):
            self.initial['event_group'] = dc.event_groups_qs().order_by('pk').first()
        # Смены просят только при создании нового меро (правило "нет меро без смен") —
        # при редактировании существующего смены управляются отдельно на event_detail.
        # Несколько смен добавляются прямо в форме создания (chip-виджет на клиенте,
        # см. _event_form_body.html) — JSON-массив приходит в скрытом поле shifts_json,
        # каждый элемент валидируется как отдельная EventShiftForm.
        self.require_shift = not self.instance.pk
        if self.require_shift:
            self.shift_forms = self._build_shift_forms()

        # Пустой вариант "—" для необязательных FK-справочников (иначе Django берёт первый).
        for name in ('organization', 'organizer', 'location', 'letter'):
            if name in self.fields:
                self.fields[name].empty_label = '— не выбрано —'
                self.fields[name].required = False

        # Ранжирование справочников по дате добавления (новые сверху) — чтобы только что
        # созданная через "＋" запись была вверху списка.
        if 'organization' in self.fields:
            self.fields['organization'].queryset = dc.organizations_qs().order_by('-created_at')
        if 'organizer' in self.fields:
            self.fields['organizer'].queryset = dc.organizers_qs().order_by('-id')
        if 'location' in self.fields:
            self.fields['location'].queryset = dc.locations_qs().order_by('-id')

        # Данные для зависимой фильтрации выбора организации/организатора на клиенте:
        # какие организаторы связаны с какой организацией (и наоборот). Выбрал
        # организацию → ниже показываются только связанные организаторы, и наоборот.
        import json
        if 'organization' in self.fields and 'organizer' in self.fields:
            links = dc.organizer_organization_link_pairs()
            self.org_organizer_links_json = json.dumps(
                [{'organization': o, 'organizer': z} for o, z in links]
            )
        else:
            self.org_organizer_links_json = '[]'

        if not show_closing_fields:
            for name in self.CLOSING_FIELDS:
                self.fields.pop(name, None)

        self._setup_function_field()
        self.instance_had_categories = bool(self.instance.pk and dc.event_categories_for_event(self.instance))
        if not self.instance.pk:
            # «+ Функция» = позиция с этим названием: название берётся из функции.
            self.fields['title'].required = False

        if self.instance.pk:
            self.fields['categories'].initial = dc.event_categories_for_event(self.instance)
            self.fields['perks'].initial = dc.event_perks_for_event(self.instance)
            self.fields['requirements'].initial = dc.event_requirements_for_event(self.instance)
            self.fields['team_leads'].initial = dc.event_staff_users(self.instance, 'team_lead')
            managers = dc.event_staff_users(self.instance, 'manager')
            self.fields['manager'].initial = managers[0] if managers else None
        elif self.assigned_by:
            # Создание нового меро — создатель визуально предвыбран ответственным
            # менеджером в пикере (можно сменить прямо здесь же, до сохранения).
            self.fields['manager'].initial = self.assigned_by

    def _setup_function_field(self):
        from blog.services.position_pool import _key
        group_id = self.data.get('event_group') if self.data else None
        group_id = group_id or self.initial.get('event_group') or (self.instance.event_group_id if self.instance.pk else None)
        group_id = getattr(group_id, 'pk', group_id)
        own_names = {_key(d.name) for d in dc.event_directions_qs().filter(event_group_id=group_id)} if group_id else set()
        pool = list(dc.event_functions_qs().prefetch_related('default_categories').order_by('name'))
        own = [(str(c.pk), c.name) for c in pool if _key(c.name) in own_names]
        rest = [(str(c.pk), c.name) for c in pool if _key(c.name) not in own_names]
        choices = [('', '— выберите функцию —')]
        if own:
            choices.append(('Функции мероприятия', own))
        choices += [('Пул функций', rest), ('new', '＋ Новая функция')]
        self.fields['function'].choices = choices
        # Категории по умолчанию каждой функции — для автоподстановки чипов на клиенте.
        defaults = {str(c.pk): ','.join(str(d.pk) for d in c.default_categories.all()) for c in pool}
        self.function_own = [(v, l, defaults[v]) for v, l in own]
        self.function_rest = [(v, l, defaults[v]) for v, l in rest]
        from blog.services.shift_roles import TEAM_LEAD_ROLE, VOLUNTEER_ROLE
        self.function_pools = {int(pk): [TEAM_LEAD_ROLE, VOLUNTEER_ROLE] for pk, _ in own + rest}
        for template in dc.position_templates_qs().order_by('name'):
            self.function_pools.setdefault(template.category_id, [TEAM_LEAD_ROLE, VOLUNTEER_ROLE]).append(template.name)
        self.default_role_pool = [TEAM_LEAD_ROLE, VOLUNTEER_ROLE]
        if self.instance.pk:
            from blog.services.position_pool import position_function
            current = position_function(self.instance)
            if current:
                self.fields['function'].initial = str(current.pk)
        elif self.initial.get('function') and not self.initial.get('title'):
            # Название позиции по умолчанию — название функции (2026-11-11); роли людей
            # внутри смены задаются в таблице набора, а не отдельными позициями.
            chosen = next((name for pk, name in own + rest if pk == str(self.initial['function'])), '')
            self.initial['title'] = chosen

    def clean(self):
        cleaned = super().clean()
        chosen = cleaned.get('function') or ''
        if chosen == 'new':
            if not (cleaned.get('function_name') or '').strip():
                self.add_error('function_name', 'Впишите название новой функции.')
            elif not cleaned.get('title'):
                cleaned['title'] = ' '.join(cleaned['function_name'].split())
            return cleaned
        if chosen:
            cleaned['function_category'] = dc.event_functions_qs().filter(pk=chosen).first()
            if not cleaned.get('title') and cleaned['function_category']:
                cleaned['title'] = cleaned['function_category'].name
        elif self.data and 'function' in self.data and not self.instance.pk:
            self.add_error('function', 'Выберите функцию: позиция создаётся внутри функции мероприятия.')
        return cleaned

    def clean_title(self):
        return (self.cleaned_data.get('title') or '').strip()

    def _save_function(self, event):
        """Функция позиции: связь с пулом + функция в списке мероприятия + название в пул."""
        from blog.services import event_functions
        from blog.services.position_pool import function_category
        chosen = self.cleaned_data.get('function') or ''
        if not chosen:
            return
        category = (function_category(self.cleaned_data.get('function_name'), self.assigned_by) if chosen == 'new'
                    else self.cleaned_data.get('function_category'))
        if category is None:
            return
        dc.set_event_function(event, category)
        if not self.cleaned_data.get('categories') and not self.instance_had_categories:
            # Категории не выбраны (форма без JS, старый клиент) — по умолчанию функции.
            from blog.services.position_pool import apply_default_categories
            apply_default_categories(event, category)
        if event.event_group_id:
            event_functions.add_function(self.assigned_by, event.event_group, category=category) if self.assigned_by else None
        event_functions.remember_position(event, category, self.assigned_by)

    def _build_shift_forms(self):
        """Разбирает JSON-массив смен из скрытого поля `shifts_json` (собирается на
        клиенте chip-виджетом, см. _event_form_body.html) в список EventShiftForm —
        каждая смена валидируется отдельно теми же правилами, что и в event_shift_add."""
        import json
        raw = (self.data.get('shifts_json') if self.data else None) or '[]'
        try:
            rows = json.loads(raw)
        except (ValueError, TypeError):
            rows = []
        forms_list = []
        for i, row in enumerate(rows if isinstance(rows, list) else []):
            data = {
                f'shift-{i}-day': row.get('day', ''),
                f'shift-{i}-start_time': row.get('start_time', ''),
                f'shift-{i}-end_time': row.get('end_time', ''),
                f'shift-{i}-volunteer_needed': row.get('volunteer_needed') or 0,
                f'shift-{i}-recruit_status': 'open',
                f'shift-{i}-location': '',
                f'shift-{i}-role_plan': json.dumps(row.get('role_plan') or []),
            }
            forms_list.append(EventShiftForm(data, prefix=f'shift-{i}'))
        return forms_list

    def is_valid(self):
        valid = super().is_valid()
        if self.require_shift:
            # Хотя бы одна смена обязательна (аналогично обязательному title); каждая
            # добавленная смена дополнительно валидируется своей формой.
            if not self.shift_forms:
                self.add_error(None, 'Добавьте хотя бы одну смену мероприятия.')
                valid = False
            for shift_form in self.shift_forms:
                if not shift_form.is_valid():
                    valid = False
            # Смены одного мероприятия не должны пересекаться по времени в один день
            # (нельзя создать две смены на одно и то же время — это ошибка ввода).
            if valid and _shifts_overlap([
                (f.cleaned_data['day'], f.cleaned_data['start_time'], f.cleaned_data['end_time'])
                for f in self.shift_forms
            ]):
                self.add_error(None, 'Смены мероприятия пересекаются по времени. Проверьте даты и время смен.')
                valid = False
        return valid

    def clean_event_group(self):
        """Старые точки создания без нового поля продолжают работать с первой группой."""
        return (self.cleaned_data.get('event_group') or self.instance.event_group
                or dc.event_groups_qs().order_by('pk').first())

    def save(self, commit=True):
        event = super().save(commit=False)
        # Упрощённая модель: менеджер просто вставляет ссылку на Добро.ру (или оставляет
        # пустой) — kind проставляется автоматически, без выбора shared/unique (db.md 7e
        # по-прежнему хранит это поле, но UI его больше не показывает).
        group = self.cleaned_data.get('event_group')
        if group is not None and group.dobro_ru_link:
            event.dobro_ru_link, event.dobro_ru_shared_link = group.dobro_ru_link, None
        if event.dobro_ru_link_kind != 'shared':
            event.dobro_ru_link_kind = 'unique' if event.dobro_ru_link else 'none'
        if commit:
            event.save()
            self._save_categories(event)
            self._save_function(event)
            self._save_perks(event)
            self._save_requirements(event)
            self._save_team_leads(event)
            self._save_manager(event)
            self._link_org_and_organizer(event)
            if self.require_shift:
                for shift_form in self.shift_forms:
                    shift = shift_form.save(commit=False)
                    shift.event = event
                    shift.save()
            # Тим-лидеры — сразу в таблицу набора каждой смены с ролью «Тим-лидер».
            from blog.services.shift_roles import sync_team_leads
            sync_team_leads(event, self.assigned_by)
        return event

    def _save_categories(self, event):
        selected = list(self.cleaned_data.get('categories') or [])
        dc.sync_event_categories(event, selected)

    def _save_perks(self, event):
        selected = list(self.cleaned_data.get('perks') or [])
        dc.sync_event_perks(event, selected)

    def _save_requirements(self, event):
        selected = list(self.cleaned_data.get('requirements') or [])
        dc.sync_event_requirements(event, selected)

    def _save_team_leads(self, event):
        """Приводит назначения тим-лидеров к ровно выбранному набору пользователей.

        Мероприятие без явно назначенного тим-лидера получает тим-лидером по
        умолчанию самого создающего менеджера (правило "нет меро без ТЛ") — только
        при создании; при редактировании пустой выбор просто снимает всех ТЛ, как раньше.
        """
        selected = list(self.cleaned_data.get('team_leads') or [])
        if not selected and self.require_shift and self.assigned_by:
            selected = [self.assigned_by]
        selected_ids = {u.id for u in selected}
        dc.prune_event_staff(event, 'team_lead', selected_ids)
        for user in selected:
            created = dc.add_event_staff(event, user, 'team_lead')
            if not dc.has_active_team_leader_role(user):
                dc.create_team_leader_role(user, assigned_by=self.assigned_by)
                from blog.services.notifications import notify_became_team_leader
                notify_became_team_leader(user)
            if created:
                from blog.services.notifications import notify_assigned_to_event
                notify_assigned_to_event(user, event)

    def _link_org_and_organizer(self, event):
        """Если менеджер указал и организацию, и организатора — закрепляем их связь
        (OrganizerOrganizationLink), если её ещё нет. Так выбранная при создании меро
        пара сразу становится «связанной» и в дальнейшем предлагается друг для друга
        в зависимой фильтрации выбора."""
        organization = self.cleaned_data.get('organization')
        organizer = self.cleaned_data.get('organizer')
        if organization and organizer:
            dc.get_or_create_organizer_organization_link(organizer, organization)

    def _save_manager(self, event):
        """Ровно один ответственный менеджер. Без явного выбора при СОЗДАНИИ —
        назначается создатель (тот же принцип, что у ТЛ); при редактировании пустой
        выбор снимает менеджера (на форме поле визуально предвыбрано создателем/
        текущим менеджером, так что случайно "снять" можно только явной очисткой)."""
        selected = self.cleaned_data.get('manager')
        if not selected and self.require_shift and self.assigned_by:
            selected = self.assigned_by
        dc.prune_event_manager(event, selected)
        if selected:
            dc.add_event_staff(event, selected, 'manager')

class EventShiftForm(forms.ModelForm):
    """Смена мероприятия: одна дата + время начала и окончания (без дат внутри времени).

    Модель хранит start_time/end_time как DateTimeField, но пользователю мы показываем
    отдельную дату и два поля времени, а склеиваем их в datetime уже при сохранении.
    """
    day = forms.DateField(
        label='Дата',
        widget=forms.DateInput(attrs={'type': 'text', 'data-datepicker': '', 'autocomplete': 'off'}, format='%Y-%m-%d'),
    )
    start_time = forms.TimeField(
        label='Время начала',
        widget=forms.TimeInput(attrs={'type': 'text', 'data-timepicker': '', 'autocomplete': 'off'}, format='%H:%M'),
    )
    end_time = forms.TimeField(
        label='Время окончания',
        widget=forms.TimeInput(attrs={'type': 'text', 'data-timepicker': '', 'autocomplete': 'off'}, format='%H:%M'),
    )
    # План ролей смены (2026-11-11): JSON [[роль, n], …] из редактора [data-role-plan];
    # пусто — 1 тим-лидер и остальные волонтёры.
    role_plan = forms.CharField(required=False, widget=forms.HiddenInput(attrs={'data-role-plan-json': ''}))

    class Meta:
        model = EventShift
        # start_time/end_time НЕ включаем в model-поля: в модели это DateTimeField, а на форме —
        # объявленные выше TimeField. Если оставить их в Meta.fields, ModelForm при _post_clean
        # присвоит объект time в DateTimeField и упадёт на to_python. Склеиваем в save().
        fields = ['day', 'volunteer_needed', 'recruit_status', 'location']
        labels = {
            'volunteer_needed': 'Нужно волонтёров',
            'recruit_status': 'Набор на смену',
            'location': 'Локация',
        }
        widgets = {
            # min=1 — на смену не может требоваться 0 волонтёров (иначе набор
            # автоматически считается "укомплектованным" и смена бессмысленна).
            # list="volunteer-needed-options" — нативный HTML5 datalist: можно выбрать
            # готовое число из списка (1..200) или ввести своё вручную, без отдельного
            # JS-компонента (единственный такой combobox в проекте, см. datalist в
            # _event_shift_form_body.html).
            'volunteer_needed': forms.NumberInput(attrs={'min': 1, 'list': 'volunteer-needed-options'}),
        }

    def __init__(self, *args, event=None, **kwargs):
        # `event` передаётся при добавлении/редактировании отдельной смены — по нему
        # проверяем пересечение по времени с уже существующими сменами того же меро.
        # (При создании меро несколько смен проверяются в EventForm.is_valid.)
        self.overlap_event = event
        super().__init__(*args, **kwargs)
        self.fields['location'].queryset = dc.locations_qs().order_by('-id')
        from blog.services import shift_roles
        self.role_pool = shift_roles.role_pool(event) if event is not None else shift_roles.role_pool()
        if self.instance and self.instance.pk and self.instance.role_plan:
            import json
            self.initial.setdefault('role_plan', json.dumps(self.instance.role_plan, ensure_ascii=False))
        if self.instance and self.instance.pk:
            # При редактировании существующего дня разложить datetime обратно на дату и время.
            if self.instance.start_time:
                start = timezone.localtime(self.instance.start_time)
                self.initial.setdefault('day', start.date())
                self.initial.setdefault('start_time', start.time())
            if self.instance.end_time:
                self.initial.setdefault('end_time', timezone.localtime(self.instance.end_time).time())
        else:
            # Новая смена — типовые часы мероприятия по умолчанию (10:00-18:00) и
            # сегодняшняя дата, чтобы не заполнять вручную каждый раз (календарь и
            # так визуально показывает сегодня как выбранный день).
            self.initial.setdefault('day', timezone.localdate())
            self.initial.setdefault('start_time', time(10, 0))
            self.initial.setdefault('end_time', time(18, 0))

    def clean_volunteer_needed(self):
        value = self.cleaned_data.get('volunteer_needed')
        if value is None or value < 1:
            raise forms.ValidationError('Укажите, сколько волонтёров нужно на смену (не менее 1).')
        return value

    def clean_role_plan(self):
        import json
        try:
            raw = json.loads(self.cleaned_data.get('role_plan') or '[]')
        except ValueError:
            raw = []
        return raw if isinstance(raw, list) else []

    def clean(self):
        cleaned = super().clean()
        day = cleaned.get('day')
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if start and end and end <= start:
            self.add_error('end_time', 'Время окончания должно быть позже времени начала.')
        # Пересечение с другими сменами того же меро в тот же день (add/edit одной смены).
        if self.overlap_event is not None and day and start and end:
            others = self.overlap_event.shifts.filter(day=day)
            if self.instance and self.instance.pk:
                others = others.exclude(pk=self.instance.pk)
            for other in others:
                o_start = timezone.localtime(other.start_time).time()
                o_end = timezone.localtime(other.end_time).time()
                if _intervals_overlap(start, end, o_start, o_end):
                    self.add_error(
                        None,
                        'Смена пересекается по времени с уже существующей сменой этого '
                        'мероприятия в тот же день.'
                    )
                    break
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        day = self.cleaned_data['day']
        tz = timezone.get_current_timezone()
        instance.day = day
        instance.start_time = timezone.make_aware(
            datetime.combine(day, self.cleaned_data['start_time']), tz
        )
        instance.end_time = timezone.make_aware(
            datetime.combine(day, self.cleaned_data['end_time']), tz
        )
        from blog.services.shift_roles import normalize_role_plan
        instance.role_plan = normalize_role_plan(self.cleaned_data.get('role_plan'), instance.volunteer_needed)
        if commit:
            instance.save()
            # При изменении времени смены часы уже проставленной явки должны стать
            # ровно как в смене (длительность смены). Пересчитываем только присутствовавших
            # (attended) — у отсутствовавших часы 0 и меняться не должны. Затрагиваем
            # только тех, кому НЕ правили часы вручную тим-лидером (hours_overridden),
            # чтобы не затирать ручную корректировку.
            self._recalc_participation_hours(instance)
        return instance

    @staticmethod
    def _recalc_participation_hours(shift):
        from blog.services.stats import recalc_user_aggregates

        duration_hours = max(0, round((shift.end_time - shift.start_time).total_seconds() / 3600))
        affected = shift.participations.filter(status='attended', hours_overridden=False)
        users = list({p.user for p in affected})
        affected.update(hours=duration_hours)
        for user in users:
            recalc_user_aggregates(user)

class EventCommentForm(forms.ModelForm):
    """Комментарий к мероприятию (менеджеры/тим-лидеры) — в UI показывается
    без подписи автора, только текст и дата."""
    class Meta:
        model = EventComment
        fields = ['text']
        labels = {'text': 'Комментарий'}
        widgets = {'text': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Заметка по мероприятию…'})}

class EventFeedbackForm(forms.ModelForm):
    class Meta:
        model = EventFeedback
        fields = ['rating', 'comment']
        labels = {
            'rating': 'Оценка (0-10)',
            'comment': 'Комментарий',
        }
        widgets = {
            'rating': forms.NumberInput(attrs={'min': 0, 'max': 10}),
            'comment': forms.Textarea(attrs={'rows': 3}),
        }


class EventFunctionForm(forms.Form):
    """Добавить функцию в мероприятие: из пула (названия из ФиП) или новую."""
    category = forms.ModelChoiceField(queryset=dc.event_functions_qs().order_by('name'), required=False,
                                      label='Функция из пула', empty_label='— новая функция —')
    name = forms.CharField(label='Или название новой функции', required=False, max_length=100)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('category') and not (cleaned.get('name') or '').strip():
            raise forms.ValidationError('Выберите функцию из пула или впишите название новой.')
        return cleaned

