"""Поэтапная миграция старых баз: база → люди → мероприятие → ФиП → сопоставление → загрузка.

Решения пользователя (2026-11-11), которые здесь застрахованы:
- позиция = набор тим-лидера ФиП; значение ячейки «7.2 - …» сопоставляется человеком
  (с подсказкой), а не превращается в позицию «7.2»;
- тим-лидер из базы получает EventStaff на позиции и глобальную роль;
- часы — из смены ФиП, ручные правки сотрудников не перезаписываются;
- колонка без явной даты не загружается, пока дату не укажет человек;
- баз несколько (одна база = год), люди в них пересекаются и не дублируются;
- расхождение с анкетой, которую человек заполнил сам, уходит ему на уточнение.
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from blog.models import (
    EventShift, EventStaff, FapDocument, LegacyBase, Participation, ProfileConflict, TeamLeader, User, UserComment,
)
from blog.services import legacy_migration as lm
from . import factories as f

FAP = Path(__file__).resolve().parents[1] / 'resources' / 'fap' / 'marathon-2026-mentors.xlsx'
PROFILE = ['Комментарий координатора', 'Комментарий тим-лидера', 'Имя', 'Фамилия', 'Дата рождения',
           'Электронная почта', 'Мобильный телефон', 'Ник в Telegram', 'Размер футболки']
EVENTS = ['ММ\n24 сентября\nВыдача', 'ММ\n27 сентября\nДень марафона', 'ММ\n(резерв)',
          'БФБ\n23 августа \nвс - 1 смена', 'БФБ\n23 августа \nвс - 2 смена']
ANNA = ['Координатор об Анне', '', 'Анна', 'Иванова', datetime(2000, 6, 1), 'anna@example.org', '89991112233', '@anna', 'M',
        '7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км',
        '10.4 - Волонтёр пункта питания на дистанции (ПП2)', None, 'Ассистент выдачи номеров', 'Волонтёр выдачи медалей']
BORIS = ['', 'Лидер о Борисе', 'Борис', 'Петров', None, '', '89992223344', '@boris', 'L',
         '7.2 - Тим-лидер волонтёров зоны выдачи номеров и пакетов участника',
         '10.1 - Тим-лидер волонтёров пункта освежения (ПО1)', '11 - Помощник тим-лидера организации сервисов',
         None, None]


def base_xlsx(*rows, headers=None):
    wb = Workbook()
    wb.active.title = 'База'
    wb.active.append(headers or PROFILE + EVENTS)
    for row in rows:
        wb.active.append(row)
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


class MigrationTestCase(TestCase):
    def setUp(self):
        self.manager = f.make_manager()

    def upload(self, *rows, year=2026, name='база.xlsx', headers=None):
        return lm.upload_base(self.manager, base_xlsx(*(rows or (ANNA, BORIS)), headers=headers), name, year)

    def marathon(self, base):
        columns = list(base.columns.filter(header__startswith='ММ').order_by('index'))
        group = lm.create_event_from_columns(self.manager, base, [c.pk for c in columns], 'Московский марафон 2026')
        return group, list(base.columns.filter(event_group=group).order_by('index'))

    def map_all(self, group, overrides=None):
        """Принять подсказки; несопоставленное — по overrides, иначе пропустить."""
        overrides = overrides or {}
        items = []
        for row in lm.mapping_table(group):
            suggestion = row['suggestion']
            target = overrides.get(row['raw'], str(suggestion['position'].pk) if suggestion['position'] else 'skip')
            items.append({'key': row['key'], 'raw': row['raw'], 'target': target,
                          'role': suggestion['role'], 'title': row['new_title']})
        lm.save_mappings(self.manager, group, items)


class BaseAndPeopleTests(MigrationTestCase):
    def test_upload_keeps_file_columns_unique_values_and_explicit_dates_only(self):
        base = self.upload(year=2025)
        self.assertEqual(base.year, 2025)
        columns = {c.header: c for c in base.columns.all()}
        self.assertEqual(columns['ММ\n24 сентября\nВыдача'].day, date(2025, 9, 24))
        self.assertIsNone(columns['ММ\n(резерв)'].day)
        self.assertEqual(columns['ММ\n24 сентября\nВыдача'].value_counts, {
            '7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км': 1,
            '7.2 - Тим-лидер волонтёров зоны выдачи номеров и пакетов участника': 1})
        self.assertFalse(User.objects.filter(first_name='Анна').exists())
        with self.assertRaisesMessage(ValidationError, 'уже загружена'):
            self.upload(year=2025)

    def test_only_manager_uploads(self):
        with self.assertRaises(PermissionDenied):
            lm.upload_base(f.make_team_leader(), base_xlsx(ANNA), 'x.xlsx', 2026)

    def test_people_stage_creates_profiles_comments_and_is_idempotent(self):
        base = self.upload()
        result = lm.load_people(self.manager, base)
        self.assertEqual(result['created'], 2)
        anna = User.objects.get(telegram_username='anna')
        self.assertEqual((anna.phone, anna.tshirt_size, anna.birthday), ('+79991112233', 'M', date(2000, 6, 1)))
        self.assertTrue(anna.telegram_id.startswith('legacy:'))
        self.assertTrue(UserComment.objects.filter(target_user=anna, source='legacy_coordinator').exists())
        lm.load_people(self.manager, base)
        self.assertEqual(User.objects.filter(telegram_username='anna').count(), 1)

    def test_second_year_base_reuses_person_and_newer_data_wins_for_base_only_profiles(self):
        old = self.upload(year=2025)
        lm.load_people(self.manager, old)
        anna_2026 = ANNA.copy()
        anna_2026[5], anna_2026[8] = 'anna.new@example.org', 'S'
        new = self.upload(anna_2026, year=2026, name='2026.xlsx')
        lm.load_people(self.manager, new)
        anna = User.objects.get(telegram_username='anna')
        self.assertEqual(User.objects.filter(telegram_username='anna').count(), 1)
        self.assertEqual((anna.email, anna.tshirt_size), ('anna.new@example.org', 'S'))
        note = UserComment.objects.get(target_user=anna, source='legacy_changes').text
        self.assertIn('anna@example.org', note)
        self.assertIn('anna.new@example.org', note)
        # Более старая база после новой не откатывает актуальные данные.
        older = ANNA.copy()
        older[5] = 'anna.2024@example.org'
        lm.load_people(self.manager, self.upload(older, year=2024, name='2024.xlsx'))
        anna.refresh_from_db()
        self.assertEqual(anna.email, 'anna.new@example.org')

    def test_self_filled_profile_is_not_overwritten_and_asks_the_person(self):
        person = f.make_user(telegram_id='555', telegram_username='anna', first_name='Аня', phone='+79991112233', email='')
        lm.load_people(self.manager, self.upload(ANNA))
        person.refresh_from_db()
        self.assertEqual(person.first_name, 'Аня')
        self.assertEqual(person.email, 'anna@example.org')  # пустое поле просто дополнено
        conflict = ProfileConflict.objects.get(user=person, field='first_name')
        self.assertEqual((conflict.current_value, conflict.proposed_value), ('Аня', 'Анна'))
        self.assertIn('Аня', UserComment.objects.get(target_user=person, source='legacy_changes').text)


class FapAndMappingTests(MigrationTestCase):
    def setUp(self):
        super().setUp()
        self.base = self.upload()
        lm.load_people(self.manager, self.base)
        self.group, self.columns = self.marathon(self.base)
        self.document = lm.attach_fap(self.manager, self.group, FAP.read_bytes(), FAP.name)

    def test_fap_versions_are_kept_and_positions_get_functions_from_pool(self):
        self.assertEqual(self.document.version, 1)
        self.assertIsNotNone(self.document.applied_at)
        again = lm.attach_fap(self.manager, self.group, FAP.read_bytes(), FAP.name)
        self.assertEqual((again.version, FapDocument.objects.filter(event_group=self.group).count()), (2, 2))
        distance = self.group.positions.get(title='Волонтёры дистанции — Пункт освежения (ПО1)')
        self.assertEqual(list(distance.category_map.values_list('category__name', flat=True)), ['Дистанция'])

    def test_suggestions_use_code_and_text_and_detect_team_leads(self):
        rows = {row['raw']: row for row in lm.mapping_table(self.group)}
        volunteer = rows['7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км']['suggestion']
        self.assertEqual(volunteer['position'].title, 'Организация выдачи пакетов участников — Зона выдачи номеров и пакетов участника')
        self.assertEqual(volunteer['role'], 'volunteer')
        lead = rows['7.2 - Тим-лидер волонтёров зоны выдачи номеров и пакетов участника']['suggestion']
        self.assertEqual((lead['position'], lead['role']), (volunteer['position'], 'team_lead'))
        self.assertEqual(rows['10.4 - Волонтёр пункта питания на дистанции (ПП2)']['suggestion']['position'].title,
                         'Волонтёры дистанции — Пункт питания на дистанции (ПП2)')
        self.assertEqual(rows['11 - Помощник тим-лидера организации сервисов']['suggestion']['role'], 'volunteer')
        self.assertEqual(rows['7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км']['counts'][0][1], 1)

    def test_column_needs_mapping_and_explicit_date_before_load(self):
        first, _, reserve = self.columns
        self.assertEqual(lm.column_state(first)['code'], 'unmapped')
        with self.assertRaises(ValidationError):
            lm.load_columns(self.manager, [first])
        self.map_all(self.group)
        self.assertEqual(lm.column_state(first)['code'], 'ready')
        self.assertEqual(lm.column_state(reserve)['code'], 'no_date')
        lm.set_column(self.manager, reserve, day=date(2026, 9, 26))
        self.assertEqual(lm.column_state(reserve)['code'], 'ready')

    def test_load_creates_participation_with_fap_hours_and_team_lead_role(self):
        self.map_all(self.group)
        first, marathon_day, _ = self.columns
        result = lm.load_columns(self.manager, [first, marathon_day])
        anna, boris = User.objects.get(first_name='Анна'), User.objects.get(first_name='Борис')
        part = Participation.objects.get(user=anna, event_day__day=date(2026, 9, 24))
        self.assertEqual((part.status, part.hours), ('attended', Decimal('6.08')))
        position = part.event_day.event
        self.assertTrue(EventStaff.objects.filter(event=position, user=boris, staff_role='team_lead').exists())
        self.assertTrue(TeamLeader.objects.filter(user=boris, revoked_at__isnull=True).exists())
        self.assertTrue(Participation.objects.filter(user=boris, event_day__event=position).exists())
        anna.refresh_from_db()
        self.assertEqual(anna.total_hours, Decimal('6.08') + Decimal('5.83'))
        self.assertEqual(result['participations'], 4)
        lm.load_columns(self.manager, [first, marathon_day])
        self.assertEqual(Participation.objects.filter(user__in=[anna, boris]).count(), 4)
        first.refresh_from_db()
        self.assertEqual(lm.column_state(first)["code"], "loaded")

    def test_remapping_moves_untouched_participation_but_keeps_manual_hours(self):
        self.map_all(self.group)
        first, marathon_day, _ = self.columns
        lm.load_columns(self.manager, [first, marathon_day])
        anna = User.objects.get(first_name='Анна')
        edited = Participation.objects.get(user=anna, event_day__day=date(2026, 9, 27))
        edited.hours, edited.hours_overridden = Decimal('3'), True
        edited.save()
        other = self.group.positions.get(title__endswith='Зона проверки справок')
        po1 = self.group.positions.get(title__endswith='Пункт освежения (ПО1)')
        self.map_all(self.group, {'7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км': str(other.pk),
                                  '10.4 - Волонтёр пункта питания на дистанции (ПП2)': str(po1.pk)})
        first.refresh_from_db()
        self.assertEqual(lm.column_state(first)["code"], "changed")
        result = lm.load_columns(self.manager, [first, marathon_day])
        self.assertEqual(Participation.objects.get(user=anna, event_day__day=date(2026, 9, 24)).event_day.event, other)
        edited.refresh_from_db()
        self.assertEqual((edited.hours, edited.event_day.event.title.endswith('(ПП2)')), (Decimal('3'), True))
        self.assertEqual(len(result['conflicts']), 1)

    def test_unload_column_removes_only_what_it_created(self):
        self.map_all(self.group)
        first = self.columns[0]
        lm.load_columns(self.manager, [first])
        lm.unload_column(self.manager, first)
        first.refresh_from_db()
        self.assertFalse(Participation.objects.exists())
        self.assertFalse(EventStaff.objects.filter(staff_role='team_lead', user__first_name='Борис').exists())
        self.assertEqual(lm.column_state(first)['code'], 'ready')


class WithoutFapTests(MigrationTestCase):
    def test_new_positions_from_values_and_two_shifts_same_day(self):
        base = self.upload()
        lm.load_people(self.manager, base)
        columns = list(base.columns.filter(header__startswith='БФБ').order_by('index'))
        group = lm.create_event_from_columns(self.manager, base, [c.pk for c in columns], 'БФБ 2026')
        self.assertEqual(group.title, 'БФБ 2026')
        rows = {row['raw']: row for row in lm.mapping_table(group)}
        self.assertIsNone(rows['Ассистент выдачи номеров']['suggestion']['position'])
        self.map_all(group, {'Ассистент выдачи номеров': 'new', 'Волонтёр выдачи медалей': 'new'})
        position = group.positions.get(title='Ассистент выдачи номеров')
        self.assertEqual(list(position.category_map.values_list('category__name', flat=True)), ['Выдача стартовых пакетов'])
        lm.load_columns(self.manager, columns)
        shifts = EventShift.objects.filter(event__event_group=group, day=date(2026, 8, 23))
        self.assertEqual(shifts.count(), 2)
        self.assertTrue(all(s.time_unknown for s in shifts))
        self.assertEqual(set(Participation.objects.filter(event_day__in=shifts).values_list('hours', flat=True)), {Decimal('0')})


class MigrationViewsTests(MigrationTestCase):
    def test_hub_lists_unloaded_columns_with_reason_and_is_manager_only(self):
        base = self.upload()
        self.marathon(base)
        self.client.force_login(self.manager)
        response = self.client.get(reverse('legacy_migration'))
        self.assertContains(response, 'Московский марафон 2026')
        self.assertContains(response, 'не сопоставлены значения')
        self.assertContains(response, 'База 2026')
        detail = self.client.get(reverse('legacy_migration_base', args=[base.pk]))
        self.assertContains(detail, 'БФБ')
        self.client.force_login(f.make_team_leader())
        self.assertEqual(self.client.get(reverse('legacy_migration')).status_code, 403)

    def test_settings_points_to_migration(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('settings'))
        self.assertContains(response, reverse('legacy_migration'))
        self.assertContains(response, 'Миграция старой базы')

    def test_full_flow_through_pages(self):
        self.client.force_login(self.manager)
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(reverse('legacy_migration'), {
            'action': 'upload_base', 'year': 2026, 'workbook': SimpleUploadedFile('база.xlsx', base_xlsx(ANNA, BORIS))})
        base = LegacyBase.objects.get()
        self.assertRedirects(response, reverse('legacy_migration_base', args=[base.pk]))
        self.client.post(reverse('legacy_migration_base', args=[base.pk]), {'action': 'load_people'})
        self.assertEqual(User.objects.filter(first_name__in=['Анна', 'Борис']).count(), 2)
        columns = base.columns.filter(header__startswith='ММ')
        response = self.client.post(reverse('legacy_migration_base', args=[base.pk]), {
            'action': 'create_event', 'title': 'ММ 2026', 'columns': [c.pk for c in columns]})
        group = base.columns.get(header__startswith='ММ\n24').event_group
        self.assertRedirects(response, reverse('legacy_migration_group', args=[group.pk]))
        self.client.post(reverse('legacy_migration_group', args=[group.pk]), {
            'action': 'attach_fap', 'workbook': SimpleUploadedFile(FAP.name, FAP.read_bytes())})
        self.assertEqual(FapDocument.objects.filter(event_group=group).count(), 1)
        page = self.client.get(reverse('legacy_migration_group', args=[group.pk]))
        self.assertContains(page, '7.2 - Тим-лидер волонтёров зоны выдачи номеров')
        data = {'action': 'save_mappings'}
        for i, row in enumerate(page.context['rows']):
            data[f'key_{i}'] = row['key']
            data[f'raw_{i}'] = row['raw']
            data[f'target_{i}'] = row['selected']
            data[f'role_{i}'] = row['selected_role']
            data[f'title_{i}'] = row['new_title']
        self.client.post(reverse('legacy_migration_group', args=[group.pk]), data)
        first = base.columns.get(header__startswith='ММ\n24')
        self.client.post(reverse('legacy_migration_group', args=[group.pk]), {'action': 'load', 'columns': [first.pk]})
        self.assertEqual(Participation.objects.filter(event_day__day=date(2026, 9, 24)).count(), 2)


class ProfileConflictFlowTests(TestCase):
    def test_person_sees_banner_and_chooses_actual_values(self):
        manager = f.make_manager()
        person = f.make_user(telegram_id='777', telegram_username='anna', first_name='Аня', phone='+79991112233')
        lm.load_people(manager, lm.upload_base(manager, base_xlsx(ANNA), 'b.xlsx', 2026))
        conflict = ProfileConflict.objects.get(user=person, field='first_name')
        self.client.force_login(person)
        self.assertContains(self.client.get(reverse('dashboard')), reverse('profile_actualize'))
        page = self.client.get(reverse('profile_actualize'))
        self.assertContains(page, 'Анна')
        others = ProfileConflict.objects.filter(user=person).exclude(pk=conflict.pk)
        choices = {f'choice_{conflict.pk}': 'proposed', **{f'choice_{c.pk}': 'current' for c in others}}
        self.client.post(reverse('profile_actualize'), choices)
        person.refresh_from_db()
        conflict.refresh_from_db()
        self.assertEqual(person.first_name, 'Анна')
        self.assertIsNotNone(conflict.resolved_at)
        self.assertFalse(ProfileConflict.objects.filter(user=person, resolved_at__isnull=True).exists())
        self.assertNotContains(self.client.get(reverse('dashboard')), reverse('profile_actualize'))

    def test_custom_value_is_validated(self):
        manager = f.make_manager()
        person = f.make_user(telegram_id='778', telegram_username='anna', email='old@example.org', phone='+79991112233')
        lm.load_people(manager, lm.upload_base(manager, base_xlsx(ANNA), 'b.xlsx', 2026))
        conflict = ProfileConflict.objects.get(user=person, field='email')
        self.client.force_login(person)
        response = self.client.post(reverse('profile_actualize'), {f'choice_{conflict.pk}': 'custom', f'custom_{conflict.pk}': 'не почта'})
        self.assertContains(response, 'почт')
        conflict.refresh_from_db()
        self.assertIsNone(conflict.resolved_at)
