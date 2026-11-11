"""Формы «таблички желающих» (documentation/volunteer-wishes.md)."""
from ._common import *  # noqa: F401,F403


class VolunteerWishAddForm(forms.Form):
    """Вставить сообщение о желающих как есть — разбор в services/volunteer_wishes."""
    text = forms.CharField(
        label='Сообщение о желающих',
        max_length=4000,
        widget=forms.Textarea(attrs={
            'rows': 6,
            'placeholder': '@username Фамилия Имя хочет на Скорость 21 и 22\n@username хочет на справки',
        }),
        help_text='Можно сразу несколько человек: @юзернеймы, телефоны, ФИО, название забега, '
                  'даты («14 и 15-го», «21 ноября», «21-22») и позицию («на справки»).',
    )


class VolunteerWishEditForm(forms.Form):
    """Ручная правка строки: привязать реальный аккаунт и мероприятие, один день.

    `user` приходит из общего выбора людей (data-select-remote="users", скрытый input
    перед сабмитом), поэтому в шаблоне поле рисуется пикером, а не стандартным виджетом."""
    user = forms.ModelChoiceField(label='Аккаунт на платформе', queryset=dc.users_qs(), required=False)
    telegram_username = forms.CharField(label='Telegram', max_length=100, required=False)
    phone = forms.CharField(label='Телефон', max_length=20, required=False)
    full_name = forms.CharField(label='ФИО', max_length=255, required=False)
    event_group = forms.ModelChoiceField(
        label='Мероприятие в базе', queryset=dc.event_groups_qs().none(), required=False,
        empty_label='— нет в базе (указать названием ниже) —',
    )
    event_hint = forms.CharField(label='Название, как написали', max_length=255, required=False,
                                 help_text='Если мероприятия ещё нет в базе: «Скорость», «СКБС».')
    wish_date = forms.DateField(
        label='День', required=False, input_formats=['%Y-%m-%d', '%d.%m.%Y'],
        widget=forms.DateInput(attrs={'type': 'text', 'data-datepicker': '', 'data-dp-keep-empty': '',
                                      'autocomplete': 'off'}, format='%Y-%m-%d'),
        help_text='Один день. Хочет на несколько — отдельная строка на каждый.',
    )
    position_hint = forms.CharField(label='Позиция', max_length=255, required=False)

    def __init__(self, *args, current_group=None, **kwargs):
        super().__init__(*args, **kwargs)
        from blog.services.volunteer_wishes import upcoming_event_groups
        ids = [group.pk for group in upcoming_event_groups()] + ([current_group.pk] if current_group else [])
        self.fields['event_group'].queryset = dc.event_groups_qs().filter(pk__in=ids).order_by('title')

    def clean(self):
        data = super().clean()
        if not any(data.get(name) for name in ('user', 'telegram_username', 'phone', 'full_name')):
            raise forms.ValidationError('Нужен аккаунт или хотя бы один контакт: Telegram, телефон или ФИО.')
        return data


class VolunteerWishTakeShiftForm(forms.Form):
    """«Забрать в смену»: смена (только доступные пользователю) и необязательная роль
    из плана смен. Выбор делает services/volunteer_wishes.shift_choices."""
    shift = forms.TypedChoiceField(label='Смена', coerce=int)
    role = forms.ChoiceField(label='Роль в смене', required=False,
                             help_text='Можно не выбирать — роль назначают и потом, в таблице смены.')

    def __init__(self, *args, shifts=(), **kwargs):
        super().__init__(*args, **kwargs)
        from django.utils import timezone as tz
        from blog.services import shift_roles

        # Название мероприятия в подписи — только если смены из разных мероприятий.
        several_groups = len({shift.event.event_group_id for shift in shifts}) > 1

        def label(shift):
            group = shift.event.event_group.title + ' · ' if several_groups and shift.event.event_group_id else ''
            start, end = tz.localtime(shift.start_time), tz.localtime(shift.end_time)
            return f'{group}{shift.event.title} · {shift.day:%d.%m} {start:%H:%M}–{end:%H:%M}'

        self.fields['shift'].choices = [(shift.pk, label(shift)) for shift in shifts]
        roles = []
        for shift in shifts:
            for name, _ in shift_roles.shift_plan(shift):
                if name not in roles:
                    roles.append(name)
        self.fields['role'].choices = [('', '— без роли —')] + [(name, name) for name in roles]
