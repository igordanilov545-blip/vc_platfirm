"""Блок «Мой опыт» (раздел 3): объединяет системный волонтёрский опыт (участия в
мероприятиях центра) и самозаявленный внешний опыт (ExternalExperience) в единый
хронологический список. Внешний опыт в статистику НЕ входит.
"""
from blog.models import User


def build_experience(user: User) -> dict:
    """Возвращает {'items': [...], 'system_event_count': int, 'total_count': int}.

    items — список записей вида:
      {'kind': 'system'|'external', 'title': str, 'date': date|None,
       'event_id': int|None, 'exp_id': int|None}
    отсортированный по дате (свежие сверху; записи без даты — в конец).

    system_event_count — число РАЗНЫХ мероприятий центра с явкой (для статистики/текста
    экспорта учитываем именно системные, но общий счётчик total_count включает и внешние).
    """
    # Системный опыт: посещённые смены, сгруппированные по мероприятию (одно меро —
    # одна строка, дата = последний посещённый день этого меро).
    participations = (
        user.participations.filter(status='attended')
        .select_related('event_day__event')
    )
    by_event = {}
    for p in participations:
        event = p.event_day.event
        day = p.event_day.day
        cur = by_event.get(event.id)
        if cur is None or day > cur['date']:
            by_event[event.id] = {
                'kind': 'system',
                'title': event.title,
                'date': day,
                'event_id': event.id,
                'exp_id': None,
            }

    items = list(by_event.values())
    system_event_count = len(items)

    for exp in user.external_experiences.all():
        if exp.date and exp.date_to and exp.date_to != exp.date:
            date_display = f'{exp.date.strftime("%d.%m.%y")} — {exp.date_to.strftime("%d.%m.%y")}'
        elif exp.date:
            date_display = exp.date.strftime('%d.%m.%y')
        else:
            date_display = None
        items.append({
            'kind': 'external',
            'title': exp.title,
            'date': exp.date,
            'date_display': date_display,
            'description': exp.description,
            'event_id': None,
            'exp_id': exp.id,
        })

    # Ранжирование: сначала мероприятия ВЦ (kind='system'), внутри — по времени
    # (свежие сверху); затем внешний опыт (kind='external'), тоже по времени.
    # Записи без даты — в конце своей группы.
    items.sort(key=lambda i: (
        0 if i['kind'] == 'system' else 1,
        i['date'] is None,
        -i['date'].toordinal() if i['date'] else 0,
    ))

    return {
        'items': items,
        'system_event_count': system_event_count,
        'total_count': len(items),
    }
