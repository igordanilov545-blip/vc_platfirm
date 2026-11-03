"""Загрузка FaP и ключа Google через интерфейс, без редактирования кода/.env."""
from django import forms
from data_base import data_controller as dc


def prepare_form_sheet(form, *, required=False):
    upload, url = form.cleaned_data.get('workbook'), form.cleaned_data.get('google_url', '')
    if upload and url:
        raise forms.ValidationError('Выберите один источник: XLSX или Google Таблицу.')
    if not upload and not url:
        if required:
            raise forms.ValidationError('Загрузите XLSX или вставьте ссылку Google Таблицы.')
        return None
    from blog.services.event_sheets import prepare_sheet_input
    if upload:
        if not upload.name.lower().endswith('.xlsx') or upload.size > 10 * 1024 * 1024:
            raise forms.ValidationError('Нужен файл .xlsx размером до 10 МБ.')
        content = upload.read()
        return prepare_sheet_input(form.assigned_by, content=content, name=upload.name)
    return prepare_sheet_input(form.assigned_by, google_url=url)


class EventSheetImportForm(forms.Form):
    workbook = forms.FileField(required=False, label='Загрузить таблицу (.xlsx)', widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))
    google_url = forms.URLField(required=False, label='Ссылка на Google Таблицу', widget=forms.URLInput(attrs={'placeholder': 'https://docs.google.com/spreadsheets/d/…/edit'}))

    def __init__(self, *args, assigned_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assigned_by = assigned_by
        self.prepared_sheet = None

    def clean(self):
        values = super().clean()
        if not self.errors:
            self.prepared_sheet = prepare_form_sheet(self, required=True)
        return values


class GoogleSheetsConnectionForm(forms.Form):
    credentials = forms.FileField(label='JSON-ключ сервисного аккаунта', widget=forms.ClearableFileInput(attrs={'accept': '.json'}))

    def clean_credentials(self):
        upload = self.cleaned_data['credentials']
        if upload.size > 65536:
            raise forms.ValidationError('JSON-ключ слишком большой.')
        return upload


class SheetTeamLeaderBindingForm(forms.Form):
    user = forms.ModelChoiceField(queryset=dc.active_team_leader_users_qs(), label='Тим-лидер платформы', empty_label='Выберите пользователя')
