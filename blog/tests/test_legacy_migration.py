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
from unittest.mock import patch

from django.test import TestCase, override_settings
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
        # Тот же файл (байт в байт): openpyxl пишет время создания, поэтому
        # повторно генерировать книгу нельзя — хеш мог бы отличаться.
        with self.assertRaisesMessage(ValidationError, 'уже загружена'):
            lm.upload_base(self.manager, bytes(base.content), 'копия.xlsx', 2025)

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
        again = lm.attach_fap(self.manager, self.group, FAP.read_bytes(), 'другое имя.xlsx')
        self.assertEqual((again.pk, FapDocument.objects.filter(event_group=self.group).count()), (self.document.pk, 1))
        distance = self.group.positions.get(title='Волонтер пункта освежения (ПО1)')
        self.assertEqual(list(distance.category_map.filter(category__kind='function').values_list('category__name', flat=True)), ['Волонтёры дистанции'])

    def test_suggestions_use_code_and_text_and_detect_team_leads(self):
        rows = {row['raw']: row for row in lm.mapping_table(self.group)}
        volunteer = rows['7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км']['suggestion']
        self.assertEqual(volunteer['position'].title, 'Ассистент выдачи номеров и пакетов участника — 42,2 км')
        self.assertEqual(volunteer['role'], 'volunteer')
        self.assertEqual(volunteer['function'].name, 'Организация выдачи пакетов участников')
        lead = rows['7.2 - Тим-лидер волонтёров зоны выдачи номеров и пакетов участника']['suggestion']
        self.assertEqual((lead['position'].title, lead['role']), ('Тим-лидер волонтёров зоны выдачи номеров и пакетов участника', 'team_lead'))
        self.assertEqual(rows['10.4 - Волонтёр пункта питания на дистанции (ПП2)']['suggestion']['position'].title,
                         'Волонтёр пункта питания на дистанции (ПП2)')
        self.assertEqual(rows['11 - Помощник тим-лидера организации сервисов']['suggestion']['role'], 'volunteer')
        self.assertEqual(rows['7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км']['counts'][0][1], 1)

    def test_exact_code_beats_similar_text_and_codeless_values_need_close_text(self):
        """Реальная база ММ: «10.10 … (ПО6)» в базе подписано как «пункт питания», но код
        10.10 однозначно указывает на ПО6. «Разбор медалей» в ФиП нет — подсказки нет."""
        hints = lm._position_hints(self.group)
        self.assertTrue(lm.suggest('10.10 - Волонтёр пункта питания на дистанции (ПО6)', hints)['position'].title.endswith('(ПО6)'))
        self.assertIsNone(lm.suggest('Волонтёр разбора медалей', hints)['position'])
        self.assertIsNone(lm.suggest('Тим-лидер разбора медалей', hints)['position'])

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
        self.assertEqual((part.status, part.hours), ('attended', Decimal('5.83')))
        position = part.event_day.event
        self.assertTrue(EventStaff.objects.filter(event=position, user=boris, staff_role='team_lead').exists())
        self.assertTrue(TeamLeader.objects.filter(user=boris, revoked_at__isnull=True).exists())
        # Тим-лидер видит весь набор функции: назначен и на позицию ассистентов (выше).
        self.assertTrue(Participation.objects.filter(user=boris, event_day__day=date(2026, 9, 24)).exists())
        anna.refresh_from_db()
        self.assertEqual(anna.total_hours, Decimal('5.83') + Decimal('5.83'))
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
        other = self.group.positions.get(title='Ассистент проверки медицинских справок')
        po1 = self.group.positions.get(title='Волонтер пункта освежения (ПО1)')
        self.map_all(self.group, {'7.2 - Ассистент выдачи номеров и пакетов участника — 42,2 км': str(other.pk),
                                  '10.4 - Волонтёр пункта питания на дистанции (ПП2)': str(po1.pk)})
        first.refresh_from_db()
        self.assertEqual(lm.column_state(first)["code"], "changed")
        result = lm.load_columns(self.manager, [first, marathon_day])
        self.assertEqual(Participation.objects.get(user=anna, event_day__day=date(2026, 9, 24)).event_day.event, other)
        edited.refresh_from_db()
        self.assertEqual((edited.hours, edited.event_day.event.title.endswith('(ПП2)')), (Decimal('3'), True))
        self.assertEqual(len(result['conflicts']), 1)

    def test_overlapping_shifts_of_one_person_are_warned_but_allowed(self):
        """Решение 2026-11-11: человек может быть в нескольких позициях, даже если они
        пересекаются по времени — БД это допускает, менеджер видит предупреждение."""
        self.map_all(self.group)
        first = self.columns[0]
        lm.load_columns(self.manager, [first])
        boris = User.objects.get(first_name='Борис')
        other = self.group.positions.get(title='Ассистент проверки медицинских справок').shifts.get(day=date(2026, 9, 24))
        Participation.objects.create(user=boris, event_day=other, status='attended')
        warnings = lm.overlaps(self.group)
        self.assertEqual([w['user'] for w in warnings], [boris])
        self.assertEqual(len(warnings[0]['shifts']), 2)

    def test_new_fap_version_accepted_after_columns_created_unknown_time_shifts(self):
        """Реальный случай пользователя (МПМ, 2026-11-11): колонка «резерв» с датой вне
        ФиП создала смену «без времени» в позиции ФиП — новая версия ФиП не должна
        отклоняться как «конфликт»: такие смены — архивная явка, а не правка плана."""
        from copy import deepcopy
        from blog.services import event_sheets
        self.map_all(self.group)
        reserve = self.columns[2]
        lm.set_column(self.manager, reserve, day=date(2026, 9, 20))
        lm.load_columns(self.manager, [reserve])
        self.assertTrue(EventShift.objects.filter(event__event_group=self.group, legacy_source__isnull=False).exists())
        plan = deepcopy(lm.document_plan(self.document))
        plan['directions'][0]['positions'][0]['days'][2]['shifts'][0]['count'] += 1
        event_sheets.import_plan(self.manager, self.group, lm._carry_ids_by_name(self.group, plan), FAP.read_bytes() + b'v2', 'v2.xlsx')
        self.assertTrue(Participation.objects.filter(event_day__day=date(2026, 9, 20)).exists())

    def test_fap_uploaded_before_library_gets_plan_parsed_from_file(self):
        FapDocument.objects.filter(pk=self.document.pk).update(plan={}, title='')
        self.document.refresh_from_db()
        choices = lm.fap_choices()
        self.assertEqual([d['day'] for d in choices[0]['days']][:1], [date(2026, 9, 24)])
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, 'marathon-2026-mentors')

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
        self.assertEqual(list(position.category_map.filter(category__kind='function').values_list('category__name', flat=True)), ['Организация выдачи пакетов участников'])
        lm.load_columns(self.manager, columns)
        shifts = EventShift.objects.filter(event__event_group=group, day=date(2026, 8, 23))
        self.assertEqual(shifts.count(), 2)
        self.assertTrue(all(s.time_unknown for s in shifts))
        self.assertEqual(set(Participation.objects.filter(event_day__in=shifts).values_list('hours', flat=True)), {Decimal('0')})


