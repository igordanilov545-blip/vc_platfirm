"""Рендер благодарственных писем поверх PDF-фона (letter-templates.md).

Конструктор: менеджер загружает оформленный PDF (`ThankYouLetterTemplate.background_pdf`)
и расставляет поверх поля-заглушки (`fields_json`). Здесь — генерация итогового PDF
(штамповка реальных значений в координаты полей) и растр фона в PNG для редактора.

КРОСС-ПЛАТФОРМЕННОСТЬ (приоритет проекта): всё делает PyMuPDF (fitz) — самодостаточная
библиотека без системных бинарей и без обращения к шрифтам ОС. Текст штампуется файлом
шрифта из БД (`LetterFont.font_file`), поэтому вывод идентичен на Windows (локально) и
Linux (прод). Встроенные шрифты берём из matplotlib (DejaVu Sans/Serif/Mono — полная
кириллица, matplotlib и так в зависимостях) — не зависим от того, что установлено в ОС.
"""
import io
import os

import fitz  # PyMuPDF

from data_base import data_controller as dc


# --- Поля-заглушки, доступные в редакторе -----------------------------------

FIELD_KEYS = {
    'fio': 'ФИО волонтёра',
    'event': 'Мероприятие',
    'event_date': 'Дата мероприятия',
    'hours': 'Количество часов',
    'organizer': 'Организатор / подпись',
    'custom': 'Свободный текст',
}

# Выравнивание fitz по строковому ключу поля.
_ALIGN = {
    'left': fitz.TEXT_ALIGN_LEFT,
    'center': fitz.TEXT_ALIGN_CENTER,
    'right': fitz.TEXT_ALIGN_RIGHT,
}

_RU_MONTHS = [
    '', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]


# --- Встроенные шрифты (лениво досоздаются в БД) -----------------------------

def _matplotlib_font_dir():
    import matplotlib
    return os.path.join(os.path.dirname(matplotlib.__file__), 'mpl-data', 'fonts', 'ttf')


# name → имя файла в mpl-data. DejaVu покрывает кириллицу; matplotlib — обязательная
# зависимость, так что файлы гарантированно есть и на проде.
BUILTIN_FONTS = {
    'DejaVu Sans': 'DejaVuSans.ttf',
    'DejaVu Sans Bold': 'DejaVuSans-Bold.ttf',
    'DejaVu Serif': 'DejaVuSerif.ttf',
    'DejaVu Serif Bold': 'DejaVuSerif-Bold.ttf',
    'DejaVu Sans Mono': 'DejaVuSansMono.ttf',
}


def ensure_builtin_fonts():
    """Досоздаёт встроенные шрифты в таблице letter_fonts, если их ещё нет (ленивая
    инициализация вместо data-миграции, coding-principles §9). Идемпотентна."""
    font_dir = _matplotlib_font_dir()
    for name, filename in BUILTIN_FONTS.items():
        if dc.get_letter_font_by_name(name):
            continue
        path = os.path.join(font_dir, filename)
        if not os.path.exists(path):
            continue
        with open(path, 'rb') as f:
            data = f.read()
        dc.create_letter_font(name=name, data=data, filename=filename, is_builtin=True)


# --- Формат даты письма ------------------------------------------------------

def _ru_long_date(value) -> str:
    """Дата как «12 марта 2025» (русские месяцы, без нулей). PyMuPDF-текст, поэтому
    локаль ОС не задействуем — имена месяцев зашиты (кросс-платформенно)."""
    if not value:
        return ''
    return f'{value.day} {_RU_MONTHS[value.month]} {value.year}'


def event_date_label(first_day, last_day) -> str:
    """Подпись даты мероприятия. Одна дата — «12 марта 2025». Диапазон (многодневное
    меро) — «12 марта — 14 марта 2025» (по первой и последней смене, как просил
    заказчик). Год не дублируем, если он совпадает."""
    if not first_day:
        return ''
    if not last_day or first_day == last_day:
        return _ru_long_date(first_day)
    if first_day.year == last_day.year:
        left = f'{first_day.day} {_RU_MONTHS[first_day.month]}'
        return f'{left} — {_ru_long_date(last_day)}'
    return f'{_ru_long_date(first_day)} — {_ru_long_date(last_day)}'


