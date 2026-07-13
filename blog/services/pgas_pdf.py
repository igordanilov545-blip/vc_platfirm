"""Пайплайн генерации PDF справки ПГАС: HTML → WeasyPrint → PDF → PyMuPDF растр
в «картиночный» PDF (текст нельзя выделить/скопировать — каждая страница вставлена
как изображение).

Здесь — единственное место, зависящее от системных библиотек (WeasyPrint требует
cairo/pango; PyMuPDF — самодостаточен). Импорты weasyprint/fitz — ЛЕНИВЫЕ (внутри
функций), чтобы `manage.py check` и локальная разработка на Windows (где WeasyPrint
не установлен) не падали на импорте модуля. Проверять генерацию нужно на проде
(Docker-образ уже несёт cairo/pango; локально Windows не показателен)."""
from django.http import HttpResponse


def html_to_pdf_bytes(html: str, base_url: str = None) -> bytes:
    """HTML-строка → PDF-байты через WeasyPrint. base_url нужен, если в HTML есть
    относительные ссылки на статику/шрифты (у нас всё инлайново — можно None)."""
    from weasyprint import HTML

    return HTML(string=html, base_url=base_url).write_pdf()


def pdf_to_image_pdf(pdf_bytes: bytes, dpi: int = 170) -> bytes:
    """PDF → PDF, где каждая страница — растровое изображение исходной (текст не
    извлекается). Открываем исходный PDF в PyMuPDF, рендерим каждую страницу в PNG
    заданного dpi и собираем новый PDF: страница того же размера, на всю площадь
    которой вставлена картинка. dpi=170 — компромисс качество/размер для A4."""
    import fitz  # PyMuPDF

    src = fitz.open(stream=pdf_bytes, filetype='pdf')
    out = fitz.open()
    zoom = dpi / 72.0  # 72 pt = 1 inch, matrix-масштаб под нужный dpi
    matrix = fitz.Matrix(zoom, zoom)
    try:
        for page in src:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png = pix.tobytes('png')
            new_page = out.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(page.rect, stream=png)
        return out.tobytes()
    finally:
        src.close()
        out.close()


def certificate_pdf_bytes(html: str) -> bytes:
    """Полный пайплайн: HTML → PDF → «картиночный» PDF-байты."""
    return pdf_to_image_pdf(html_to_pdf_bytes(html))


def certificate_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    """Отдаёт PDF как вложение (скачивание)."""
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
