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


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleXlsxField(forms.FileField):
    """Несколько .xlsx за один раз (каждый файл проверяется отдельно)."""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': '.xlsx', 'multiple': True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        files = data if isinstance(data, (list, tuple)) else [data]
        return [_xlsx(single(item, initial), 'legacy_import_max_mb', 10) for item in files if item] or [single(None, initial)]


class FapLibraryForm(forms.Form):
    action = forms.CharField(widget=forms.HiddenInput, initial='upload_fap')
    workbooks = MultipleXlsxField(label='Файлы ФиП (.xlsx, можно несколько)',
                                  help_text='Читается только лист «Смены». Файлы попадают в библиотеку; к мероприятиям их привязывает таблица колонок базы.')