# --- Контекст письма для конкретного волонтёра/меро --------------------------

def letter_context(user, event, hours=None, first_day=None, last_day=None) -> dict:
    """Значения полей-заглушек для реального письма. Если дни/часы не переданы —
    считаем по участиям волонтёра в меро (attended)."""
    if hours is None or first_day is None or last_day is None:
        parts = list(
            dc.participations_qs().filter(
                user=user, event_day__event=event, status='attended'
            ).select_related('event_day')
        )
        if hours is None:
            hours = sum(p.hours for p in parts)
        days = [p.event_day.day for p in parts]
        if first_day is None:
            first_day = min(days) if days else None
        if last_day is None:
            last_day = max(days) if days else None

    organizer = ''
    if event.organization_id:
        organizer = event.organization.name

    return {
        'fio': user.full_name,
        'event': event.title,
        'event_date': event_date_label(first_day, last_day),
        'hours': _fmt_hours(hours),
        'organizer': organizer,
    }


def demo_context() -> dict:
    """Демо-значения для превью в редакторе (реальных данных ещё нет)."""
    import datetime
    return {
        'fio': 'Божескова Ангелина Алексеевна',
        'event': 'Встреча академического кадрового резерва НИУ ВШЭ',
        'event_date': event_date_label(datetime.date(2025, 3, 12), datetime.date(2025, 3, 12)),
        'hours': '2,5',
        'organizer': 'Центр лидерства и волонтёрства НИУ ВШЭ',
    }


def _fmt_hours(hours) -> str:
    """Часы как «2,5» (запятая) / «3» (без дробной части) — как на макете."""
    if hours is None:
        return ''
    if float(hours) == int(hours):
        return str(int(hours))
    return f'{hours}'.replace('.', ',')


# --- Рендер PDF --------------------------------------------------------------

def _resolve_text(field, ctx) -> str:
    """Текст поля: для custom — заранее заданный текст поля, иначе значение из контекста."""
    key = field.get('key')
    if key == 'custom':
        return field.get('text', '') or ''
    return ctx.get(key, '') or ''


def render_letter_pdf(template, ctx) -> bytes:
    """Штампует значения `ctx` в поля `template.fields_json` поверх PDF-фона.

    Координаты полей — в долях [0..1] от размера страницы; переводим в пункты по
    фактическому размеру страницы фона. Шрифт каждого поля берём из БД по font_id
    (fontfile), поэтому кириллица и внешний вид одинаковы на любой ОС. Возвращает
    PDF-байты (одна страница)."""
    doc = fitz.open(stream=bytes(template.background_pdf), filetype='pdf')
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height

    # Кэш зарегистрированных в документе шрифтов: имя fitz → уже вставленный fontfile.
    font_cache = {}
    tmp_files = []
    try:
        for idx, field in enumerate(template.fields_json or []):
            text = _resolve_text(field, ctx)
            if not text:
                continue
            x = float(field.get('x', 0)) * pw
            y = float(field.get('y', 0)) * ph
            w = float(field.get('w', 0)) * pw
            h = float(field.get('h', 0)) * ph
            rect = fitz.Rect(x, y, x + w, y + h)
            size = float(field.get('size', 18))
            color = _hex_to_rgb(field.get('color', '#000000'))
            align = _ALIGN.get(field.get('align', 'left'), fitz.TEXT_ALIGN_LEFT)

            font_id = field.get('font_id')
            fontname, fontfile = _font_for(font_id, font_cache, tmp_files)

            # Подбираем кегль ДО реальной вставки на страницу (dry-run на отдельной
            # временной странице), затем рисуем ОДИН раз. Иначе несколько неудачных
            # insert_textbox наложили бы полупрозрачные слои текста разного размера.
            s = _fit_font_size(text, rect, fontname, fontfile, size, align)
            page.insert_textbox(
                rect, text, fontname=fontname, fontfile=fontfile,
                fontsize=s, color=color, align=align,
            )
        return doc.tobytes()
    finally:
        for p in tmp_files:
            try:
                os.remove(p)
            except OSError:
                pass
        doc.close()


