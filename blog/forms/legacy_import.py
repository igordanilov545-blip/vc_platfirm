"""Загрузка старой базы и уточнение дат колонок в существующих виджетах."""
from django import forms
from data_base import data_controller as dc


class LegacyBaseUploadForm(forms.Form):
    workbook = forms.FileField(label='Таблица базы (.xlsx)', widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))

    def clean_workbook(self):
        upload = self.cleaned_data['workbook']
        maximum = dc.get_const('legacy_import_max_mb', default=10)
        if not upload.name.casefold().endswith('.xlsx') or upload.size > maximum * 1024 * 1024:
            raise forms.ValidationError(f'Нужен файл .xlsx размером до {maximum:g} МБ.')
        return upload


class LegacyDatesForm(forms.Form):
    def __init__(self, plan, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for column in plan['columns']:
            self.fields[f'date_{column["index"]}'] = forms.DateField(
                label=column['header'], required=bool(column['used']), initial=column['day'],
                input_formats=['%Y-%m-%d', '%d.%m.%Y'],
                widget=forms.DateInput(format='%Y-%m-%d', attrs={'data-datepicker': '', 'data-dp-keep-empty': '', 'autocomplete': 'off'}),
            )

    def date_overrides(self):
        return {name.removeprefix('date_'): value.isoformat() for name, value in self.cleaned_data.items() if value}
