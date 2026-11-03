from django import forms
from blog.services.role_invitations import default_hours


class RoleInvitationForm(forms.Form):
    role = forms.ChoiceField(choices=[('team_lead', 'Тим-лидер'), ('manager', 'Менеджер')], label='Выдаваемая роль')
    hours = forms.DecimalField(min_value=.01, max_digits=8, decimal_places=2, label='Срок действия ссылки, часов')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hours'].initial = default_hours()
