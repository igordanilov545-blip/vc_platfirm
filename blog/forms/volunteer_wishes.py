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
    """Ручная правка разобранной строки, если эвристика ошиблась."""
    telegram_username = forms.CharField(label='Telegram', max_length=100, required=False)
    phone = forms.CharField(label='Телефон', max_length=20, required=False)
    full_name = forms.CharField(label='ФИО', max_length=255, required=False)
    event_hint = forms.CharField(label='Мероприятие', max_length=255, required=False,
                                 help_text='Как называют забег в сообществе: «Скорость», «СКБС».')
    dates_text = forms.CharField(label='Даты', max_length=255, required=False,
                                 help_text='Например: 21.11.2026, 22.11.2026 или «21-22 ноября».')
    position_hint = forms.CharField(label='Позиция', max_length=255, required=False)

    def clean(self):
        from blog.services.volunteer_wishes import parse_dates_text
        data = super().clean()
        if not any(data.get(name) for name in ('telegram_username', 'phone', 'full_name')):
            raise forms.ValidationError('Нужен хотя бы один контакт: Telegram, телефон или ФИО.')
        data['dates'] = parse_dates_text(data.get('dates_text'))
        if data.get('dates_text') and not data['dates']:
            self.add_error('dates_text', 'Не удалось разобрать даты.')
        return data