@override_settings(MIGRATION_JOBS_INLINE=True)
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


FAP_DIR = FAP.parent


@override_settings(MIGRATION_JOBS_INLINE=True)
class BackgroundJobTests(MigrationTestCase):
    """Загрузка людей и колонок идёт фоновой задачей с процентом и отменой
    (запрос пользователя 2026-11-11): можно уходить на другие страницы."""

    def test_people_job_reports_progress_and_status_endpoint(self):
        from blog.models import MigrationJob
        from blog.services import migration_jobs
        base = self.upload()
        job = migration_jobs.start_people(self.manager, base)
        job.refresh_from_db()
        self.assertEqual((job.status, job.done, job.total), ('done', 2, 2))
        self.assertEqual(User.objects.filter(first_name__in=['Анна', 'Борис']).count(), 2)
        self.client.force_login(self.manager)
        data = self.client.get(reverse('legacy_migration_job', args=[job.pk])).json()
        self.assertEqual((data['status'], data['percent']), ('done', 100))
        self.assertIn('Новых людей: 2', data['message'])
        self.assertEqual(MigrationJob.objects.count(), 1)

    def test_cancelled_people_job_removes_what_it_created(self):
        from blog.services import migration_jobs
        existing = f.make_user(telegram_id='901', telegram_username='boris', first_name='Боря', phone='+79992223344')
        base = self.upload()
        checks = iter([False, True, True])
        with patch.object(migration_jobs, 'PEOPLE_CHUNK', 1), \
                patch.object(migration_jobs, '_cancelled', lambda job: next(checks)):
            job = migration_jobs.start_people(self.manager, base)
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
        self.assertFalse(User.objects.filter(first_name='Анна').exists())
        self.assertTrue(User.objects.filter(pk=existing.pk).exists())
        self.assertFalse(base.people.exists())
        base.refresh_from_db()
        self.assertIsNone(base.people_loaded_at)

    def test_cancel_view_asks_running_job_to_stop_and_second_job_waits(self):
        from blog.services import migration_jobs
        base = self.upload()
        job = migration_jobs.dc.create_migration_job(kind='people', operator=self.manager, base=base, total=2)
        with self.assertRaisesMessage(ValidationError, 'Уже идёт загрузка'):
            migration_jobs.start_people(self.manager, base)
        self.client.force_login(self.manager)
        page = self.client.get(reverse('legacy_migration'))
        self.assertContains(page, 'Да, отменить')
        self.assertContains(page, 'Идёт загрузка')
        self.client.post(reverse('legacy_migration_job', args=[job.pk]), {'action': 'cancel', 'next': reverse('legacy_migration')})
        job.refresh_from_db()
        self.assertTrue(job.cancel_requested)
        self.client.force_login(f.make_team_leader())
        self.assertEqual(self.client.get(reverse('legacy_migration_job', args=[job.pk])).status_code, 403)

    def test_cancelled_columns_job_unloads_its_columns(self):
        from blog.services import migration_jobs
        base = self.upload()
        lm.load_people(self.manager, base)
        group, columns = self.marathon(base)
        lm.attach_fap(self.manager, group, FAP.read_bytes(), FAP.name)
        self.map_all(group)
        checks = iter([False, True, True])
        with patch.object(migration_jobs, 'COLUMN_CHUNK', 1), \
                patch.object(migration_jobs, '_cancelled', lambda job: next(checks, True)):
            job = migration_jobs.start_columns(self.manager, group, columns[:2])
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
        self.assertFalse(Participation.objects.exists())


