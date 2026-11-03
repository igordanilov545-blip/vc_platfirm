"""Загрузка старой базы и уточнение дат колонок в существующих виджетах."""
from django import forms
from data_base import data_controller as dc
from blog.services.legacy_workbook import DEFAULT_LEGACY_DAY


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
                label=column['header'], required=False, initial=column['day'] or DEFAULT_LEGACY_DAY,
                input_formats=['%Y-%m-%d', '%d.%m.%Y'],
                widget=forms.DateInput(format='%Y-%m-%d', attrs={'data-datepicker': '', 'data-dp-keep-empty': '', 'autocomplete': 'off'}),
            )

    def date_overrides(self):
        return {name.removeprefix('date_'): value.isoformat() for name, value in self.cleaned_data.items() if value}

    @property
    def error_summary(self):
        summary = [{'message': message, 'anchor': 'legacy-import-status'} for message in self.non_field_errors()]
        for name, messages in self.errors.items():
            if name in self.fields:
                summary.extend({'message': f'{self.fields[name].label}: {message}',
                                'anchor': 'legacy-date-' + name.removeprefix('date_')} for message in messages)
        return summary
