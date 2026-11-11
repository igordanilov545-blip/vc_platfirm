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


def _clean(name):
    return ' '.join(str(name or '').split())[:255]


def normalize_role_plan(raw, needed):
    """План ролей смены: [[роль, n], …]. Пусто — 1 тим-лидер и остальные волонтёры;
    нерасписанный остаток — волонтёрам. Больше, чем нужно, — оставляем (подсказка)."""
    plan, index = [], {}
    for item in raw or []:
        role, count = (item.get('role'), item.get('count')) if isinstance(item, dict) else (list(item) + [None, None])[:2]
        role = _clean(role)
        try:
            count = int(count or 0)
        except (TypeError, ValueError):
            count = 0
        if not role or count <= 0:
            continue
        if _key(role) in index:
            plan[index[_key(role)]][1] += count
        else:
            index[_key(role)] = len(plan)
            plan.append([role, count])
    needed = max(int(needed or 0), 0)
    if not plan:
        plan = [[TEAM_LEAD_ROLE, 1]] if needed else []
    rest = needed - sum(n for _, n in plan)
    if rest > 0:
        if _key(VOLUNTEER_ROLE) in {_key(r) for r, _ in plan}:
            plan = [[r, n + rest] if _key(r) == _key(VOLUNTEER_ROLE) else [r, n] for r, n in plan]
        else:
            plan.append([VOLUNTEER_ROLE, rest])
    return plan


def shift_plan(shift):
    """План ролей смены; у старых смен без плана — по умолчанию."""
    return shift.role_plan or normalize_role_plan([], shift.volunteer_needed)


def plan_label(plan):
    return ', '.join(f'{role} {n}' for role, n in plan)


def role_pool(event=None, function=None):
    """Подсказки названий ролей при планировании смены: роли функции из пула."""
    function = function if function is not None else (position_function(event) if event is not None else None)
    names = [TEAM_LEAD_ROLE, VOLUNTEER_ROLE]
    if function is not None:
        names += [t.name for t in dc.position_templates_qs().filter(category=function).order_by('name')]
    return _unique(names)


def _unique(names):
    seen, result = set(), []
    for name in names:
        if name and _key(name) not in seen:
            seen.add(_key(name))
            result.append(name)
    return result


def role_options(event, shifts=None):
    """Выбор роли человека — только роли, запланированные в сменах этой функции."""
    shifts = list(shifts if shifts is not None else event.shifts.all())
    return _unique([role for shift in shifts for role, _ in shift_plan(shift)])


def role_stats(shift, decisions):
    """По каждой роли плана: сколько одобренных уже с ней / сколько планировалось."""
    counts = Counter(_key(d.role) for d in decisions if d.status == 'approved' and d.role)
    plan = shift_plan(shift)
    stats = [{'role': role, 'have': counts.pop(_key(role), 0), 'plan': n} for role, n in plan]
    names = {_key(d.role): d.role for d in decisions if d.role}
    stats += [{'role': names[key], 'have': n, 'plan': 0} for key, n in counts.items()]
    without = sum(1 for d in decisions if d.status == 'approved' and not d.role)
    return {'roles': stats, 'without': without}


def set_role(operator, decision, role):
    return dc.set_decision_role(decision, role, operator)


@transaction.atomic
def sync_team_leads(event, operator=None):
    """Тим-лидеры позиции — в таблицу набора каждой будущей смены, одобрены, роль «Тим-лидер».

    Только если у тим-лидера ещё нет решения по этой смене: убранного вручную в
    резерв обратно не возвращаем, роль, выбранную вручную, не перетираем."""
    leads = dc.event_staff_users(event, 'team_lead')
    # Только непрошедшие и не архивные смены: история (миграция базы, где тим-лидер
    # назначен на все позиции функции) не должна получать лишних участий и часов.
    shifts = list(event.shifts.filter(day__gte=timezone.localdate(), legacy_source__isnull=True))
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