class FapLibraryTests(MigrationTestCase):
    """Несколько ФиП за раз в библиотеку; колонки базы сопоставляются с файлом и днём."""

    def test_several_files_upload_each_checked_separately(self):
        files = [(name, (FAP_DIR / name).read_bytes()) for name in
                 ('marathon-2026-mentors.xlsx', 'night-2026-split-day.xlsx', 'april-2026-labels.xlsx')]
        files.append(('сломанный.xlsx', b'not a workbook'))
        results = lm.upload_fap_files(self.manager, files, default_year=2026)
        ok = [doc for _, doc, error in results if doc and not error]
        self.assertEqual(len(ok), 3)
        self.assertTrue(results[-1][2])
        self.assertTrue(all(doc.event_group is None for doc in ok))
        again = lm.upload_fap_files(self.manager, files[:1])
        self.assertIn('уже загружен', again[0][2])

    def test_columns_mapped_to_fap_day_create_event_once_and_take_fap_dates(self):
        base = self.upload()
        [(_, document, _)] = lm.upload_fap_files(self.manager, [('Московский марафон 2026 - Функции и позиции.xlsx', FAP.read_bytes())])
        self.assertEqual(document.title, 'Московский марафон 2026')
        columns = list(base.columns.filter(header__startswith='ММ').order_by('index'))
        overview = {item['column'].pk: item for item in lm.base_overview(base)['columns']}
        self.assertEqual(overview[columns[0].pk]['fap_selected'], f'{document.pk}|2026-09-24')
        self.assertTrue(overview[columns[0].pk]['fap_suggested'])
        lm.map_columns_to_fap(self.manager, base, {columns[0].pk: f'{document.pk}|2026-09-24',
                                                   columns[2].pk: f'{document.pk}|2026-09-26'})
        document.refresh_from_db()
        reserve = base.columns.get(pk=columns[2].pk)
        self.assertEqual(reserve.day, date(2026, 9, 26))
        self.assertEqual(reserve.event_group.title, 'Московский марафон 2026')
        self.assertEqual((document.event_group, document.version), (reserve.event_group, 1))
        self.assertEqual(reserve.event_group.positions.count(), 106)
        self.assertTrue(lm.dc.position_templates_qs().filter(name='Волонтер пункта освежения (ПО1)').exists())

    def test_state_hint_names_unmapped_values(self):
        base = self.upload()
        group, columns = self.marathon(base)
        state = lm.column_state(columns[0])
        self.assertEqual(state['code'], 'unmapped')
        self.assertIn('7.2 - Ассистент выдачи номеров', state['hint'])
        self.assertIn('Сопоставление значений', state['hint'])


