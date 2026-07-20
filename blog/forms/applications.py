"""Формы домена «applications». Часть пакета blog.forms (см. README.md).

Формы заявок и явки: подача/отмена заявки, участие (часы), импорт Excel.

Общие импорты (django.forms, модели) — из ._common.
"""
from ._common import *  # noqa: F401,F403


class ParticipationForm(forms.ModelForm):
    class Meta:
        model = Participation
        fields = ['status', 'hours', 'full_shift']
        labels = {
            'status': 'Статус явки',
            'hours': 'Часы',
            'full_shift': 'Полная смена',
        }
        widgets = {
            'hours': forms.NumberInput(attrs={'min': 0}),
        }

class ShiftMultipleSelect(forms.SelectMultiple):
    """Select для выбора смен, где у каждого <option> проставлен `data-closed="1"`,
    если набор на эту смену закрыт — JS (initCategoryChips) красит такой chip серым,
    но смена остаётся кликабельной (заявка на неё просто сразу уйдёт в резерв)."""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        # value приходит как ModelChoiceIteratorValue (Django 4+), не голым pk — берём
        # обёрнутое значение через .value перед использованием в фильтре.
        raw_value = value.value if hasattr(value, 'value') else value
        shift = self.choices.queryset.filter(pk=raw_value).first() if raw_value else None
        if shift and shift.recruit_status != 'open':
            option['attrs']['data-closed'] = '1'
        return option

class ApplicationForm(forms.ModelForm):
    """Заявка на участие через веб (в отличие от Excel-импорта): ФИО/Telegram/телефон
    система уже знает из профиля авторизованного пользователя, поэтому их не спрашивает —
    остаётся выбрать мероприятие и смены.

    Выбор смен — множественный (чипы, как категории у мероприятия): пул вариантов —
    смены, привязанные к выбранному мероприятию с открытым набором. Если у меро всего
    одна смена — выбирать нечего, подаём сразу на неё.
    """
    selected_shifts = forms.ModelMultipleChoiceField(
        queryset=EventShift.objects.none(),
        required=False,
        label='Смены',
        widget=ShiftMultipleSelect,
    )

    class Meta:
        model = Application
        fields = ['event', 'functions', 'role_in_event']
        labels = {
            'event': 'Мероприятие',
            'functions': 'Функция',
            'role_in_event': 'Роль',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.applicant = user
        # Прошедшие мероприятия с ещё открытыми сменами закрываем лениво прямо тут —
        # это самое надёжное место: форма подачи заявки открывается чаще всего и должна
        # гарантированно не предлагать прошедшие меро (нет отдельного планировщика задач).
        for event in Event.objects.filter(shifts__recruit_status='open').distinct():
            event.close_recruit_if_passed()
        # Подать заявку можно на любое ОПУБЛИКОВАННОЕ меро (published_at задан), у
        # которого есть хотя бы одна смена, которая ещё не началась — даже если набор
        # на все смены уже закрыт (такая заявка просто сразу уходит в резерв, см.
        # application_create), но НЕ на меро, которое уже закончилось целиком или
        # ЯВНО ЗАВЕРШЕНО менеджером (event_status='finished'): такое меро больше не
        # принимает заявок, даже если у него формально остались будущие смены.
        now = timezone.now()
        self.fields['event'].queryset = (
            Event.objects.filter(published_at__isnull=False, shifts__start_time__gt=now)
            .exclude(event_status='finished')
            .distinct().order_by('-created_at')
        )

        # Пул смен для чипов — только смены выбранного меро, которые ещё не начались
        # (открытые и закрытые по набору — закрытая смена всё ещё выбираема, просто
        # заявка на неё сразу пойдёт в резерв; прошедшие/начавшиеся не предлагаются).
        event = self.instance.event if self.instance and self.instance.pk else None
        if 'event' in self.data:
            try:
                event = Event.objects.get(pk=self.data.get('event'))
            except (Event.DoesNotExist, ValueError, TypeError):
                event = None
        if event:
            self.fields['selected_shifts'].queryset = event.shifts.filter(
                start_time__gt=now
            ).order_by('day')
        if self.instance and self.instance.pk:
            self.initial.setdefault('selected_shifts', self.instance.selected_shifts.all())
            # При редактировании существующей заявки мероприятие не меняем — только
            # смены/функцию/роль (иначе теряется смысл "отредактировать свою заявку").
            self.fields['event'].disabled = True

class ApplicationCancelForm(forms.Form):
    """Отмена заявки волонтёром — причина обязательна (доступно только пока до
    мероприятия осталось больше const.late_cancel_hours, проверяется во view)."""
    reason = forms.CharField(
        label='Подскажите, пожалуйста, почему вы отказываетесь от участия — нам это поможет',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Например: изменились планы, не подхожу по времени и т.п.'}),
    )

class ExcelImportForm(forms.Form):
    excel_file = forms.FileField(label='Excel файл', help_text='Загрузите файл .xlsx')
