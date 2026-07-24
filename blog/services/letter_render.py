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

# name → имя файла шрифта. DejaVu покрывает кириллицу. Файлы ВЕНДОРИМ в репозиторий
# (blog/static/blog/fonts/) — рендер не должен зависеть от того, установлен ли на проде
# matplotlib (иначе любой сбой его импорта = 500 на каждом письме).
BUILTIN_FONTS = {
    'DejaVu Sans': 'DejaVuSans.ttf',
    'DejaVu Sans Bold': 'DejaVuSans-Bold.ttf',
    'DejaVu Serif': 'DejaVuSerif.ttf',
    'DejaVu Serif Bold': 'DejaVuSerif-Bold.ttf',
    'DejaVu Sans Mono': 'DejaVuSansMono.ttf',
}


def _builtin_font_dirs():
    """Каталоги, где ищем файлы встроенных шрифтов, в порядке приоритета:
    1) вендоренная копия в репозитории (надёжно на любом окружении);
    2) matplotlib mpl-data (fallback, если по какой-то причине вендор отсутствует)."""
    from django.conf import settings
    dirs = [os.path.join(settings.BASE_DIR, 'blog', 'static', 'blog', 'fonts')]
    try:
        import matplotlib
        dirs.append(os.path.join(os.path.dirname(matplotlib.__file__), 'mpl-data', 'fonts', 'ttf'))
    except Exception:
        pass
    return dirs


def ensure_builtin_fonts():
    """Досоздаёт встроенные шрифты в таблице letter_fonts, если их ещё нет (ленивая
    инициализация вместо data-миграции, coding-principles §9). Идемпотентна.
    Не бросает исключение, если файл шрифта не найден — просто пропускает его."""
    dirs = _builtin_font_dirs()
    for name, filename in BUILTIN_FONTS.items():
        if dc.get_letter_font_by_name(name):
            continue
        for d in dirs:
            path = os.path.join(d, filename)
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    data = f.read()
                dc.create_letter_font(name=name, data=data, filename=filename, is_builtin=True)
                break


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


def _stamped_doc(template, ctx):
    """Открывает PDF-фон и штампует значения `ctx` в поля `template.fields_json`.
    Возвращает fitz.Document (вызывающий обязан закрыть). Общее ядро для PDF и PNG.

    Координаты полей — в долях [0..1] от размера страницы; переводим в пункты по
    фактическому размеру страницы фона. Шрифт каждого поля грузим из БД байтами
    (`fitz.Font(fontbuffer=...)`) и рисуем через `TextWriter` — БЕЗ временных файлов и
    путей на диске: важно для прод-хостинга с ограниченным/недоступным /tmp."""
    doc = fitz.open(stream=bytes(template.background_pdf), filetype='pdf')
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height

    font_cache = {}  # font_id → fitz.Font (грузим из БД один раз)
    for field in (template.fields_json or []):
        text = _resolve_text(field, ctx)
        if not text:
            continue
        x = float(field.get('x', 0)) * pw
        y = float(field.get('y', 0)) * ph
        w = float(field.get('w', 0)) * pw
        h = float(field.get('h', 0)) * ph
        if w <= 1 or h <= 1:
            continue  # вырожденная рамка — нечего рисовать
        rect = fitz.Rect(x, y, x + w, y + h)
        size = float(field.get('size', 18) or 18)
        color = _hex_to_rgb(field.get('color', '#000000'))
        align = _ALIGN.get(field.get('align', 'left'), fitz.TEXT_ALIGN_LEFT)
        font = _font_for(field.get('font_id'), font_cache)

        _draw_textbox(page, rect, text, font, size, color, align)
    return doc


def render_letter_pdf(template, ctx) -> bytes:
    """Готовое письмо как PDF-байты (одна страница) — для скачивания/печати."""
    doc = _stamped_doc(template, ctx)
    try:
        return doc.tobytes()
    finally:
        doc.close()


def render_letter_png(template, ctx, dpi=150) -> bytes:
    """Готовое письмо как PNG — для просмотра «картинкой» в модалке (как фото в ленте),
    без браузерного PDF-вьюера с панелью печати. Растрируем через PyMuPDF."""
    doc = _stamped_doc(template, ctx)
    try:
        pix = doc[0].get_pixmap(dpi=dpi)
        return pix.tobytes('png')
    finally:
        doc.close()


def _draw_textbox(page, rect, text, font, size, color, align, min_size=6):
    """Рисует `text` в рамке `rect` шрифтом `font` (fitz.Font из байтов), подбирая
    наибольший кегль ≤ size, при котором текст влезает. Использует TextWriter (без
    временных файлов). `fill_textbox` возвращает остаток невлезшего текста — если он
    пуст, всё поместилось."""
    s = float(size)
    while s >= min_size:
        tw = fitz.TextWriter(page.rect, color=color)
        try:
            leftover = tw.fill_textbox(rect, text, font=font, fontsize=s, align=align)
        except Exception:
            leftover = None
        # fill_textbox возвращает список невместившихся слов (пустой = всё влезло).
        if not leftover:
            tw.write_text(page)
            return
        s -= 1
    # Не влезло даже на min_size — рисуем как есть (обрежется рамкой), лишь бы не пусто.
    tw = fitz.TextWriter(page.rect, color=color)
    try:
        tw.fill_textbox(rect, text, font=font, fontsize=min_size, align=align)
        tw.write_text(page)
    except Exception:
        pass


def _font_for(font_id, cache):
    """fitz.Font из байтов шрифта в БД (без временного файла). Дефолт — встроенный
    DejaVu Sans (кириллица), досоздаётся лениво. Результат кэшируется на рендер."""
    key = font_id or 'default'
    if key in cache:
        return cache[key]

    font_row = dc.get_letter_font_by_id(font_id) if font_id else None
    if font_row is None:
        ensure_builtin_fonts()
        font_row = dc.get_letter_font_by_name('DejaVu Sans')
    if font_row is None:
        # крайний случай — встроенного шрифта нет в БД: берём файл напрямую из вендора.
        cache[key] = fitz.Font(fontbuffer=_default_font_bytes())
        return cache[key]

    cache[key] = fitz.Font(fontbuffer=bytes(font_row.font_file))
    return cache[key]


def _default_font_bytes() -> bytes:
    """Байты дефолтного встроенного шрифта из вендоренного файла (последний рубеж,
    если в БД шрифтов нет вообще)."""
    for d in _builtin_font_dirs():
        path = os.path.join(d, 'DejaVuSans.ttf')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
    raise RuntimeError('Не найден дефолтный шрифт DejaVuSans.ttf')


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
