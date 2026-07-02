from django import forms
from .models import (
    Event, EventDay, Participation, Application, UserComment, EventFeedback,
    Const, Season, Organization, Organizer, User, EventStaff,
)


class LoginForm(forms.Form):
    login = forms.CharField(label='Логин', max_length=50)
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput)


class UserModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        suffix = f' (@{obj.telegram_username})' if obj.telegram_username else ''
        return f'{obj.full_name}{suffix}'


class EventStaffAssignForm(forms.Form):
    user = UserModelChoiceField(
        queryset=User.objects.order_by('first_name', 'last_name'),
        label='Пользователь',
    )
    staff_role = forms.ChoiceField(choices=EventStaff.ROLE_CHOICES, label='Роль')


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            'title', 'description', 'location', 'chat_link', 'post_in_chanel_link',
            'dobro_ru_link', 'dobro_ru_link_type', 'organization', 'organizer',
            'people_helped', 'internal_comment', 'letter',
        ]
        labels = {
            'title': 'Название',
            'description': 'Описание',
            'location': 'Локация',
            'chat_link': 'Ссылка на чат',
            'post_in_chanel_link': 'Ссылка на пост в канале',
            'dobro_ru_link': 'Ссылка на Добро.ру',
            'dobro_ru_link_type': 'Тип ссылки на Добро.ру',
            'organization': 'Организация',
            'organizer': 'Контактное лицо',
            'people_helped': 'Людей получили помощь',
            'internal_comment': 'Внутренний комментарий',
            'letter': 'Шаблон благодарственного письма',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'internal_comment': forms.Textarea(attrs={'rows': 3}),
        }


class EventDayForm(forms.ModelForm):
    class Meta:
        model = EventDay
        fields = ['day', 'start_time', 'end_time', 'volunteer_needed', 'location']
        labels = {
            'day': 'Дата',
            'start_time': 'Время начала',
            'end_time': 'Время окончания',
            'volunteer_needed': 'Нужно волонтёров',
            'location': 'Локация',
        }
        widgets = {
            'day': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'end_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class ParticipationForm(forms.ModelForm):
    class Meta:
        model = Participation
        fields = ['status', 'hours']
        labels = {
            'status': 'Статус явки',
            'hours': 'Часы',
        }


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = [
            'event', 'first_name', 'last_name', 'telegram_username', 'phone',
            'functions', 'shifts', 'role_in_event', 'user_status',
        ]
        labels = {
            'event': 'Мероприятие',
            'first_name': 'Имя',
            'last_name': 'Фамилия',
            'telegram_username': 'Telegram',
            'phone': 'Телефон',
            'functions': 'Функция',
            'shifts': 'Смена',
            'role_in_event': 'Роль',
            'user_status': 'Статус обращающегося',
        }


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
            'start_season': forms.DateInput(attrs={'type': 'date'}),
            'end_season': forms.DateInput(attrs={'type': 'date'}),
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
