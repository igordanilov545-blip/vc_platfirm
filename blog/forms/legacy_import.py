"""Миграция старых баз: загрузка файла базы (с годом) и версии ФиП."""
from django import forms
from django.utils import timezone

from data_base import data_controller as dc


def _xlsx(upload, limit_const, default_mb):
    maximum = dc.get_const(limit_const, default=default_mb)
    if not upload.name.casefold().endswith('.xlsx') or upload.size > maximum * 1024 * 1024:
        raise forms.ValidationError(f'Нужен файл .xlsx размером до {maximum:g} МБ.')
    return upload


class LegacyBaseUploadForm(forms.Form):
    action = forms.CharField(widget=forms.HiddenInput, initial='upload_base')
    workbook = forms.FileField(label='Таблица базы (.xlsx)', widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))
    year = forms.IntegerField(label='Год базы', min_value=2000, max_value=2100,
                              help_text='Одна база — один год. Год подставляется в даты колонок без года.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['year'].initial = timezone.localdate().year

    def clean_workbook(self):
        return _xlsx(self.cleaned_data['workbook'], 'legacy_import_max_mb', 10)


class FapUploadForm(forms.Form):
    action = forms.CharField(widget=forms.HiddenInput, initial='attach_fap')
    workbook = forms.FileField(label='Файл ФиП (.xlsx)', widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))

    def clean_workbook(self):
        return _xlsx(self.cleaned_data['workbook'], 'legacy_import_max_mb', 10)
