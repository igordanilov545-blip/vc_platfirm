"""Формы домена «references». Часть пакета blog.forms (см. README.md).

Формы справочников: локации, организации, организаторы, категории,
требования (+ исключения), константы, сезоны, их Quick-версии.

Общие импорты (django.forms, модели) — из ._common.
"""
from ._common import *  # noqa: F401,F403


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

class QuickCategoryForm(forms.ModelForm):
    """Мини-форма быстрого создания категории мероприятия прямо из формы мероприятия."""
    class Meta:
        model = EventCategory
        fields = ['name']
        labels = {'name': 'Название категории'}

class CategoryForm(forms.ModelForm):
    """Создание/редактирование категории мероприятия на странице настроек."""
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
        user = dc.get_user_by_id(user_id)
        if not user:
            raise forms.ValidationError('Выберите волонтёра из списка.')
        if self.requirement is not None and dc.user_has_requirement_exception(user, self.requirement):
            raise forms.ValidationError('Этот волонтёр уже отмечен как несоответствующий требованию.')
        return user

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.user = self.cleaned_data['user']
        instance.requirement = self.requirement
        if commit:
            instance.save()
        return instance

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
        queryset=dc.organizers_qs().order_by('last_name', 'first_name'),
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
            self.fields['organizers'].initial = dc.organizers_for_organization(self.instance)

    def save(self, commit=True):
        organization = super().save(commit=commit)
        if commit:
            self._save_organizers(organization)
        return organization

    def save_organizers(self, organization):
        self._save_organizers(organization)

    def _save_organizers(self, organization):
        selected = list(self.cleaned_data.get('organizers') or [])
        dc.sync_organization_organizers(organization, selected)

class OrganizerForm(forms.ModelForm):
    organizations = forms.ModelMultipleChoiceField(
        queryset=dc.organizations_qs().order_by('name'),
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
            self.fields['organizations'].initial = dc.organizations_for_organizer(self.instance)

    def save(self, commit=True):
        organizer = super().save(commit=commit)
        if commit:
            self._save_organizations(organizer)
        return organizer

    def save_organizations(self, organizer):
        self._save_organizations(organizer)

    def _save_organizations(self, organizer):
        selected = list(self.cleaned_data.get('organizations') or [])
        dc.sync_organizer_organizations(organizer, selected)