class PositionPoolTests(TestCase):
    """Функции пула по ключевым словам с начала слова (documentation/position-pool.md)."""

    def test_keywords_match_word_starts(self):
        from blog.services.position_pool import classify
        cases = {
            'Ассистент выдачи номеров и пакетов участника — 42,2 км': 'Организация выдачи пакетов участников',
            'Тим-лидер волонтёров организации сервисов для отдельных клиентских категорий - СМИ': 'Организация сервисов для отдельных клиентских групп',
            'Волонтёр раздевалок в стартовом городке': 'Организация сервисов для отдельных клиентских групп',
            'Волонтёр церемонии награждения': 'Волонтёры режиссёрской группы',
            'Волонтер для контроля ксерокопирования': 'Организация выдачи пакетов участников',
            'Волонтеры на пунктах передачи (П2, П3, П8)': 'Волонтёры специальных стартов',
            'Волонтёр пункта питания на дистанции (ПП2)': 'Волонтёры дистанции',
            'Волонтёр выдачи питания на финише': 'Волонтёры финиша',
            'Тим-лидер зоны регистрации и информации': 'Организация выдачи пакетов участников',
            'Стюард парка — Центральная аллея': 'Организация сервисов для спортсменов и зрителей',
        }
        for text, function in cases.items():
            self.assertEqual(classify(text), function, text)


