"""Формы домена «roles». Часть пакета blog.forms (см. README.md).

Формы ролей и капча: назначение/снятие ролей (пикер пользователей),
капча-2FA, поле множественного скрытого выбора.

Общие импорты (django.forms, модели) — из ._common.
"""
from ._common import *  # noqa: F401,F403


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
