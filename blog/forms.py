from django import forms
from .models import User, Event, EventDay, Participation


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = '__all__'


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = '__all__'


class EventDayForm(forms.ModelForm):
    class Meta:
        model = EventDay
        fields = '__all__'


class ParticipationForm(forms.ModelForm):
    class Meta:
        model = Participation
        fields = '__all__'



class ExcelImportForm(forms.Form):
    excel_file = forms.FileField(label='Excel файл', help_text='Загрузите файл .xlsx')