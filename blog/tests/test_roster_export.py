"""Excel до начала смен: все заявки, уникальные люди, позиции и время по дням."""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import BytesIO
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook
from blog.models import Application, EventGroup
from . import factories as f


class RosterExportTests(TestCase):
    def setUp(self):
        self.manager = f.make_manager()
        self.group = EventGroup.objects.create(title='Марафон')
        self.events = [f.make_event(title=title, event_group=self.group) for title in ('Выдача', 'Финиш')]
        start = datetime(2026, 11, 4, 6, tzinfo=dt_timezone.utc)
        self.shifts = [f.make_shift(self.events[0], start_time=start, end_time=start + timedelta(hours=3)),
                       f.make_shift(self.events[1], start_time=start + timedelta(hours=4), end_time=start + timedelta(hours=7)),
                       f.make_shift(self.events[0], start_time=start + timedelta(days=1), end_time=start + timedelta(days=1, hours=3))]
        self.user = f.make_user(first_name='Анна', last_name='А', birthday=date(2000, 11, 4),
                                email='a@example.org', VK_username='anna', instagram_url='https://instagram.com/anna',
                                preferred_contact_methods=['telegram', 'email'], tshirt_size='XL')
        f.make_application(self.events[0], self.user, status='new', shifts=[self.shifts[0], self.shifts[2]])
        f.make_application(self.events[1], self.user, status='rejected', shifts=[self.shifts[1]])
        f.make_participation(self.user, self.shifts[0], status='pending', hours=0)
        self.other = f.make_user(first_name='Борис', last_name='Б', birthday=None)
        f.make_application(self.events[1], self.other, status='new', shifts=[self.shifts[1]])
        outsider = f.make_event(title='Вне охвата')
        f.make_application(outsider, f.make_user(first_name='Чужой'), shifts=[f.make_shift(outsider)])
        self.client.force_login(self.manager)

    def workbook(self, route, pk):
        response = self.client.get(reverse(route, args=[pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        return load_workbook(BytesIO(response.content))

    def test_group_all_applicants_unique_people_daily_columns_and_stats(self):
        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 3)):
            wb = self.workbook('event_group_roster_export', self.group.pk)
        ws = wb['Участники']
        self.assertEqual(ws.max_row, 3)
        self.assertEqual(ws.max_column, 14)
        anna = list(ws.values)[1]
        self.assertEqual((anna[0], anna[1], anna[2], anna[10], anna[11]), ('Анна', 'А', 25, 'XL', 3))
        self.assertEqual(anna[3].date(), self.user.birthday)
        self.assertEqual(anna[7], 'https://vk.com/anna')
        self.assertIn('Телеграм', anna[9])
        self.assertIn('Выдача', anna[12])
        self.assertIn('Финиш', anna[12])
        self.assertIn('09:00', anna[12])
        self.assertIn('резерв', anna[12].lower())
        self.assertIn('новая', list(ws.values)[2][12].lower())
        self.assertIsNone(list(ws.values)[2][13])
        self.assertIsNone(list(ws.values)[2][2])
        self.assertIn('4 ноября 2026', ws.cell(1, 13).value)
        self.assertEqual(wb['Сводка'].cell(2, 2).value, 2)
        self.assertEqual(wb['Сводка'].cell(2, 4).value, 4)
        self.assertEqual(len(list(wb['Сводка'].values)), 4)

    def test_position_limits_scope_and_counts_own_shifts(self):
        wb = self.workbook('position_roster_export', self.events[0].pk)
        rows = list(wb['Участники'].values)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][11], 2)
        self.assertNotIn('Финиш', str(rows))
        self.assertNotIn('Борис', str(rows))

    def test_unlinked_cancelled_and_legacy_application_and_formula_text(self):
        Application.objects.create(event=self.events[0], user=None, first_name='=1+1', last_name='Без профиля',
                                   telegram_username='unlinked', phone='+7000123', status='cancelled')
        wb = self.workbook('position_roster_export', self.events[0].pk)
        ws = wb['Участники']
        row = next(row for row in ws.iter_rows(min_row=2) if row[0].value == '=1+1')
        self.assertEqual(row[0].data_type, 's')
        self.assertEqual(row[2].value, None)
        self.assertEqual(row[5].value, '+7000123')
        self.assertEqual(row[11].value, 2)
        self.assertIn('отмен', row[12].value.lower())

    def test_export_permissions_and_buttons(self):
        self.assertContains(self.client.get(reverse('event_group_detail', args=[self.group.pk])), reverse('event_group_roster_export', args=[self.group.pk]))
        self.assertContains(self.client.get(reverse('event_detail', args=[self.events[0].pk])), reverse('position_roster_export', args=[self.events[0].pk]))
        leader = f.make_team_leader()
        self.client.force_login(leader)
        self.assertEqual(self.client.get(reverse('position_roster_export', args=[self.events[0].pk])).status_code, 403)
        f.assign_team_leader(self.events[0], leader)
        self.assertEqual(self.client.get(reverse('position_roster_export', args=[self.events[0].pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('event_group_roster_export', args=[self.group.pk])).status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('position_roster_export', args=[self.events[0].pk])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('event_group_roster_export', args=[self.group.pk])).status_code, 302)

    def test_empty_scope_has_headers_and_zero_summary(self):
        empty = EventGroup.objects.create(title='Пустое')
        wb = self.workbook('event_group_roster_export', empty.pk)
        self.assertEqual(wb['Участники'].max_row, 1)
        self.assertEqual(wb['Участники'].max_column, 12)
        self.assertEqual(wb['Сводка'].cell(2, 2).value, 0)

    def test_application_without_shifts_is_counted_in_position_summary(self):
        event = f.make_event(title='Ещё без смен', event_group=self.group)
        f.make_application(event, self.other)
        wb = self.workbook('event_group_roster_export', self.group.pk)
        row = next(row for row in wb['Сводка'].values if row[0] == event.title)
        self.assertEqual((row[1], row[2], row[3]), (1, 0, 0))

    def test_utc_midnight_uses_moscow_day_and_export_is_read_only(self):
        app = Application.objects.create(event=self.events[0], user=None, first_name='Legacy', status='new')
        self.shifts[0].start_time = datetime(2026, 11, 3, 22, 30, tzinfo=dt_timezone.utc)
        self.shifts[0].end_time = datetime(2026, 11, 4, 1, 30, tzinfo=dt_timezone.utc)
        self.shifts[0].save(update_fields=['start_time', 'end_time'])
        wb = self.workbook('position_roster_export', self.events[0].pk)
        self.assertIn('4 ноября 2026', wb['Участники'].cell(1, 13).value)
        self.assertIn('01:30', wb['Участники'].cell(2, 13).value)
        self.assertEqual(app.shift_decisions.count(), 0)

    def test_vk_links_accept_nickname_and_address_without_protocol(self):
        for value in ('@anna', 'vk.com/anna', 'www.vk.com/anna', 'https://vk.com/anna'):
            self.user.VK_username = value
            self.user.save(update_fields=['VK_username'])
            wb = self.workbook('position_roster_export', self.events[0].pk)
            self.assertEqual(wb['Участники'].cell(2, 8).value, 'https://vk.com/anna')
