"""Форма отдельного доступа к регистрации участников; роли пользователя не меняет."""
from django import forms
from data_base import data_controller as dc


class ScannerGrantForm(forms.Form):
    user = forms.ModelChoiceField(queryset=dc.users_qs().filter(status='active').order_by('last_name', 'first_name'), label='Пользователь')
    event_group = forms.ModelChoiceField(queryset=dc.event_groups_qs().order_by('title'), label='Мероприятие')