class HubUploadTests(MigrationTestCase):
    """Хаб (запрос 2026-11-11): формы загрузки в карточках списков, файл попадает
    туда, где нужен, по своим листам; год базы определяется сам; ошибки видны."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.manager)
        self.url = reverse('legacy_migration')

    def post(self, action, field, name, content, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(self.url, {'action': action, field: SimpleUploadedFile(name, content), **extra}, follow=True)

    def test_fap_sent_through_base_form_lands_in_library(self):
        response = self.post('upload_base', 'workbook', 'Ночной 2026 - Функции и позиции.xlsx', (FAP_DIR / 'night-2026-split-day.xlsx').read_bytes())
        self.assertEqual(FapDocument.objects.get().title, 'Ночной 2026')
        self.assertFalse(LegacyBase.objects.exists())
        self.assertContains(response, 'Ночной 2026')

    def test_base_sent_through_fap_form_becomes_base_with_detected_year(self):
        headers = PROFILE + ['Ночной\n18.06.2025\nДень выдачи', 'ММ\n24 сентября\nВыдача']
        content = base_xlsx(ANNA[:9] + ['1 - Ассистент', '2 - Волонтёр'], headers=headers)
        self.post('upload_fap', 'workbooks', 'база.xlsx', content)
        base = LegacyBase.objects.get()
        self.assertEqual(base.year, 2025)
        self.assertEqual(base.columns.get(header__startswith='ММ').day, date(2025, 9, 24))
        self.assertFalse(FapDocument.objects.exists())

    def test_year_from_file_name_wins_and_manual_year_is_kept(self):
        self.post('upload_base', 'workbook', 'база 2024.xlsx', base_xlsx(ANNA))
        self.assertEqual(LegacyBase.objects.get().year, 2024)
        LegacyBase.objects.all().delete()
        self.post('upload_base', 'workbook', 'база 2024.xlsx', base_xlsx(BORIS), year=2023)
        self.assertEqual(LegacyBase.objects.get().year, 2023)

    def test_invalid_upload_is_reported_at_top(self):
        response = self.post('upload_fap', 'workbooks', 'notes.txt', b'hello')
        self.assertContains(response, 'Загрузка ФиП: Нужен файл .xlsx')
        response = self.post('upload_fap', 'workbooks', 'pusto.xlsx', base_xlsx(headers=['что-то']).replace(b'xl/workbook.xml', b'xl/workbook.xml'))
        self.assertFalse(FapDocument.objects.exists())

    def test_upload_forms_live_inside_list_cards(self):
        page = self.client.get(self.url).content.decode()
        bases, library = page.index('id="bases"'), page.index('id="fap-library"')
        self.assertLess(bases, page.index('name="workbook"'))
        self.assertLess(page.index('name="workbook"'), library)
        self.assertLess(library, page.index('name="workbooks"'))


class BaseFapTableTests(MigrationTestCase):
    """Таблица «Колонки базы ↔ ФиП» (2026-11-11): сохранение с ручной датой,
    уже выбранные дни ФиП не предлагаются другим колонкам."""

    def test_save_with_manual_date_in_russian_format(self):
        base = self.upload()
        column = base.columns.get(header__startswith='БФБ\n23 августа \nвс - 1')
        self.client.force_login(self.manager)
        response = self.client.post(reverse('legacy_migration_base', args=[base.pk]),
                                    {'action': 'map_fap', f'day_{column.pk}': '24.08.2026'})
        self.assertEqual(response.status_code, 302)
        column.refresh_from_db()
        self.assertEqual(column.day, date(2026, 8, 24))

    def test_chosen_fap_day_hidden_for_other_columns(self):
        base = self.upload()
        [(_, document, _)] = lm.upload_fap_files(self.manager, [('ММ 2026.xlsx', FAP.read_bytes())])
        first, second = base.columns.filter(header__startswith='ММ').order_by('index')[:2]
        lm.map_columns_to_fap(self.manager, base, {first.pk: f'{document.pk}|2026-09-24'})
        items = {i['column'].pk: i for i in lm.base_overview(base)['columns']}
        values = lambda item: [d['value'] for c in item['fap_options'] for d in c['days']]
        self.assertIn(f'{document.pk}|2026-09-24', values(items[first.pk]))
        self.assertNotIn(f'{document.pk}|2026-09-24', values(items[second.pk]))
        self.assertIn(f'{document.pk}|2026-09-25', values(items[second.pk]))



class FunctionMappingTests(MigrationTestCase):
    """Решение 2026-11-11: мероприятие → функции (названия колонки B ФиП, пул ~10–20)
    → позиции внутри функции. В сопоставлении выбирается функция, затем позиция."""

    def test_pool_holds_fap_function_names(self):
        names = set(lm.dc.event_functions_qs().values_list('name', flat=True))
        for name in ('Организация сервисов для отдельных клиентских групп', 'Волонтёры-атташе и волонтёры отеля-партнёра',
                     'Волонтёры режиссёрской группы', 'Волонтёры дистанции'):
            self.assertIn(name, names)
        self.assertLessEqual(len(names), 20)

    def test_new_position_is_created_inside_chosen_or_new_function(self):
        base = self.upload()
        lm.load_people(self.manager, base)
        columns = list(base.columns.filter(header__startswith='БФБ').order_by('index'))
        group = lm.create_event_from_columns(self.manager, base, [c.pk for c in columns], 'БФБ 2026')
        rows = {row['raw']: row for row in lm.mapping_table(group)}
        self.assertEqual(lm.dc.event_functions_qs().get(pk=rows['Волонтёр выдачи медалей']['function_selected']).name,
                         'Волонтёры финиша')
        finish = lm.dc.event_functions_qs().get(name='Волонтёры финиша')
        lm.save_mappings(self.manager, group, [
            {'key': rows['Волонтёр выдачи медалей']['key'], 'raw': 'Волонтёр выдачи медалей', 'target': 'new',
             'role': 'volunteer', 'title': 'Волонтёр выдачи медалей', 'function': str(finish.pk)},
            {'key': rows['Ассистент выдачи номеров']['key'], 'raw': 'Ассистент выдачи номеров', 'target': 'new',
             'role': 'volunteer', 'title': 'Ассистент выдачи номеров', 'function': 'new', 'function_name': 'Стартовый городок'},
        ])
        medals = group.positions.get(title='Волонтёр выдачи медалей')
        self.assertEqual(list(medals.category_map.filter(category__kind='function').values_list('category__name', flat=True)), ['Волонтёры финиша'])
        numbers = group.positions.get(title='Ассистент выдачи номеров')
        self.assertEqual(list(numbers.category_map.filter(category__kind='function').values_list('category__name', flat=True)), ['Стартовый городок'])
        page = lm.group_page(group)
        self.assertEqual({f.name for f in page['used_functions']}, {'Волонтёры финиша', 'Стартовый городок'})

    def test_team_lead_is_assigned_to_every_position_of_the_function(self):
        base = self.upload()
        lm.load_people(self.manager, base)
        group, columns = self.marathon(base)
        lm.attach_fap(self.manager, group, FAP.read_bytes(), FAP.name)
        self.map_all(group)
        lm.load_columns(self.manager, [columns[0]])
        boris = User.objects.get(first_name='Борис')
        function = lm.dc.event_functions_qs().get(name='Организация выдачи пакетов участников')
        positions = group.positions.filter(category_map__category=function)
        self.assertGreater(positions.count(), 5)
        self.assertEqual(EventStaff.objects.filter(user=boris, staff_role='team_lead', event__in=positions).count(), positions.count())
        lm.unload_column(self.manager, base.columns.get(pk=columns[0].pk))
        self.assertFalse(EventStaff.objects.filter(user=boris, staff_role='team_lead').exists())
