"""Сводки мероприятий: независимые агрегаты не перемножают смены, заявки и менеджеров."""
from django.db.models import Count, Q, Sum

from data_base import data_controller as dc


def event_group_rows():
    """Список мероприятий с суммами по позициям; Добро.ру всегда читается из позиций.

    Набор измеряется местами на сменах. Заявка на несколько смен считается одной
    заявкой. Отменённые заявки исключаются. Позиции без учёта Добро.ру не требуют
    простановки; отсутствие учитываемых позиций означает «не требуется».
    Производный статус не хранится вторым флагом и потому обновляется в обе стороны,
    включая перенос/удаление позиции и существующие массовые операции отчётов.
    """
    groups = list(dc.event_groups_qs().prefetch_related('managers').order_by('title', 'pk'))
    ids = [group.pk for group in groups]
    if not ids:
        return groups

    needed = dict(
        dc.event_shifts_qs().filter(event__event_group_id__in=ids)
        .values('event__event_group_id').annotate(n=Sum('volunteer_needed'))
        .values_list('event__event_group_id', 'n')
    )
    approved = dict(
        dc.application_shift_decisions_qs()
        .filter(application__event__event_group_id__in=ids, status='approved')
        .exclude(application__status='cancelled')
        .values('application__event__event_group_id').annotate(n=Count('pk'))
        .values_list('application__event__event_group_id', 'n')
    )
    applications = {
        row['event__event_group_id']: row
        for row in dc.applications_qs().filter(event__event_group_id__in=ids)
        .exclude(status='cancelled').values('event__event_group_id')
        .annotate(total=Count('pk'), processed=Count('pk', filter=~Q(status='new')))
    }
    dobro = {
        row['event_group_id']: row
        for row in dc.events_qs().filter(event_group_id__in=ids)
        .exclude(dobro_ru_link_kind='none').values('event_group_id')
        .annotate(tracked=Count('pk'), pending=Count('pk', filter=Q(dobro_ru_hours_logged=False)))
    }
    for group in groups:
        group.managers_label = ', '.join(user.full_name for user in group.managers.all()) or '—'
        group.needed = needed.get(group.pk, 0)
        group.approved = approved.get(group.pk, 0)
        group.recruit_percent = (
            round(group.approved * 100 / group.needed) if group.needed
            else (100 + group.approved * 100 if group.approved else 100)
        )
        counts = applications.get(group.pk, {})
        group.applications_total = counts.get('total', 0)
        group.applications_processed = counts.get('processed', 0)
        group.applications_percent = (
            round(group.applications_processed * 100 / group.applications_total)
            if group.applications_total else 100
        )
        tracking = dobro.get(group.pk)
        group.dobro_status = 'not_required' if not tracking else ('pending' if tracking['pending'] else 'logged')
        group.dobro_ru_hours_logged = group.dobro_status == 'logged'
    return groups
