"""Excel-импорт заявок (blog/views/applications.py: import_preview/import_commit,
blog/services/import_applications.py) — не был покрыт ни одним тестом, несмотря на
задокументированный в CLAUDE.md §4 инвариант «дедупликация по паре (человек,
мероприятие), не по всем полям» и «отменённые волонтёром заявки импорт не
воскрешает». Строим реальный .xlsx через openpyxl и гоняем полный пайплайн
превью → коммит через HTTP, как это делает менеджер в браузере.
"""
import io

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from blog.models import Application
from . import factories as f


def _xlsx_upload(rows, header=None):
    header = header or ['Мероприятие', 'Автор', 'Фамилия', 'Телеграм', 'Телефон', 'Функция']
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile('import.xlsx', buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


class ImportPreviewTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event(title='Импорт-меро')

    def test_preview_matches_existing_event(self):
        upload = _xlsx_upload([['Импорт-меро', 'Аня', 'Иванова', 'anya', '+79990001122', '']])
        r = self.client.post(reverse('import_preview'), {'excel_file': upload})
        self.assertEqual(r.status_code, 200)
        rows = self.client.session['import_rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event_id'], self.event.id)
        self.assertFalse(rows[0]['event_missing'])

    def test_preview_missing_event_flagged(self):
        upload = _xlsx_upload([['Несуществующее меро', 'Аня', 'Иванова', 'anya', '', '']])
        r = self.client.post(reverse('import_preview'), {'excel_file': upload})
        self.assertEqual(r.status_code, 200)
        rows = self.client.session['import_rows']
        self.assertTrue(rows[0]['event_missing'])

    def test_preview_missing_name_column_errors(self):
        upload = _xlsx_upload([['Импорт-меро', '', '', '', '', '']], header=['Мероприятие', 'X', 'X', 'X', 'X', 'X'])
        r = self.client.post(reverse('import_preview'), {'excel_file': upload})
        self.assertEqual(r.status_code, 200)
        self.assertIn('обязательные колонки', ' '.join(self.client.session.get('import_rows') and [] or r.context['errors']))

    def test_forbidden_for_volunteer(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.get(reverse('import_preview'))
        self.assertEqual(r.status_code, 403)


class ImportCommitTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event(title='Импорт-меро')

    def _upload_and_commit(self, rows, header=None):
        upload = _xlsx_upload(rows, header=header)
        self.client.post(reverse('import_preview'), {'excel_file': upload})
        return self.client.post(reverse('import_commit'))

    def test_commit_creates_application_and_user(self):
        r = self._upload_and_commit([['Импорт-меро', 'Аня', 'Иванова', 'anya_tg', '+79990001122', '']])
        self.assertEqual(r.status_code, 302)
        app = Application.objects.get(event=self.event, first_name='Аня')
        self.assertIsNotNone(app.user_id)
        self.assertEqual(app.user.telegram_username, 'anya_tg')

    def test_commit_blocked_while_event_missing(self):
        upload = _xlsx_upload([['Нет такого меро', 'Аня', 'Иванова', '', '', '']])
        self.client.post(reverse('import_preview'), {'excel_file': upload})
        r = self.client.post(reverse('import_commit'))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Application.objects.filter(first_name='Аня').exists())

    def test_repeat_import_updates_not_duplicates(self):
        """CLAUDE.md §4: дедуп по (человек, мероприятие), повторная загрузка
        обновляет существующую заявку, а не плодит дубль."""
        self._upload_and_commit([['Импорт-меро', 'Аня', 'Иванова', 'anya_tg', '+79990001122', 'Регистратор']])
        self.assertEqual(Application.objects.filter(event=self.event, telegram_username='anya_tg').count(), 1)

        r = self._upload_and_commit([['Импорт-меро', 'Аня', 'Иванова', 'anya_tg', '+79990001122', 'Фотограф']])
        self.assertEqual(r.status_code, 302)
        apps = Application.objects.filter(event=self.event, telegram_username='anya_tg')
        self.assertEqual(apps.count(), 1, 'повторный импорт того же человека на то же меро не должен плодить дубль')

    def test_cancelled_application_not_resurrected(self):
        """CLAUDE.md §4: отменённые волонтёром заявки импорт не воскрешает."""
        volunteer = f.make_user(telegram_username='anya_tg', phone='+79990001122', first_name='Аня', last_name='Иванова')
        cancelled = f.make_application(self.event, user=volunteer, status='cancelled')

        self._upload_and_commit([['Импорт-меро', 'Аня', 'Иванова', 'anya_tg', '+79990001122', '']])

        apps = Application.objects.filter(event=self.event, user=volunteer)
        self.assertEqual(apps.count(), 2, 'должна появиться НОВАЯ заявка, а не воскрешение отменённой')
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, 'cancelled', 'отменённая заявка не должна была измениться')

    def test_matched_existing_user_reused(self):
        """Матчинг по telegram_username → существующий пользователь переиспользуется,
        не создаётся дубль-профиль."""
        from blog.models import User
        existing = f.make_user(telegram_username='anya_tg')
        before_count = User.objects.count()

        self._upload_and_commit([['Импорт-меро', 'Аня', 'Иванова', 'anya_tg', '', '']])

        self.assertEqual(User.objects.count(), before_count)
        app = Application.objects.get(event=self.event, telegram_username='anya_tg')
        self.assertEqual(app.user_id, existing.id)
