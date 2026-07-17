from datetime import datetime, time

from django import forms
from django.utils import timezone
from .models import (
    Event, EventComment, EventShift, Participation, Application, UserComment, EventFeedback,
    Const, Manager, Season, Organization, Organizer, User, EventStaff, Location,
    EventCategory, EventCategoryMap, TeamLeader, ExternalExperience,
    EventRequirement, EventRequirementMap, UserRequirementException,
)


class LoginForm(forms.Form):
    login = forms.CharField(label='Логин', max_length=50)
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput)


class RegisterForm(forms.Form):
    """Самостоятельная веб-регистрация без Telegram (создаёт аккаунт с временным
    служебным telegram_id, как import:* у Excel-импорта — см. register_view).

    Обязательны: ФИО (Фамилия/Имя, Отчество опционально), Telegram, телефон, дата
    рождения, логин и пароль — остальные поля профиля пользователь донастроит позже.
    Если по ФИО+Telegram+телефону находится уже существующий пользователь (заведён
    ботом/импортом ранее) — НЕ блокируем регистрацию: создаём новый веб-аккаунт и
    просим подтвердить личность через бота для последующего объединения профилей
    (см. register_view, TODO мерджа — пока только плашка-предупреждение)."""
    last_name = forms.CharField(label='Фамилия', max_length=100)
    first_name = forms.CharField(label='Имя', max_length=100)
    middle_name = forms.CharField(label='Отчество', max_length=100, required=False)
    telegram_username = forms.CharField(label='Telegram', max_length=100)
    phone = forms.CharField(label='Номер телефона', max_length=20)
    birthday = forms.DateField(
        label='Дата рождения',
        widget=forms.DateInput(
            attrs={'type': 'text', 'data-datepicker': '', 'data-dp-default-years-ago': '18', 'autocomplete': 'off'},
            format='%Y-%m-%d',
        ),
    )
    login = forms.CharField(label='Логин', max_length=50)
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Повторите пароль', widget=forms.PasswordInput)

    def clean_telegram_username(self):
        value = (self.cleaned_data.get('telegram_username') or '').strip()
        return value.lstrip('@').strip()

    def clean_login(self):
        value = (self.cleaned_data.get('login') or '').strip()
        if User.objects.filter(login=value).exists():
            raise forms.ValidationError('Этот логин уже занят — выберите другой.')
        return value

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        password2 = cleaned.get('password2')
        if password and password2 and password != password2:
            self.add_error('password2', 'Пароли не совпадают.')
        return cleaned


class QuickLocationForm(forms.ModelForm):
    """Мини-форма быстрого создания локации прямо из формы мероприятия (без ухода со страницы)."""
    class Meta:
        model = Location
        fields = ['name', 'map_link']
        labels = {'name': 'Название локации', 'map_link': 'Ссылка на карту'}


