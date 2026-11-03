"""Формы домена «profiles». Часть пакета blog.forms (см. README.md).

Формы профиля: редактирование профиля, внешний опыт, комментарии
о пользователе, быстрое создание волонтёра.

Общие импорты (django.forms, модели) — из ._common.
"""
from ._common import *  # noqa: F401,F403
from blog.services.profile_completion import PROFILE_SECTIONS, profile_completion


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
    preferred_contact_methods = forms.MultipleChoiceField(
        label='Наиболее удобный способ связи', choices=User.CONTACT_METHOD_CHOICES,
        widget=forms.CheckboxSelectMultiple, required=True,
        error_messages={'required': 'Выберите хотя бы один способ связи.'},
    )
    weekday_daytime_available = forms.TypedChoiceField(
        label='Вы могли бы помогать нам в дневное время в будни?',
        choices=[('', '—'), ('True', 'Да'), ('False', 'Нет')],
        coerce=lambda value: value == 'True', empty_value=None, required=False,
    )
    wants_team_lead = forms.TypedChoiceField(
        label='Желание стать тим-лидером', choices=[('', '—'), ('True', 'Да'), ('False', 'Нет')],
        coerce=lambda value: value == 'True', empty_value=None, required=False,
    )

    class Meta:
        model = User
        fields = [name for _, _, names in PROFILE_SECTIONS for name in names]
        widgets = {
            'birthday': forms.DateInput(
                attrs={'type': 'text', 'data-datepicker': '', 'data-dp-keep-empty': '', 'autocomplete': 'off'},
                format='%Y-%m-%d',
            ),
            'about': forms.Textarea(attrs={'rows': 3}),
            'volunteer_experience': forms.Textarea(attrs={'rows': 3}),
            'motivation': forms.Textarea(attrs={'rows': 3}),
            'familiar_positions': forms.Textarea(attrs={'rows': 3}),
            'performed_tasks': forms.Textarea(attrs={'rows': 3}),
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
        for field in self.fields.values():
            field.widget.attrs['data-counter-mode'] = 'limit'

    @property
    def sections(self):
        return [{'key': key, 'title': title, 'fields': [self[name] for name in names]}
                for key, title, names in PROFILE_SECTIONS]

    @property
    def completion(self):
        if self.is_bound:
            self.errors  # Вычисляем cleaned_data: ошибочные ответы не считаются заполненными.
            return profile_completion(self.cleaned_data)
        return profile_completion(self.instance)

    def clean_preferred_contact_methods(self):
        return list(dict.fromkeys(self.cleaned_data['preferred_contact_methods']))

    def clean_telegram_username(self):
        # Нормализуем: убираем ведущий @ и пробелы, чтобы в БД лежал чистый username.
        value = (self.cleaned_data.get('telegram_username') or '').strip()
        return value.lstrip('@').strip()

    def clean_VK_username(self):
        from blog.services.social_profiles import social_username
        value = self.cleaned_data.get('VK_username')
        handle = social_username(value, 'vk')
        if value and not handle:
            raise forms.ValidationError('Укажите имя пользователя ВК или ссылку на vk.com.')
        return handle

    def clean_instagram_url(self):
        from blog.services.social_profiles import social_username
        value = self.cleaned_data.get('instagram_url')
        handle = social_username(value, 'instagram')
        if value and not handle:
            raise forms.ValidationError('Укажите имя пользователя Instagram или ссылку на instagram.com.')
        return handle

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


# Обратная совместимость: часть кода/шаблонов ещё ссылается на старое имя.
ProfileCompletionForm = ProfileForm