def _fit_font_size(text, rect, fontname, fontfile, size, align, min_size=6):
    """Наибольший кегль ≤ `size`, при котором текст влезает в рамку `rect`. Проверяем
    dry-run'ом на отдельной временной странице того же размера (insert_textbox
    возвращает ≥0, когда всё поместилось), НИЧЕГО не рисуя на реальной странице.
    Если не влезает даже на min_size — возвращаем min_size (текст обрежется рамкой)."""
    probe = fitz.open()
    ppage = probe.new_page(width=rect.width + 2, height=rect.height + 2)
    prect = fitz.Rect(1, 1, 1 + rect.width, 1 + rect.height)
    try:
        s = float(size)
        while s >= min_size:
            rc = ppage.insert_textbox(
                prect, text, fontname=fontname, fontfile=fontfile,
                fontsize=s, align=align,
            )
            if rc >= 0:
                return s
            # На каждой пробе страница копится — берём чистую, чтобы прошлые вставки
            # не влияли (insert возвращает остаток высоты относительно уже занятого).
            probe.delete_page(0)
            ppage = probe.new_page(width=rect.width + 2, height=rect.height + 2)
            s -= 1
        return float(min_size)
    finally:
        probe.close()


def _font_for(font_id, cache, tmp_files):
    """Возвращает (fontname, fontfile) для fitz. Файл шрифта из БД пишем во временный
    файл (fitz.insert_textbox принимает путь). Имя шрифта в документе уникально на
    font_id, чтобы PyMuPDF не переопределял один и тот же ресурс."""
    key = font_id or 'default'
    if key in cache:
        return cache[key]

    font = dc.get_letter_font_by_id(font_id) if font_id else None
    if font is None:
        # дефолт — первый встроенный (DejaVu Sans); гарантирован ensure_builtin_fonts.
        ensure_builtin_fonts()
        font = dc.get_letter_font_by_name('DejaVu Sans')

    import tempfile
    fd, path = tempfile.mkstemp(suffix='.ttf')
    with os.fdopen(fd, 'wb') as f:
        f.write(bytes(font.font_file))
    tmp_files.append(path)
    fontname = f'F{key}'
    cache[key] = (fontname, path)
    return cache[key]


def _hex_to_rgb(value):
    """'#RRGGBB' → (r,g,b) в долях [0..1] для fitz. Некорректное → чёрный."""
    try:
        v = value.lstrip('#')
        r = int(v[0:2], 16) / 255
        g = int(v[2:4], 16) / 255
        b = int(v[4:6], 16) / 255
        return (r, g, b)
    except (ValueError, AttributeError, IndexError):
        return (0, 0, 0)


def background_page_png(template, dpi=120) -> bytes:
    """Первая страница PDF-фона как PNG — подложка редактора (без штамповки полей).
    Растрируем через PyMuPDF (не зависим от внешних вьюеров/CDN)."""
    doc = fitz.open(stream=bytes(template.background_pdf), filetype='pdf')
    try:
        pix = doc[0].get_pixmap(dpi=dpi)
        return pix.tobytes('png')
    finally:
        doc.close()


def read_pdf_page_size(pdf_bytes) -> tuple:
    """(width_pt, height_pt) первой страницы загруженного PDF — сохраняем в шаблон
    как эталон для пересчёта относительных координат."""
    doc = fitz.open(stream=bytes(pdf_bytes), filetype='pdf')
    try:
        r = doc[0].rect
        return (r.width, r.height)
    finally:
        doc.close()
