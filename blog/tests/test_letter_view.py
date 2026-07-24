"""Тесты просмотра/скачивания благодарственных писем волонтёром (letter_view,
letters_download_all, blog/views/profiles.py) — то, что не покрыл
test_letter_templates.py (там тестируется конструктор/рендер-сервис, не сама
страница просмотра письма и ACL к ней).
"""
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


def _make_letter_with_background():
    letter_render.ensure_builtin_fonts()
    font = dc.get_letter_font_by_name('DejaVu Sans')
    tpl = ThankYouLetterTemplate.objects.create(title='Шаблон письма')
    pdf = _blank_pdf()
    w, h = letter_render.read_pdf_page_size(pdf)
    dc.set_letter_background(tpl, pdf, 'bg.pdf', w, h)
    dc.set_letter_fields(tpl, [
        {'key': 'fio', 'x': 0.1, 'y': 0.4, 'w': 0.8, 'h': 0.1,
         'font_id': font.id, 'size': 24, 'color': '#000000', 'align': 'left'},
    ])
    return tpl


class LetterViewTests(TestCase):
    def setUp(self):
        self.volunteer = f.make_user()
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=-1)
        f.make_participation(self.volunteer, self.shift, status='attended', hours=4)

    def test_no_letter_template_forbidden(self):
        self.client.force_login(self.volunteer)
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]))
        self.assertEqual(r.status_code, 403)

    def test_html_fallback_without_background(self):
        tpl = ThankYouLetterTemplate.objects.create(title='Без фона')
        self.event.letter = tpl
        self.event.save(update_fields=['letter'])
        self.client.force_login(self.volunteer)
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0], 'text/html')

    def test_pdf_background_view_returns_png(self):
        tpl = _make_letter_with_background()
        self.event.letter = tpl
        self.event.save(update_fields=['letter'])
        self.client.force_login(self.volunteer)
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')

    def test_pdf_background_download_returns_pdf(self):
        tpl = _make_letter_with_background()
        self.event.letter = tpl
        self.event.save(update_fields=['letter'])
        self.client.force_login(self.volunteer)
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]), {'download': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_no_attendance_forbidden(self):
        tpl = _make_letter_with_background()
        self.event.letter = tpl
        self.event.save(update_fields=['letter'])
        outsider = f.make_user()
        self.client.force_login(outsider)
        r = self.client.get(reverse('letter_view', args=[outsider.id, self.event.id]))
        self.assertEqual(r.status_code, 403)

    def test_stranger_cannot_view_others_letter(self):
        tpl = _make_letter_with_background()
        self.event.letter = tpl
        self.event.save(update_fields=['letter'])
        stranger = f.make_user()
        self.client.force_login(stranger)
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]))
        self.assertEqual(r.status_code, 403)

    def test_manager_can_view_any_letter(self):
        tpl = _make_letter_with_background()
        self.event.letter = tpl
        self.event.save(update_fields=['letter'])
        manager = f.make_manager()
        self.client.force_login(manager)
        r = self.client.get(reverse('letter_view', args=[self.volunteer.id, self.event.id]))
        self.assertEqual(r.status_code, 200)


class LettersDownloadAllTests(TestCase):
    def setUp(self):
        self.volunteer = f.make_user()

    def test_no_letters_returns_404(self):
        self.client.force_login(self.volunteer)
        r = self.client.get(reverse('letters_download_all', args=[self.volunteer.id]))
        self.assertEqual(r.status_code, 404)

    def test_zip_with_one_letter(self):
        tpl = _make_letter_with_background()
        event = f.make_event()
        shift = f.make_shift(event, days_from_now=-1)
        f.make_participation(self.volunteer, shift, status='attended', hours=3)
        event.letter = tpl
        event.save(update_fields=['letter'])

        self.client.force_login(self.volunteer)
        r = self.client.get(reverse('letters_download_all', args=[self.volunteer.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/zip')

    def test_stranger_forbidden(self):
        stranger = f.make_user()
        self.client.force_login(stranger)
        r = self.client.get(reverse('letters_download_all', args=[self.volunteer.id]))
        self.assertEqual(r.status_code, 403)
