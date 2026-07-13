"""Пайплайн генерации PDF справки ПГАС: .docx (с сохранённым оформлением) →
LibreOffice конвертирует в PDF → PyMuPDF растрирует страницы в «картиночный» PDF
(текст нельзя выделить/скопировать — каждая страница вставлена как изображение).

Здесь — единственное место, зависящее от системных бинарей: LibreOffice (`soffice`)
для docx→pdf и PyMuPDF (самодостаточен) для растра. Проверять генерацию нужно на
проде (Docker-образ несёт libreoffice-writer; локально на Windows soffice обычно
нет — конвертация упадёт, это ожидаемо)."""
import os
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.http import HttpResponse

# Путь к бинарю LibreOffice. Переопределяется настройкой SOFFICE_BIN при нужде.
SOFFICE_BIN = getattr(settings, 'SOFFICE_BIN', 'soffice')


def docx_to_pdf_bytes(docx_bytes: bytes, timeout: int = 120) -> bytes:
    """.docx → PDF-байты через LibreOffice (`soffice --headless --convert-to pdf`).

    Пишем docx во временную директорию, конвертируем туда же и читаем результат.
    `-env:UserInstallation` в отдельный tmp-профиль — чтобы параллельные вызовы не
    конфликтовали за общий профиль LibreOffice (иначе второй процесс падает)."""
    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, 'template.docx')
        with open(src_path, 'wb') as f:
            f.write(docx_bytes)

        profile = os.path.join(tmp, 'lo_profile')
        cmd = [
            SOFFICE_BIN, '--headless', '--norestore',
            f'-env:UserInstallation=file://{profile}',
            '--convert-to', 'pdf', '--outdir', tmp, src_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
        )
        pdf_path = os.path.join(tmp, 'template.pdf')
        if result.returncode != 0 or not os.path.exists(pdf_path):
            raise RuntimeError(
                f'LibreOffice не сконвертировал docx→pdf (code={result.returncode}): '
                f'{result.stderr.decode(errors="replace")[:500]}'
            )
        with open(pdf_path, 'rb') as f:
            return f.read()


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


def certificate_pdf_from_docx(docx_bytes: bytes) -> bytes:
    """Полный пайплайн справки: docx → PDF (LibreOffice) → «картиночный» PDF-байты."""
    return pdf_to_image_pdf(docx_to_pdf_bytes(docx_bytes))


def soffice_available() -> bool:
    """Есть ли LibreOffice в системе (для дружелюбной ошибки вместо стектрейса)."""
    return bool(shutil.which(SOFFICE_BIN))


def certificate_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    """Отдаёт PDF как вложение (скачивание)."""
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