class LocationForm(forms.ModelForm):
    """Полноценное редактирование локации (список локаций)."""
    class Meta:
        model = Location
        fields = ['name', 'map_link', 'description']
        labels = {'name': 'Название локации', 'map_link': 'Ссылка на карту', 'description': 'Описание'}
        widgets = {
            'map_link': forms.URLInput(attrs={'placeholder': 'https://yandex.ru/maps/…'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class QuickOrganizationForm(forms.ModelForm):
    """Мини-форма быстрого создания организации прямо из формы мероприятия."""
    class Meta:
        model = Organization
        fields = ['name', 'description']
        labels = {'name': 'Название организации', 'description': 'Описание'}
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


class QuickOrganizerForm(forms.ModelForm):
    """Мини-форма быстрого создания контактного лица прямо из формы мероприятия."""
    class Meta:
        model = Organizer
        fields = ['first_name', 'last_name', 'phone', 'telegram_username']
        labels = {
            'first_name': 'Имя', 'last_name': 'Фамилия',
            'phone': 'Телефон', 'telegram_username': 'Telegram',
        }


class QuickVolunteerForm(forms.Form):
    """Мини-форма создания волонтёра менеджером (кнопка «Создать нового» в блоке
    «Добавить волонтёра»): заполняется как профиль пришедшего «извне» человека (как при
    Excel-импорте). Обязательны фамилия, имя и ХОТЯ БЫ ОДИН способ связи — Telegram ИЛИ
    телефон. Новый пользователь сразу попадает в пул выбора волонтёров."""
    first_name = forms.CharField(label='Имя', max_length=100)
    last_name = forms.CharField(label='Фамилия', max_length=100)
    phone = forms.CharField(label='Телефон', max_length=20, required=False)
    telegram_username = forms.CharField(label='Telegram', max_length=100, required=False)

    def clean(self):
        cleaned = super().clean()
        phone = (cleaned.get('phone') or '').strip()
        tg = (cleaned.get('telegram_username') or '').strip()
        if not phone and not tg:
            raise forms.ValidationError('Укажите способ связи — Telegram или телефон (хотя бы одно).')
        return cleaned


class QuickCategoryForm(forms.ModelForm):
    """Мини-форма быстрого создания категории мероприятия прямо из формы мероприятия."""
    class Meta:
        model = EventCategory
        fields = ['name']
        labels = {'name': 'Название категории'}


class QuickRequirementForm(forms.ModelForm):
    """Мини-форма быстрого создания требования прямо из формы мероприятия. check_type
    не запрашивается — быстро создаются только обычные («вручную проверяемые») требования;
    автоматическая проверка по возрасту настраивается отдельно на странице требований."""
    class Meta:
        model = EventRequirement
        fields = ['title', 'description']
        labels = {'title': 'Название требования', 'description': 'Описание'}


class RequirementForm(forms.ModelForm):
    """Создание требования на странице «Требования» — тип проверки в форме не
    показывается, новые требования всегда создаются как 'manual' (значение по
    умолчанию в модели). Автоматическая проверка по возрасту («18+») — служебный тип,
    заведённый через seed-миграцию; переключать его на другое требование через это
    UI не предполагается (см. RequirementEditForm)."""
    class Meta:
        model = EventRequirement
        fields = ['title', 'description']
        labels = {'title': 'Название', 'description': 'Описание'}
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


class RequirementEditForm(RequirementForm):
    """Редактирование существующего требования — в отличие от формы создания, здесь
    check_type виден и редактируем (на случай, если понадобится вручную перенести
    автопроверку возраста на другое требование)."""
    class Meta(RequirementForm.Meta):
        fields = ['title', 'description', 'check_type']
        labels = {**RequirementForm.Meta.labels, 'check_type': 'Тип проверки'}


class RequirementExceptionForm(forms.ModelForm):
    """Добавление волонтёра в список «не соответствует требованию». Пользователь НЕ
    выбирается через серверный <select> (при тысячах волонтёров рендер queryset'а в
    <option> — сам по себе главная причина медленной загрузки страницы требований).
    Вместо этого — скрытое числовое поле `user`, заполняемое единым JS-виджетом выбора
    в remote-режиме (data-chip-select data-select-remote="users", base.html): список
    пользователей грузится AJAX-запросом (см. users_picker_data) с ранжированием и
    лимитом, кэшируется на клиенте и переиспользуется всеми такими виджетами страницы."""
    user = forms.IntegerField(widget=forms.HiddenInput, label='Волонтёр')

    class Meta:
        model = UserRequirementException
        fields = ['reason']
        labels = {'reason': 'Причина'}
        widgets = {'reason': forms.TextInput(attrs={'placeholder': 'Необязательно'})}

    def __init__(self, *args, requirement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.requirement = requirement

    def clean_user(self):
        user_id = self.cleaned_data['user']
        user = User.objects.filter(pk=user_id).first()
        if not user:
            raise forms.ValidationError('Выберите волонтёра из списка.')
        if self.requirement is not None and UserRequirementException.objects.filter(
            user=user, requirement=self.requirement
        ).exists():
            raise forms.ValidationError('Этот волонтёр уже отмечен как несоответствующий требованию.')
        return user

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.user = self.cleaned_data['user']
        instance.requirement = self.requirement
        if commit:
            instance.save()
        return instance


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


class EventForm(forms.ModelForm):
    """Форма создания/редактирования мероприятия.

    На этапе создания (cjm-event-lifecycle.md, этап 2) заполняются только: название, описание,
    локация, организация/организатор, категории, ссылки и тип учёта Добро.ру. Поля закрытия/
    пост-меро (`people_helped`, `internal_comment`, `letter`) появляются только при редактировании
    уже существующего меро (`show_closing_fields`), чтобы не засорять форму создания.
    """
    categories = forms.ModelMultipleChoiceField(
        queryset=EventCategory.objects.order_by('name'),
        required=False,
        label='Категории',
        widget=forms.SelectMultiple,
    )
    requirements = forms.ModelMultipleChoiceField(
        queryset=EventRequirement.objects.order_by('title'),
        required=False,
        label='Требования к волонтёрам',
        widget=forms.SelectMultiple,
    )
    team_leads = TeamLeadChoiceField(
        # Только пользователи с активной ролью тим-лидера (таблица team_leaders, revoked_at IS NULL).
        # ВАЖНО: filter(team_leader_roles__revoked_at__isnull=True) через LEFT JOIN даёт
        # ложные совпадения — у пользователей БЕЗ единой записи в team_leaders revoked_at
        # тоже NULL из-за LEFT JOIN, и "IS NULL" совпадает. Поэтому фильтруем по id из
        # TeamLeader напрямую.
        queryset=User.objects.filter(
            id__in=TeamLeader.objects.filter(revoked_at__isnull=True).values('user_id')
        ).order_by('last_name', 'first_name'),
        required=False,
        label='Тим-лидеры',
        widget=forms.SelectMultiple,
    )
    manager = ManagerChoiceField(
        # Только активные менеджеры (managers, revoked_at IS NULL) — тот же паттерн
        # фильтрации, что у team_leads (filter по id из Manager, не LEFT JOIN).
        queryset=User.objects.filter(
            id__in=Manager.objects.filter(revoked_at__isnull=True).values('user_id')
        ).order_by('last_name', 'first_name'),
        required=False,
        label='Ответственный менеджер',
        widget=forms.Select,
    )

    class Meta:
        model = Event
        fields = [
            'title', 'description', 'scale',
            'organization', 'organizer', 'location',
            'chat_link', 'post_in_chanel_link', 'dobro_ru_link',
            'people_helped', 'internal_comment', 'letter',
        ]
        labels = {
            'title': 'Название',
            'description': 'Описание',
            'scale': 'Масштаб мероприятия',
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
            'title': forms.TextInput(attrs={'maxlength': 255, 'placeholder': 'Название мероприятия'}),
            'description': forms.Textarea(attrs={'rows': 3, 'maxlength': 250, 'placeholder': 'Кратко опишите мероприятие (до 250 символов)'}),
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
            self.fields['organization'].queryset = Organization.objects.order_by('-created_at')
        if 'organizer' in self.fields:
            self.fields['organizer'].queryset = Organizer.objects.order_by('-id')
        if 'location' in self.fields:
            self.fields['location'].queryset = Location.objects.order_by('-id')

        if not show_closing_fields:
            for name in self.CLOSING_FIELDS:
                self.fields.pop(name, None)

        if self.instance.pk:
            self.fields['categories'].initial = EventCategory.objects.filter(
                event_map__event=self.instance
            )
            self.fields['requirements'].initial = EventRequirement.objects.filter(
                event_map__event=self.instance
            )
            self.fields['team_leads'].initial = User.objects.filter(
                staff_assignments__event=self.instance,
                staff_assignments__staff_role='team_lead',
            )
            self.fields['manager'].initial = User.objects.filter(
                staff_assignments__event=self.instance,
                staff_assignments__staff_role='manager',
            ).first()
        elif self.assigned_by:
            # Создание нового меро — создатель визуально предвыбран ответственным
            # менеджером в пикере (можно сменить прямо здесь же, до сохранения).
            self.fields['manager'].initial = self.assigned_by

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

    def save(self, commit=True):
        event = super().save(commit=False)
        # Упрощённая модель: менеджер просто вставляет ссылку на Добро.ру (или оставляет
        # пустой) — kind проставляется автоматически, без выбора shared/unique (db.md 7e
        # по-прежнему хранит это поле, но UI его больше не показывает).
        event.dobro_ru_link_kind = 'unique' if event.dobro_ru_link else 'none'
        if commit:
            event.save()
            self._save_categories(event)
            self._save_requirements(event)
            self._save_team_leads(event)
            self._save_manager(event)
            if self.require_shift:
                for shift_form in self.shift_forms:
                    shift = shift_form.save(commit=False)
                    shift.event = event
                    shift.save()
        return event

    def _save_categories(self, event):
        selected = self.cleaned_data.get('categories', EventCategory.objects.none())
        EventCategoryMap.objects.filter(event=event).exclude(category__in=selected).delete()
        for category in selected:
            EventCategoryMap.objects.get_or_create(event=event, category=category)

    def _save_requirements(self, event):
        selected = self.cleaned_data.get('requirements', EventRequirement.objects.none())
        EventRequirementMap.objects.filter(event=event).exclude(requirement__in=selected).delete()
        for requirement in selected:
            EventRequirementMap.objects.get_or_create(event=event, requirement=requirement)

    def _save_team_leads(self, event):
        """Приводит назначения тим-лидеров к ровно выбранному набору пользователей.

        Мероприятие без явно назначенного тим-лидера получает тим-лидером по
        умолчанию самого создающего менеджера (правило "нет меро без ТЛ") — только
        при создании; при редактировании пустой выбор просто снимает всех ТЛ, как раньше.
        """
        selected = list(self.cleaned_data.get('team_leads', User.objects.none()))
        if not selected and self.require_shift and self.assigned_by:
            selected = [self.assigned_by]
        selected_ids = {u.id for u in selected}
        event.staff.filter(staff_role='team_lead').exclude(user_id__in=selected_ids).delete()
        for user in selected:
            _, created = EventStaff.objects.get_or_create(event=event, user=user, staff_role='team_lead')
            if not TeamLeader.objects.filter(user=user, revoked_at__isnull=True).exists():
                TeamLeader.objects.create(user=user, assigned_by=self.assigned_by)
                from blog.services.notifications import notify_became_team_leader
                notify_became_team_leader(user)
            if created:
                from blog.services.notifications import notify_assigned_to_event
                notify_assigned_to_event(user, event)

    def _save_manager(self, event):
        """Ровно один ответственный менеджер. Без явного выбора при СОЗДАНИИ —
        назначается создатель (тот же принцип, что у ТЛ); при редактировании пустой
        выбор снимает менеджера (на форме поле визуально предвыбрано создателем/
        текущим менеджером, так что случайно "снять" можно только явной очисткой)."""
        selected = self.cleaned_data.get('manager')
        if not selected and self.require_shift and self.assigned_by:
            selected = self.assigned_by
        event.staff.filter(staff_role='manager').exclude(user=selected).delete()
        if selected:
            EventStaff.objects.get_or_create(event=event, user=selected, staff_role='manager')


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
        self.fields['location'].queryset = Location.objects.order_by('-id')
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
        from blog.models import Participation
        from blog.services.stats import recalc_user_aggregates

        duration_hours = max(0, round((shift.end_time - shift.start_time).total_seconds() / 3600))
        affected = shift.participations.filter(status='attended', hours_overridden=False)
        users = list({p.user for p in affected})
        affected.update(hours=duration_hours)
        for user in users:
            recalc_user_aggregates(user)


class ParticipationForm(forms.ModelForm):
    class Meta:
        model = Participation
        fields = ['status', 'hours', 'full_shift']
        labels = {
            'status': 'Статус явки',
            'hours': 'Часы',
            'full_shift': 'Полная смена',
        }
        widgets = {
            'hours': forms.NumberInput(attrs={'min': 0}),
        }


class ShiftMultipleSelect(forms.SelectMultiple):
    """Select для выбора смен, где у каждого <option> проставлен `data-closed="1"`,
    если набор на эту смену закрыт — JS (initCategoryChips) красит такой chip серым,
    но смена остаётся кликабельной (заявка на неё просто сразу уйдёт в резерв)."""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        # value приходит как ModelChoiceIteratorValue (Django 4+), не голым pk — берём
        # обёрнутое значение через .value перед использованием в фильтре.
        raw_value = value.value if hasattr(value, 'value') else value
        shift = self.choices.queryset.filter(pk=raw_value).first() if raw_value else None
        if shift and shift.recruit_status != 'open':
            option['attrs']['data-closed'] = '1'
        return option


class ApplicationForm(forms.ModelForm):
    """Заявка на участие через веб (в отличие от Excel-импорта): ФИО/Telegram/телефон
    система уже знает из профиля авторизованного пользователя, поэтому их не спрашивает —
    остаётся выбрать мероприятие и смены.

    Выбор смен — множественный (чипы, как категории у мероприятия): пул вариантов —
    смены, привязанные к выбранному мероприятию с открытым набором. Если у меро всего
    одна смена — выбирать нечего, подаём сразу на неё.
    """
    selected_shifts = forms.ModelMultipleChoiceField(
        queryset=EventShift.objects.none(),
        required=False,
        label='Смены',
        widget=ShiftMultipleSelect,
    )

    class Meta:
        model = Application
        fields = ['event', 'functions', 'role_in_event']
        labels = {
            'event': 'Мероприятие',
            'functions': 'Функция',
            'role_in_event': 'Роль',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.applicant = user
        # Прошедшие мероприятия с ещё открытыми сменами закрываем лениво прямо тут —
        # это самое надёжное место: форма подачи заявки открывается чаще всего и должна
        # гарантированно не предлагать прошедшие меро (нет отдельного планировщика задач).
        for event in Event.objects.filter(shifts__recruit_status='open').distinct():
            event.close_recruit_if_passed()
        # Подать заявку можно на любое ОПУБЛИКОВАННОЕ меро (published_at задан), у
        # которого есть хотя бы одна смена, которая ещё не началась — даже если набор
        # на все смены уже закрыт (такая заявка просто сразу уходит в резерв, см.
        # application_create), но НЕ на меро, которое уже закончилось целиком.
        now = timezone.now()
        self.fields['event'].queryset = Event.objects.filter(
            published_at__isnull=False, shifts__start_time__gt=now,
        ).distinct().order_by('-created_at')

        # Пул смен для чипов — только смены выбранного меро, которые ещё не начались
        # (открытые и закрытые по набору — закрытая смена всё ещё выбираема, просто
        # заявка на неё сразу пойдёт в резерв; прошедшие/начавшиеся не предлагаются).
        event = self.instance.event if self.instance and self.instance.pk else None
        if 'event' in self.data:
            try:
                event = Event.objects.get(pk=self.data.get('event'))
            except (Event.DoesNotExist, ValueError, TypeError):
                event = None
        if event:
            self.fields['selected_shifts'].queryset = event.shifts.filter(
                start_time__gt=now
            ).order_by('day')
        if self.instance and self.instance.pk:
            self.initial.setdefault('selected_shifts', self.instance.selected_shifts.all())
            # При редактировании существующей заявки мероприятие не меняем — только
            # смены/функцию/роль (иначе теряется смысл "отредактировать свою заявку").
            self.fields['event'].disabled = True


class ApplicationCancelForm(forms.Form):
    """Отмена заявки волонтёром — причина обязательна (доступно только пока до
    мероприятия осталось больше const.late_cancel_hours, проверяется во view)."""
    reason = forms.CharField(
        label='Подскажите, пожалуйста, почему вы отказываетесь от участия — нам это поможет',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Например: изменились планы, не подхожу по времени и т.п.'}),
    )


class ProfileForm(forms.ModelForm):
    """Личный кабинет: редактирование своих данных пользователем. Обязательны для
    подачи заявки — ФИО (имя), Telegram и телефон (см. roles.account_is_complete);
    остальное (юзернейм для системы, почта, дата рождения, о себе, ссылка на ВК) —
    по желанию.

    Telegram-username вводится вручную, как обычное поле: пользователь указывает свой
    ник сам. (Раньше он подтягивался только при входе через бота; теперь ограничение
    снято — при входе через бот username по-прежнему подставляется автоматически, но
    веб-пользователь может ввести/поправить его руками.)

    Дата рождения — как и везде в проекте, красивый календарь (data-datepicker), а не
    нативный type=date."""
    first_name = forms.CharField(label='Имя', max_length=100, required=True)
    last_name = forms.CharField(label='Фамилия', max_length=100, required=False)
    middle_name = forms.CharField(label='Отчество', max_length=100, required=False)

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'middle_name', 'system_username',
            'telegram_username', 'phone', 'email', 'birthday', 'gender', 'about', 'VK_username',
            'faculty', 'education_program', 'admission_year',
        ]
        widgets = {
            'birthday': forms.DateInput(
                # data-dp-default-years-ago="18" — если дата ещё не указана, календарь
                # сразу открывается и предзаполняется «сегодня минус 18 лет» (средний
                # возраст волонтёра), а не сегодняшним днём, откуда до нужного года
                # пришлось бы листать вручную.
                attrs={'type': 'text', 'data-datepicker': '', 'data-dp-default-years-ago': '18', 'autocomplete': 'off'},
                format='%Y-%m-%d',
            ),
            'about': forms.Textarea(attrs={'rows': 3}),
            'admission_year': forms.NumberInput(attrs={'min': 2000, 'max': 2100}),
        }
        labels = {
            'system_username': 'Юзернейм для системы',
            'telegram_username': 'Telegram',
            'phone': 'Номер телефона',
            'email': 'Почта',
            'birthday': 'Дата рождения',
            'gender': 'Пол',
            'about': 'О себе',
            'VK_username': 'Ссылка на ВК',
            'faculty': 'Факультет',
            'education_program': 'Образовательная программа (ОП)',
            'admission_year': 'Год поступления',
        }
        help_texts = {
            'telegram_username': 'Ваш ник в Telegram (можно с @ или без).',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Обязательные для подачи заявки поля помечаем required на форме — визуально
        # (звёздочка) и на уровне валидации.
        self.fields['phone'].required = True
        self.fields['telegram_username'].required = True

    def clean_telegram_username(self):
        # Нормализуем: убираем ведущий @ и пробелы, чтобы в БД лежал чистый username.
        value = (self.cleaned_data.get('telegram_username') or '').strip()
        return value.lstrip('@').strip()

    def clean_first_name(self):
        value = (self.cleaned_data.get('first_name') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите имя — оно обязательно для подачи заявки.')
        return value

    def save(self, commit=True):
        user = super().save(commit=False)
        # Заполненная анкета → registration_status='registered' (после входа через
        # Telegram он оставался 'guest').
        if (user.first_name or '').strip():
            user.registration_status = 'registered'
        if commit:
            user.save()
        return user


# Обратная совместимость: часть кода/шаблонов ещё ссылается на старое имя.
ProfileCompletionForm = ProfileForm


class ExternalExperienceForm(forms.ModelForm):
    """Внешнее волонтёрское мероприятие (раздел «Мой опыт») — хранится как текст в
    профиле и не влияет на статистику. Дата — диапазон (date/date_to): большинство
    внешних мероприятий однодневные, date_to можно оставить пустым."""
    class Meta:
        model = ExternalExperience
        fields = ['title', 'date', 'date_to', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Например: Городской субботник'}),
            # Красивый календарь проекта (data-datepicker) с листанием по годам
            # (data-dp-year-toggle в base.html), как в смене мероприятия — вместо
            # нативного type=date. Два независимых одиночных календаря (не
            # initDateRangePair — тот заточен под конкретную разметку строки охвата
            # отчётов), date_to может остаться пустым для однодневного мероприятия.
            'date': forms.DateInput(
                attrs={'type': 'text', 'data-datepicker': '', 'autocomplete': 'off'},
                format='%Y-%m-%d',
            ),
            'date_to': forms.DateInput(
                attrs={'type': 'text', 'data-datepicker': '', 'autocomplete': 'off'},
                format='%Y-%m-%d',
            ),
            'description': forms.TextInput(attrs={'placeholder': 'Например: Помощь на регистрации'}),
        }
        labels = {'title': 'Название', 'date': 'Дата начала', 'date_to': 'Дата окончания (если несколько дней)', 'description': 'Что делал'}

    def clean(self):
        cleaned = super().clean()
        date, date_to = cleaned.get('date'), cleaned.get('date_to')
        if date and date_to and date_to < date:
            self.add_error('date_to', 'Дата окончания не может быть раньше даты начала.')
        return cleaned


class ExcelImportForm(forms.Form):
    excel_file = forms.FileField(label='Excel файл', help_text='Загрузите файл .xlsx')


class UserCommentForm(forms.ModelForm):
    class Meta:
        model = UserComment
        fields = ['text', 'event']
        labels = {
            'text': 'Комментарий',
            'event': 'Мероприятие (необязательно)',
        }
        widgets = {
            'text': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, event_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['event'].required = False
        if event_queryset is not None:
            self.fields['event'].queryset = event_queryset


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


class CaptchaForm(forms.Form):
    """Простая капча-подтверждение для изменения констант (x + y, x,y in [-10, 10])."""
    answer = forms.IntegerField(label='Ответ')

    def __init__(self, *args, question=None, **kwargs):
        super().__init__(*args, **kwargs)
        if question:
            self.fields['answer'].label = f'Решите пример: {question} = ?'


class MultipleHiddenIntegerField(forms.Field):
    """Список id, приходящий из JS-пикера волонтёров как несколько скрытых
    input[name=...] с одинаковым именем (аналог ModelMultipleChoiceField, но БЕЗ
    рендера queryset'а в <option> — при тысячах пользователей это и было главной
    причиной медленной загрузки страниц настроек/требований, см. RequirementExceptionForm).

    Виджет — SelectMultiple без options: он не рендерится (поле выводится JS-пикером
    отдельно), но его value_from_datadict корректно делает QueryDict.getlist, забирая
    ВСЕ значения одноимённого поля, а не только последнее (как было бы у HiddenInput)."""
    widget = forms.SelectMultiple

    def to_python(self, value):
        if not value:
            return []
        try:
            return [int(v) for v in value]
        except (TypeError, ValueError):
            raise forms.ValidationError('Некорректный список пользователей.')

    def validate(self, value):
        if self.required and not value:
            raise forms.ValidationError('Выберите хотя бы одного пользователя.')


class RoleUsersForm(forms.Form):
    """Выбор пользователей для назначения/снятия роли (настройки) — id приходят от
    единого JS-виджета выбора в remote-режиме (data-chip-select data-select-remote)
    скрытыми полями `<prefix->users`, без серверного рендера queryset'а в <select>
    (тысячи пользователей иначе грузятся на каждую из нескольких секций страницы)."""
    users = MultipleHiddenIntegerField(required=True, label='Волонтёры')

    def __init__(self, *args, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_queryset = queryset if queryset is not None else User.objects.none()

    def clean_users(self):
        ids = self.cleaned_data['users']
        users = list(self.allowed_queryset.filter(id__in=ids))
        if not users:
            raise forms.ValidationError('Выберите хотя бы одного пользователя из допустимого списка.')
        return users


class ConstForm(forms.ModelForm):
    class Meta:
        model = Const
        fields = ['value']
        labels = {'value': 'Значение'}


class SeasonForm(forms.ModelForm):
    class Meta:
        model = Season
        fields = ['start_season', 'end_season']
        labels = {
            'start_season': 'Начало сезона',
            'end_season': 'Конец сезона (необязательно)',
        }
        widgets = {
            'start_season': forms.DateInput(attrs={'type': 'text', 'data-datepicker': '', 'autocomplete': 'off'}, format='%Y-%m-%d'),
            'end_season': forms.DateInput(attrs={'type': 'text', 'data-datepicker': '', 'autocomplete': 'off'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['end_season'].required = False


class OrganizationForm(forms.ModelForm):
    organizers = forms.ModelMultipleChoiceField(
        queryset=Organizer.objects.order_by('last_name', 'first_name'),
        required=False,
        label='Организаторы',
        widget=forms.SelectMultiple,
    )

    class Meta:
        model = Organization
        fields = ['name', 'description', 'internal_rating', 'comment']
        labels = {
            'name': 'Название',
            'description': 'Описание деятельности',
            'internal_rating': 'Внутренняя оценка',
            'comment': 'Комментарий',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'comment': forms.Textarea(attrs={'rows': 3}),
            'internal_rating': forms.NumberInput(attrs={'min': 0, 'max': 10}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['organizers'].initial = Organizer.objects.filter(
                organization_links__organization=self.instance
            )

    def save(self, commit=True):
        organization = super().save(commit=commit)
        if commit:
            self._save_organizers(organization)
        return organization

    def save_organizers(self, organization):
        self._save_organizers(organization)

    def _save_organizers(self, organization):
        from blog.models import OrganizerOrganizationLink
        selected = self.cleaned_data.get('organizers', Organizer.objects.none())
        OrganizerOrganizationLink.objects.filter(organization=organization).exclude(
            organizer__in=selected
        ).delete()
        for organizer in selected:
            OrganizerOrganizationLink.objects.get_or_create(organization=organization, organizer=organizer)


class OrganizerForm(forms.ModelForm):
    organizations = forms.ModelMultipleChoiceField(
        queryset=Organization.objects.order_by('name'),
        required=False,
        label='Организации',
        widget=forms.SelectMultiple,
    )

    class Meta:
        model = Organizer
        fields = [
            'first_name', 'last_name', 'phone', 'email',
            'telegram_username', 'VK_username', 'whatsapp', 'comments',
        ]
        labels = {
            'first_name': 'Имя',
            'last_name': 'Фамилия',
            'phone': 'Телефон',
            'email': 'Email',
            'telegram_username': 'Telegram',
            'VK_username': 'VK',
            'whatsapp': 'WhatsApp',
            'comments': 'Комментарии',
        }
        widgets = {
            'comments': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['organizations'].initial = Organization.objects.filter(
                organizer_links__organizer=self.instance
            )

    def save(self, commit=True):
        organizer = super().save(commit=commit)
        if commit:
            self._save_organizations(organizer)
        return organizer

    def save_organizations(self, organizer):
        self._save_organizations(organizer)

    def _save_organizations(self, organizer):
        from blog.models import OrganizerOrganizationLink
        selected = self.cleaned_data.get('organizations', Organization.objects.none())
        OrganizerOrganizationLink.objects.filter(organizer=organizer).exclude(
            organization__in=selected
        ).delete()
        for organization in selected:
            OrganizerOrganizationLink.objects.get_or_create(organizer=organizer, organization=organization)
