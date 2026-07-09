"""Генерация отчётов в DOCX (python-docx) — заменяет прежний PDF-рендер.

Никаких системных зависимостей (в отличие от WeasyPrint/GTK): чистый Python.
Графики рисуются matplotlib в PNG (blog/services/charts.py) и вставляются картинками.

Тут — тонкий билдер-обёртка `DocxBuilder` над python-docx (заголовки, таблицы,
key-value блоки, картинки) и хелпер `docx_response` для отдачи .docx как HttpResponse.
Сборка конкретных отчётов — в blog/services/report_builders.py.
"""
import io

from django.http import HttpResponse

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


ACCENT = RGBColor(0x7C, 0x3A, 0xED)
MUTED = RGBColor(0x83, 0x83, 0x8F)


class DocxBuilder:
    def __init__(self):
        self.doc = Document()
        self._base_style()

    def _base_style(self):
        style = self.doc.styles['Normal']
        style.font.name = 'Calibri'
        style.font.size = Pt(10)

    # ---- Заголовки ----
    def title(self, text, subtitle=None, tag=None):
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(18)
        run.font.color.rgb = ACCENT
        if subtitle:
            sp = self.doc.add_paragraph()
            srun = sp.add_run(subtitle)
            srun.font.size = Pt(9)
            srun.font.color.rgb = MUTED
        if tag:
            tp = self.doc.add_paragraph()
            trun = tp.add_run(tag)
            trun.font.size = Pt(8)
            trun.font.color.rgb = MUTED
        return self

    def h2(self, text):
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(14)
        run.font.color.rgb = ACCENT
        return self

    def h3(self, text):
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(11)
        return self

    def note(self, text):
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        run.font.size = Pt(8)
        run.font.color.rgb = MUTED
        return self

    def para(self, text):
        self.doc.add_paragraph(text)
        return self

    def page_break(self):
        self.doc.add_page_break()
        return self

    # ---- Key-value блок (таблица без границ) ----
    def kv(self, rows):
        """rows: [(ключ, значение), ...]. Пустые/None пропускаются."""
        rows = [(k, v) for k, v in rows if v is not None]
        if not rows:
            return self
        table = self.doc.add_table(rows=len(rows), cols=2)
        for i, (k, v) in enumerate(rows):
            kcell, vcell = table.rows[i].cells
            krun = kcell.paragraphs[0].add_run(str(k))
            krun.font.color.rgb = MUTED
            krun.font.size = Pt(9)
            vcell.paragraphs[0].add_run(str(v)).font.size = Pt(10)
        return self

    # ---- Таблица с шапкой ----
    def table(self, headers, rows, empty='Нет данных.'):
        """headers: [...], rows: [[...], ...]."""
        if not rows:
            self.note(empty)
            return self
        table = self.doc.add_table(rows=1, cols=len(headers))
        table.style = 'Light Grid Accent 1'
        hdr = table.rows[0].cells
        for i, h in enumerate(headers):
            run = hdr[i].paragraphs[0].add_run(str(h))
            run.bold = True
            run.font.size = Pt(9)
        for row in rows:
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].paragraphs[0].add_run('' if val is None else str(val)).font.size = Pt(9)
        return self

    # ---- Картинка из data-URI (или сырых PNG-байт) ----
    def image_data_uri(self, data_uri, width_inches=6.3):
        import base64
        if not data_uri:
            return self
        b64 = data_uri.split(',', 1)[1] if data_uri.startswith('data:') else data_uri
        raw = base64.b64decode(b64)
        self.doc.add_picture(io.BytesIO(raw), width=Inches(width_inches))
        return self

    def build_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.doc.save(buf)
        return buf.getvalue()


def docx_response(builder: DocxBuilder, filename: str) -> HttpResponse:
    response = HttpResponse(
        builder.build_bytes(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
