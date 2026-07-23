"""Тесты конструктора благодарственных писем (letter-templates.md).

Проверяем кросс-платформенное ядро (PyMuPDF-штамповка, встроенные шрифты, диапазон
дат) и поведение вьюх: редактор, сохранение полей, превью, fallback letter_view на
HTML при отсутствии PDF-фона.
"""
import datetime
import json

import fitz
from django.test import TestCase
from django.urls import reverse

from blog.models import ThankYouLetterTemplate
from blog.services import letter_render
from data_base import data_controller as dc
from . import factories as f


def _blank_pdf(width=842, height=595):
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    data = doc.tobytes()
    doc.close()
    return data


class LetterRenderServiceTests(TestCase):
    def test_ensure_builtin_fonts_idempotent(self):
        letter_render.ensure_builtin_fonts()
        n1 = dc.letter_fonts_qs().count()
        letter_render.ensure_builtin_fonts()
        self.assertEqual(dc.letter_fonts_qs().count(), n1)
        self.assertGreaterEqual(n1, 1)
        self.assertIsNotNone(dc.get_letter_font_by_name('DejaVu Sans'))

    def test_event_date_label_single_and_range(self):
        d1 = datetime.date(2025, 3, 12)
        self.assertEqual(letter_render.event_date_label(d1, d1), '12 марта 2025')
        d2 = datetime.date(2025, 3, 14)
        self.assertEqual(letter_render.event_date_label(d1, d2), '12 марта — 14 марта 2025')
        # разные годы — год у обеих дат
        d3 = datetime.date(2026, 1, 5)
        self.assertIn('2025', letter_render.event_date_label(d1, d3))
        self.assertIn('2026', letter_render.event_date_label(d1, d3))

    def test_fmt_hours(self):
        self.assertEqual(letter_render._fmt_hours(3), '3')
        self.assertEqual(letter_render._fmt_hours(2.5), '2,5')

    def test_render_letter_pdf_produces_pdf(self):
        letter_render.ensure_builtin_fonts()
        font = dc.get_letter_font_by_name('DejaVu Sans')
        tpl = ThankYouLetterTemplate.objects.create(title='t')
        pdf = _blank_pdf()
        w, h = letter_render.read_pdf_page_size(pdf)
        dc.set_letter_background(tpl, pdf, 'bg.pdf', w, h)
        dc.set_letter_fields(tpl, [
            {'key': 'fio', 'x': 0.1, 'y': 0.4, 'w': 0.8, 'h': 0.1,
             'font_id': font.id, 'size': 24, 'color': '#000000', 'align': 'left'},
            {'key': 'custom', 'text': 'Спасибо!', 'x': 0.1, 'y': 0.6, 'w': 0.5, 'h': 0.06,
             'font_id': font.id, 'size': 16, 'color': '#333333', 'align': 'center'},
        ])
        out = letter_render.render_letter_pdf(tpl, letter_render.demo_context())
        self.assertTrue(out.startswith(b'%PDF'))
        # результат читается обратно и содержит наш текст
        doc = fitz.open(stream=out, filetype='pdf')
        text = doc[0].get_text()
        doc.close()
        self.assertIn('Спасибо', text)

    def test_background_png(self):
        tpl = ThankYouLetterTemplate.objects.create(title='t')
        pdf = _blank_pdf()
        w, h = letter_render.read_pdf_page_size(pdf)
        dc.set_letter_background(tpl, pdf, 'bg.pdf', w, h)
        png = letter_render.background_page_png(tpl)
        self.assertTrue(png.startswith(b'\x89PNG'))


class LetterViewTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)

    def test_create_and_editor_flow(self):
        # создать шаблон (без фона)
        r = self.client.post(reverse('letter_template_create'), {'title': 'Благодарность'})
        self.assertIn(r.status_code, (200, 302))
        tpl = ThankYouLetterTemplate.objects.get(title='Благодарность')

        # редактор открывается (без фона — показывает шаг загрузки)
        r = self.client.get(reverse('letter_template_editor', args=[tpl.id]))
        self.assertEqual(r.status_code, 200)

        # загрузить фон
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf = _blank_pdf()
        r = self.client.post(
            reverse('letter_template_upload_bg', args=[tpl.id]),
            {'title': 'Благодарность',
             'background_pdf_file': SimpleUploadedFile('bg.pdf', pdf, content_type='application/pdf')},
        )
        self.assertEqual(r.status_code, 302)
        tpl.refresh_from_db()
        self.assertTrue(tpl.has_background)
        self.assertTrue(tpl.page_width_pt and tpl.page_height_pt)

        # сохранить поля (AJAX JSON)
        letter_render.ensure_builtin_fonts()
        font = dc.get_letter_font_by_name('DejaVu Sans')
        fields = [{'key': 'fio', 'x': 0.1, 'y': 0.3, 'w': 0.8, 'h': 0.1,
                   'font_id': font.id, 'size': 24, 'color': '#000000', 'align': 'left'}]
        r = self.client.post(
            reverse('letter_template_save_fields', args=[tpl.id]),
            data=json.dumps(fields), content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        tpl.refresh_from_db()
        self.assertEqual(len(tpl.fields_json), 1)

        # превью PDF
        r = self.client.get(reverse('letter_template_preview', args=[tpl.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

        # PNG-подложка
        r = self.client.get(reverse('letter_template_background', args=[tpl.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')

    def test_settings_letters_panel_ajax(self):
        r = self.client.get(reverse('letter_template_list'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Шаблоны писем')

    def test_font_upload_rejects_non_font(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.client.post(
            reverse('letter_font_upload'),
            {'name': 'Плохой', 'font_upload': SimpleUploadedFile('x.ttf', b'not a font', content_type='font/ttf')},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['ok'])


class LetterViewIntegrationTests(TestCase):
    """letter_view отдаёт PDF при наличии фона и HTML — при его отсутствии (fallback)."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.volunteer = f.make_user()
        self.event = f.make_event(title='Меро')
        self.shift = f.make_shift(self.event)
        # участие с явкой — обязательное условие letter_view
        from blog.models import Participation
        Participation.objects.create(
            user=self.volunteer, event_day=self.shift, status='attended', hours=3,
        )

    def test_letter_view_html_fallback_without_background(self):
        letter = ThankYouLetterTemplate.objects.create(title='Текстовый шаблон')
        self.event.letter = letter
        self.event.save(update_fields=['letter'])
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/html; charset=utf-8')

    def test_letter_view_pdf_with_background(self):
        letter = ThankYouLetterTemplate.objects.create(title='PDF шаблон')
        pdf = _blank_pdf()
        w, h = letter_render.read_pdf_page_size(pdf)
        dc.set_letter_background(letter, pdf, 'bg.pdf', w, h)
        letter_render.ensure_builtin_fonts()
        font = dc.get_letter_font_by_name('DejaVu Sans')
        dc.set_letter_fields(letter, [
            {'key': 'fio', 'x': 0.1, 'y': 0.3, 'w': 0.8, 'h': 0.1,
             'font_id': font.id, 'size': 24, 'color': '#000000', 'align': 'left'},
        ])
        self.event.letter = letter
        self.event.save(update_fields=['letter'])
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
