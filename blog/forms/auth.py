"""Формы домена «auth». Часть пакета blog.forms (см. README.md).

Формы входа и веб-регистрации.

Общие импорты (django.forms, модели) — из ._common.
"""
from ._common import *  # noqa: F401,F403


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
