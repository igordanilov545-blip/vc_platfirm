"""Роли людей в смене (решение пользователя 2026-11-11).

Позиция (Event) — это смена/набор; внутри одной смены у людей разные роли
(«Тим-лидер», «Волонтёр», «Хостес старта»…). Роль — колонка в таблице набора
смены рядом со статусом: подсказка для планирования, без ограничений — ключевым
остаётся количество людей. Тим-лидеры позиции заносятся в таблицу каждой смены
сами (одобрены) и сразу получают роль «Тим-лидер».
"""
from collections import Counter

from django.db import transaction
from django.utils import timezone

from data_base import data_controller as dc
from blog.services.position_pool import _key, position_function

TEAM_LEAD_ROLE = 'Тим-лидер'
VOLUNTEER_ROLE = 'Волонтёр'
NO_ROLE = 'без роли'


def role_options(event):
    """Подсказки роли: тим-лидер, волонтёр, позиции функции из пула и уже выбранные."""
    names = [TEAM_LEAD_ROLE, VOLUNTEER_ROLE]
    function = position_function(event)
    if function is not None:
        names += [t.name for t in dc.position_templates_qs().filter(category=function).order_by('name')]
    names += list(dc.application_shift_decisions_qs().filter(shift__event=event).exclude(role='')
                  .values_list('role', flat=True).distinct())
    seen, result = set(), []
    for name in names:
        if _key(name) not in seen:
            seen.add(_key(name))
            result.append(name)
    return result


def role_stats(decisions):
    """Сколько каких ролей среди одобренных в смене: [(роль, n)], «без роли» — в конце."""
    counts = Counter((d.role or NO_ROLE) for d in decisions if d.status == 'approved')
    return sorted(counts.items(), key=lambda item: (item[0] == NO_ROLE, item[0] != TEAM_LEAD_ROLE, item[0].lower()))


def set_role(operator, decision, role):
    return dc.set_decision_role(decision, role, operator)


@transaction.atomic
def sync_team_leads(event, operator=None):
    """Тим-лидеры позиции — в таблицу набора каждой смены, одобрены, роль «Тим-лидер».

    Только если у тим-лидера ещё нет решения по этой смене: убранного вручную в
    резерв обратно не возвращаем, роль, выбранную вручную, не перетираем."""
    leads = dc.event_staff_users(event, 'team_lead')
    shifts = list(event.shifts.all())
    if not leads or not shifts:
        return 0
    added = 0
    for user in leads:
        application = (dc.applications_qs().filter(event=event, user=user)
                       .exclude(status='cancelled').order_by('pk').first())
        for shift in shifts:
            decision = (dc.application_shift_decisions_qs().filter(shift=shift, application__user=user)
                        .exclude(application__status='cancelled').first())
            if decision is not None:
                continue
            if application is None:
                application = dc.create_application(
                    event=event, user=user, first_name=user.first_name or '', last_name=user.last_name,
                    middle_name=user.middle_name, telegram_username=user.telegram_username, phone=user.phone,
                    submitted_at=timezone.now(), status='approved')
                application.shifts = 'Тим-лидер'
                application.save(update_fields=['shifts'])
            application.selected_shifts.add(shift)
            decision, _ = dc.set_shift_decision(application, shift, 'approved', assigned_by=operator)
            dc.set_decision_role(decision, TEAM_LEAD_ROLE, operator)
            dc.get_or_create_participation(user, shift, defaults={'status': 'pending', 'hours': 0, 'full_shift': False})
            added += 1
        if added:
            from blog.services.stats import recalc_user_aggregates
            recalc_user_aggregates(user)
    return added
