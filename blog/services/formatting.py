"""Единые форматтеры даты/времени для отчётов, экспортов и справок.

Сводит воедино 4+ почти одинаковых локальных копии (`_fmt_dt`, `_fmt_date`,
`_fmt_dt_local`, `_fmt_day`), что расходились по краевым случаям (audit-reuse.md §2).
Здесь ОДНА реализация каждого формата.

Не дубли (свою логику НЕ переносим сюда): `_days_ago` (вычисление, а не формат) и
`_fmt_day` в `custom_tags.py` (особый формат `dd.mm.yy (день недели)`).
"""

DASH = '—'


def fmt_date(value) -> str:
    """Дата как `dd.mm.YYYY`. Пусто/None → «—». Не-дата → str(value).
    Заменяет `_fmt_date` (reports) и `_fmt_day` (pgas)."""
    if not value:
        return DASH
    try:
        return value.strftime('%d.%m.%Y')
    except AttributeError:
        return str(value)


def fmt_dt(value, with_time: bool = True) -> str:
    """Дата-время как `dd.mm.YYYY HH:MM` (или только дата при `with_time=False`).
    Пусто/None → «—». Не-дата → str(value). Заменяет `_fmt_dt` (report_builders,
    report_exports) и `_fmt_dt_local` (reports).

    Если у значения нет времени (date без hour), время не дописываем даже при
    `with_time=True` — как делал авто-режим `report_exports._fmt_dt`."""
    if not value:
        return DASH
    if not hasattr(value, 'strftime'):
        return str(value)
    has_time = hasattr(value, 'hour')
    fmt = '%d.%m.%Y %H:%M' if (with_time and has_time) else '%d.%m.%Y'
    return value.strftime(fmt)
