"""Smoke-тесты отчётов и экспортов (blog/views/reports.py).

Самый рискованный участок из testing-audit.md: генераторы PDF/DOCX/Excel нигде не
тестировались, регрессия обычно проявляется как исключение внутри openpyxl/reportlab/
python-docx, которое смоук-тест ловит сразу (в отличие от «страница вроде открылась»).
Тесты не проверяют содержимое бинарников — только что генерация не падает 500 и отдаёт
ожидаемый content-type, на пустых и на непустых данных (пустой охват — частый краевой
случай, из-за которого агрегаты/графики могут упасть на делении на ноль и т.п.).
"""
from django.test import TestCase
from django.urls import reverse

from . import factories as f


class ReportPeriodHubTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event)

    def test_shell_page(self):
        r = self.client.get(reverse('report_period'))
        self.assertEqual(r.status_code, 200)

    def test_dashboard_panel_partial(self):
        r = self.client.get(reverse('report_period'), {'view': 'dashboard', 'partial': '1'})
        self.assertEqual(r.status_code, 200)

    def test_tables_panel_each_table(self):
        for table in ['volunteers', 'events', 'teamleaders', 'managers', 'applications']:
            r = self.client.get(reverse('report_period'), {'view': 'tables', 'partial': '1', 'table': table})
            self.assertEqual(r.status_code, 200, f'table={table}')

    def test_dobro_panel(self):
        r = self.client.get(reverse('report_period'), {'view': 'dobro', 'partial': '1'})
        self.assertEqual(r.status_code, 200)

    def test_scope_partial(self):
        r = self.client.get(reverse('report_period'), {'scope_partial': '1'})
        self.assertEqual(r.status_code, 200)

    def test_empty_scope_does_not_crash(self):
        """Нет ни одного меро в выбранном периоде — панели не должны падать 500."""
        r = self.client.get(reverse('report_period'), {
            'view': 'dashboard', 'partial': '1',
            'date_from': '2000-01-01', 'date_to': '2000-01-02',
        })
        self.assertEqual(r.status_code, 200)

    def test_events_search(self):
        r = self.client.get(reverse('report_events_search'), {'q': self.event.title[:5]})
        self.assertEqual(r.status_code, 200)
        self.assertIn('events', r.json())

    def test_people_search(self):
        r = self.client.get(reverse('report_people_search'), {'q': ''})
        self.assertEqual(r.status_code, 200)

    def test_organizations_search(self):
        f.make_organization('Поисковая орг')
        r = self.client.get(reverse('report_organizations_search'), {'q': 'Поисковая'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(o['name'] == 'Поисковая орг' for o in r.json()['organizations']))

    def test_forbidden_for_volunteer(self):
        volunteer = f.make_user()
        self.client.force_login(volunteer)
        r = self.client.get(reverse('report_period'))
        self.assertEqual(r.status_code, 403)


class ReportExportsTests(TestCase):
    """Экспорты за период — с данными и на пустом охвате."""

    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event()
        self.shift = f.make_shift(self.event, days_from_now=1)
        self.volunteer = f.make_user()
        app = f.make_application(self.event, user=self.volunteer, shifts=[self.shift], status='approved')
        f.make_participation(self.volunteer, self.shift, status='attended', hours=4)

    def test_period_export_xlsx(self):
        r = self.client.get(reverse('report_period_export'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    def test_period_pdf_external_and_internal(self):
        for variant in ('external', 'internal'):
            r = self.client.get(reverse('report_period_pdf', args=[variant]))
            self.assertEqual(r.status_code, 200, variant)

    def test_period_pdf_invalid_variant_denied(self):
        r = self.client.get(reverse('report_period_pdf', args=['garbage']))
        self.assertEqual(r.status_code, 403)

    def test_bundle_zip(self):
        r = self.client.get(reverse('report_bundle'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/zip')

    def test_complex_pdf(self):
        r = self.client.get(reverse('report_complex_pdf'))
        self.assertEqual(r.status_code, 200)

    def test_event_export_xlsx(self):
        r = self.client.get(reverse('report_event_export', args=[self.event.id]))
        self.assertEqual(r.status_code, 200)

    def test_event_pdf(self):
        r = self.client.get(reverse('report_event_pdf', args=[self.event.id]))
        self.assertEqual(r.status_code, 200)

    def test_person_pdf_all_time_and_period(self):
        r = self.client.get(reverse('report_person_pdf', args=[self.volunteer.id]))
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse('report_person_pdf', args=[self.volunteer.id]), {
            'date_from': '2020-01-01', 'date_to': '2030-01-01',
        })
        self.assertEqual(r.status_code, 200)

    def test_volunteers_pdf(self):
        r = self.client.get(reverse('report_volunteers_pdf'))
        self.assertEqual(r.status_code, 200)

    def test_volunteers_export_xlsx(self):
        r = self.client.get(reverse('report_volunteers_export'))
        self.assertEqual(r.status_code, 200)

    def test_organization_pdf(self):
        org = f.make_organization()
        self.event.organization = org
        self.event.save(update_fields=['organization'])
        r = self.client.get(reverse('report_organization_pdf', args=[org.id]))
        self.assertEqual(r.status_code, 200)

    def test_dobro_export_xlsx(self):
        r = self.client.get(reverse('report_dobro_export'))
        self.assertEqual(r.status_code, 200)

    def test_exports_on_empty_scope_do_not_crash(self):
        """Пустой охват — самый частый источник тихих 500 в отчётах (деление на 0,
        пустые списки для графиков)."""
        empty_qs = {'date_from': '2000-01-01', 'date_to': '2000-01-02'}
        for name, args in [
            ('report_period_export', []), ('report_bundle', []), ('report_complex_pdf', []),
            ('report_dobro_export', []),
        ]:
            r = self.client.get(reverse(name, args=args), empty_qs)
            self.assertEqual(r.status_code, 200, name)
        for variant in ('external', 'internal'):
            r = self.client.get(reverse('report_period_pdf', args=[variant]), empty_qs)
            self.assertEqual(r.status_code, 200, variant)


class DobroToggleTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.client.force_login(self.manager)
        self.event = f.make_event(event_status='finished', dobro_ru_link_kind='unique', dobro_ru_link='https://dobro.ru/e/1')

    def test_dobro_page_redirects_to_hub(self):
        r = self.client.get(reverse('dobro_page'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('view=dobro', r['Location'])

    def test_toggle_flips_logged_flag(self):
        url = reverse('report_dobro_toggle', args=[self.event.id])
        r = self.client.post(url)
        self.assertEqual(r.status_code, 200)
        self.event.refresh_from_db()
        self.assertTrue(self.event.dobro_ru_hours_logged)
        r = self.client.post(url)
        self.event.refresh_from_db()
        self.assertFalse(self.event.dobro_ru_hours_logged)

    def test_toggle_rejects_no_tracking_event(self):
        event = f.make_event(event_status='finished', dobro_ru_link_kind='none')
        r = self.client.post(reverse('report_dobro_toggle', args=[event.id]))
        self.assertEqual(r.status_code, 400)

    def test_set_link_valid_url(self):
        event = f.make_event(dobro_ru_link_kind='none')
        r = self.client.post(reverse('report_dobro_set_link', args=[event.id]), {'url': 'https://dobro.ru/e/2'})
        self.assertEqual(r.status_code, 200)
        event.refresh_from_db()
        self.assertEqual(event.dobro_ru_link, 'https://dobro.ru/e/2')
        self.assertEqual(event.dobro_ru_link_kind, 'unique')

    def test_set_link_invalid_url_rejected(self):
        event = f.make_event(dobro_ru_link_kind='none')
        r = self.client.post(reverse('report_dobro_set_link', args=[event.id]), {'url': 'not-a-url'})
        self.assertEqual(r.status_code, 400)
        event.refresh_from_db()
        self.assertEqual(event.dobro_ru_link_kind, 'none')

    def test_set_link_empty_clears(self):
        r = self.client.post(reverse('report_dobro_set_link', args=[self.event.id]), {'url': ''})
        self.assertEqual(r.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.dobro_ru_link_kind, 'none')
