"""Табличка желающих (documentation/volunteer-wishes.md).

Желающие — люди, которые ещё ДО старта набора попросили знакомых тим-лидеров/менеджеров
взять их на следующий забег. Мероприятия в платформе ещё нет (оно только в календаре
сообщества), поэтому запись не привязана к EventGroup: она хранит разобранные подсказки
(название, даты, позиция) и исходное сообщение, а сопоставление с мероприятием
выполняется при показе страницы мероприятия.

Инварианты, которые страхуют тесты:
- добавлять/забирать могут только тим-лидеры и менеджеры (бот и веб — одно правило);
- одна запись = человек × мероприятие из сообщения: «хочет на СКБС и на Скорость» —
  две записи, чтобы «забрал на СКБС» не скрывал человека со Скорости;
- забранный в мероприятие человек показывается только в нём и не «теряется»;
- отметку «забрал» снимает тот, кто ставил, или менеджер.
"""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import EventGroup, VolunteerWish
from blog.services import volunteer_wishes as wishes
from tg_bot import services as bot_services
from . import factories as f

TODAY = datetime.date(2026, 11, 11)


def d(day, month=11, year=2026):
    return datetime.date(year, month, day)


def parse(text):
    return wishes.parse_wish_message(text, today=TODAY)


class ParseUserExamplesTests(TestCase):
    """Шесть реальных примеров из чатов сообщества (формулировка пользователя)."""

    def test_username_name_and_two_events(self):
        rows = parse('@ivan_petrov Петров Иван хочет на СКБС  и на Скорость')
        self.assertEqual([r['event_hint'] for r in rows], ['СКБС', 'Скорость'])
        for row in rows:
            self.assertEqual(row['telegram_username'], 'ivan_petrov')
            self.assertEqual(row['full_name'], 'Петров Иван')
            self.assertEqual(row['dates'], [])

    def test_days_without_month_and_comment(self):
        rows = parse('@masha_k хочет 14 и 15-го, очень классная')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['telegram_username'], 'masha_k')
        self.assertEqual(rows[0]['event_hint'], '')
        self.assertEqual(rows[0]['dates'], [d(14), d(15)])
        self.assertEqual(rows[0]['full_name'], '')

    def test_day_with_month_and_event(self):
        rows = parse('@kolya_run хочет 21 ноября на Скорость')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event_hint'], 'Скорость')
        self.assertEqual(rows[0]['dates'], [d(21)])

    def test_username_on_own_line_and_range(self):
        rows = parse('@olya_s\nХочет 21-22')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['telegram_username'], 'olya_s')
        self.assertEqual(rows[0]['dates'], [d(21), d(22)])

    def test_lowercase_event_name(self):
        rows = parse('@petya_v хочет на скорость')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event_hint'], 'Скорость')

    def test_username_at_the_end(self):
        rows = parse('Хочет на скорость 21 и 22 @sasha_m')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['telegram_username'], 'sasha_m')
        self.assertEqual(rows[0]['event_hint'], 'Скорость')
        self.assertEqual(rows[0]['dates'], [d(21), d(22)])


class ParseEdgeCasesTests(TestCase):
    def test_several_usernames_with_phones(self):
        rows = parse('@anna_one +7 912 345-67-89 @boris_two 89123456780 хотят на Скорость')
        self.assertEqual(
            [(r['telegram_username'], r['phone']) for r in rows],
            [('anna_one', '+79123456789'), ('boris_two', '+79123456780')],
        )
        self.assertTrue(all(r['event_hint'] == 'Скорость' for r in rows))

    def test_phone_only(self):
        rows = parse('+79001112233 хочет на скорость')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['phone'], '+79001112233')
        self.assertEqual(rows[0]['telegram_username'], '')

    def test_position_hints(self):
        self.assertEqual(parse('@vova_r хочет на справки')[0]['position_hint'], 'справки')
        self.assertEqual(parse('@vova_r хочет на справки')[0]['event_hint'], '')
        row = parse('@vova_r хочет на ПП/дистанцию')[0]
        self.assertEqual(row['position_hint'], 'ПП/дистанцию')
        self.assertEqual(row['event_hint'], '')
        row = parse('@vova_r хочет на Скорость на справки')[0]
        self.assertEqual((row['event_hint'], row['position_hint']), ('Скорость', 'справки'))

    def test_position_from_function_pool(self):
        """Слова из пула функций/категорий платформы тоже распознаются как позиция."""
        rows = wishes.parse_wish_message(
            '@vova_r хочет на гардероб', today=TODAY, position_vocab=['Гардероб'],
        )
        self.assertEqual((rows[0]['event_hint'], rows[0]['position_hint']), ('', 'гардероб'))

    def test_each_line_with_own_wish(self):
        rows = parse('@anna_one хочет на скорость\n@boris_two хочет на СКБС')
        self.assertEqual(
            [(r['telegram_username'], r['event_hint']) for r in rows],
            [('anna_one', 'Скорость'), ('boris_two', 'СКБС')],
        )

    def test_shared_wish_listed_before_people(self):
        rows = parse('Хотят на скорость:\n@anna_one\n@boris_two')
        self.assertEqual(
            [(r['telegram_username'], r['event_hint']) for r in rows],
            [('anna_one', 'Скорость'), ('boris_two', 'Скорость')],
        )

    def test_name_without_contacts(self):
        rows = parse('Петров Иван хочет на скорость')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['full_name'], 'Петров Иван')

    def test_nobody_identified(self):
        self.assertEqual(parse('хочет на скорость 21 и 22'), [])
        self.assertEqual(parse(''), [])

    def test_past_dates_roll_forward(self):
        """Желающих записывают заранее: прошедшая дата — это следующий год/месяц."""
        self.assertEqual(parse('@x_user хочет 5 ноября')[0]['dates'], [d(5, 11, 2027)])
        self.assertEqual(parse('@x_user хочет 5-го')[0]['dates'], [d(5, 12)])
        self.assertEqual(parse('@x_user хочет 03.01')[0]['dates'], [d(3, 1, 2027)])

    def test_counts_are_not_dates(self):
        """«2 дня», «3 смены», «10 км» — количество, а не число месяца."""
        for text in ('@x_user хочет на Быстрый пёс 2 дня', '@x_user хочет на 3 смены', '@x_user хочет на 10 км'):
            self.assertEqual(parse(text)[0]['dates'], [], text)

    def test_username_case_and_tme_link(self):
        rows = parse('https://t.me/Ivan_Petrov хочет на скорость')
        self.assertEqual(rows[0]['telegram_username'], 'ivan_petrov')


class WishServiceTests(TestCase):
    def setUp(self):
        self.tl = f.make_team_leader()
        self.manager = f.make_manager()
        self.volunteer = f.make_user()

    def add(self, text, actor=None):
        created, error = wishes.add_wishes_from_message(actor or self.tl, text, source='web', today=TODAY)
        self.assertIsNone(error)
        return created

    def test_volunteer_cannot_add(self):
        created, error = wishes.add_wishes_from_message(self.volunteer, '@x_user хочет на скорость', source='web')
        self.assertEqual((created, error), ([], 'forbidden'))
        self.assertFalse(VolunteerWish.objects.exists())

    def test_empty_message_reports_no_people(self):
        created, error = wishes.add_wishes_from_message(self.tl, 'хочет на скорость', source='web')
        self.assertEqual((created, error), ([], 'no_people'))

    def test_add_links_existing_user_and_keeps_raw_text(self):
        person = f.make_user(telegram_username='Ivan_Petrov')
        rows = self.add('@ivan_petrov хочет на СКБС и на Скорость')
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.user_id == person.id for r in rows))
        self.assertTrue(all(r.added_by_id == self.tl.id for r in rows))
        self.assertEqual(len({r.batch_id for r in rows}), 1)
        self.assertEqual(rows[0].raw_text, '@ivan_petrov хочет на СКБС и на Скорость')
        self.assertEqual(rows[0].wish_dates, [])

    def _group(self, title, *days):
        group = EventGroup.objects.create(title=title)
        position = f.make_event(title='Регистрация', event_group=group)
        for day in days:
            shift = f.make_shift(position)
            shift.day = day
            shift.save(update_fields=['day'])
        return group

    def test_matching_by_name_dates_and_acronym(self):
        speed = self._group('Скорость 2026', d(21), d(22))
        by_name = self.add('@a_name хочет на скорость')[0]
        by_date = self.add('@b_date хочет 22 ноября')[0]
        other_event_same_day = self.add('@c_other хочет 21 ноября на СКБС')[0]
        no_hints = self.add('@d_none очень хочет')[0]
        table = wishes.wishes_for_event_group(speed, self.tl)
        self.assertEqual({w.id for w in table['matched']}, {by_name.id, by_date.id})
        self.assertEqual({w.id for w in table['others']}, {other_event_same_day.id, no_hints.id})

        skbs = self._group('Северный Кросс «Белые Сопки»', d(5, 12))
        table = wishes.wishes_for_event_group(skbs, self.tl)
        self.assertIn(other_event_same_day.id, {w.id for w in table['matched']})

    def test_take_and_untake(self):
        soon = timezone.localdate() + datetime.timedelta(days=10)
        group = self._group('Скорость 2026', soon)
        other = self._group('Другой забег', soon + datetime.timedelta(days=7))
        wish = self.add('@a_name хочет на скорость')[0]
        _, error = wishes.mark_wish_taken(self.volunteer, wish.id, group.id)
        self.assertEqual(error, 'forbidden')

        wish, error = wishes.mark_wish_taken(self.tl, wish.id, group.id)
        self.assertIsNone(error)
        self.assertEqual((wish.taken_by_id, wish.taken_event_group_id), (self.tl.id, group.id))
        self.assertIsNotNone(wish.taken_at)
        table = wishes.wishes_for_event_group(group, self.tl)
        self.assertEqual([w.id for w in table['matched']], [wish.id])
        # Забранный в одно мероприятие не висит «прочим» желающим в других.
        other_table = wishes.wishes_for_event_group(other, self.tl)
        self.assertNotIn(wish.id, {w.id for w in other_table['matched'] + other_table['others']})

        # Вернуть из «забрали» в желающие может любой ТЛ/менеджер (общий пул), не волонтёр.
        _, error = wishes.unmark_wish_taken(self.volunteer, wish.id)
        self.assertEqual(error, 'forbidden')
        wish, error = wishes.unmark_wish_taken(f.make_team_leader(), wish.id)
        self.assertIsNone(error)
        self.assertIsNone(wish.taken_event_group_id)
        self.assertIsNone(wish.taken_by_id)

    def test_delete_by_author_or_manager_only(self):
        wish = self.add('@a_name хочет на скорость')[0]
        self.assertEqual(wishes.delete_wish(f.make_team_leader(), wish.id), 'forbidden')
        self.assertIsNone(wishes.delete_wish(self.tl, wish.id))
        self.assertFalse(VolunteerWish.objects.filter(pk=wish.id).exists())
        wish = self.add('@b_name хочет на скорость')[0]
        self.assertIsNone(wishes.delete_wish(self.manager, wish.id))

    def test_undo_batch_only_for_author(self):
        rows = self.add('@ivan_petrov хочет на СКБС и на Скорость')
        batch = rows[0].batch_id
        self.assertEqual(wishes.delete_wish_batch(self.manager, batch), (0, 'forbidden'))
        self.assertEqual(wishes.delete_wish_batch(self.tl, batch), (2, None))


class WishWebTests(TestCase):
    def setUp(self):
        self.tl = f.make_team_leader()
        self.volunteer = f.make_user()
        self.group = EventGroup.objects.create(title='Скорость 2026')
        f.make_event(title='Регистрация', event_group=self.group)

    def test_wishlist_page_acl(self):
        self.client.force_login(self.volunteer)
        self.assertEqual(self.client.get(reverse('volunteer_wishes')).status_code, 403)
        self.client.force_login(self.tl)
        self.assertEqual(self.client.get(reverse('volunteer_wishes')).status_code, 200)

    def test_add_from_web_form(self):
        self.client.force_login(self.tl)
        response = self.client.post(reverse('volunteer_wish_add'), {'text': '@a_name хочет на скорость'})
        self.assertEqual(response.status_code, 302)
        wish = VolunteerWish.objects.get()
        self.assertEqual((wish.telegram_username, wish.event_hint, wish.source), ('a_name', 'Скорость', 'web'))
        page = self.client.get(reverse('volunteer_wishes'))
        self.assertContains(page, '@a_name')

    def test_add_without_people_shows_error(self):
        self.client.force_login(self.tl)
        response = self.client.post(reverse('volunteer_wish_add'), {'text': 'хочет на скорость'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(VolunteerWish.objects.exists())
        self.assertContains(response, 'юзернейм')

    def test_event_group_page_shows_table_only_to_staff(self):
        wish, _ = wishes.add_wishes_from_message(self.tl, '@a_name хочет на скорость', source='web')
        url = reverse('event_group_detail', args=[self.group.pk])
        self.client.force_login(self.tl)
        response = self.client.get(url)
        self.assertContains(response, 'Желающие')
        self.assertContains(response, '@a_name')
        self.client.force_login(self.volunteer)
        response = self.client.get(url)
        self.assertNotContains(response, '@a_name')

    def test_take_and_untake_from_event_page(self):
        wish = wishes.add_wishes_from_message(self.tl, '@a_name хочет на скорость', source='web')[0][0]
        self.client.force_login(self.tl)
        url = reverse('event_group_detail', args=[self.group.pk])
        response = self.client.post(reverse('volunteer_wish_take', args=[wish.pk]), {'group': self.group.pk, 'next': url})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        wish.refresh_from_db()
        self.assertEqual(wish.taken_event_group_id, self.group.pk)
        self.assertContains(self.client.get(url), 'Вернуть в желающие')
        self.client.post(reverse('volunteer_wish_untake', args=[wish.pk]), {'next': url})
        wish.refresh_from_db()
        self.assertIsNone(wish.taken_event_group_id)

    def test_volunteer_cannot_take(self):
        wish = wishes.add_wishes_from_message(self.tl, '@a_name хочет на скорость', source='web')[0][0]
        self.client.force_login(self.volunteer)
        response = self.client.post(reverse('volunteer_wish_take', args=[wish.pk]), {'group': self.group.pk})
        self.assertEqual(response.status_code, 403)

    def test_profile_button_only_for_staff(self):
        self.client.force_login(self.tl)
        self.assertContains(self.client.get(reverse('profile_detail', args=[self.tl.pk])), reverse('volunteer_wishes'))
        self.client.force_login(self.volunteer)
        self.assertNotContains(self.client.get(reverse('profile_detail', args=[self.volunteer.pk])), reverse('volunteer_wishes'))


class WishBotServiceTests(TestCase):
    def test_bot_add_and_undo(self):
        tl = f.make_team_leader()
        rows, error = bot_services.add_volunteer_wishes(tl.id, '@a_name хочет на скорость 21 и 22')
        self.assertIsNone(error)
        self.assertEqual(rows[0].source, 'bot')
        self.assertEqual(bot_services.undo_volunteer_wishes(tl.id, str(rows[0].batch_id)), (1, None))
        self.assertFalse(VolunteerWish.objects.exists())

    def test_bot_volunteer_forbidden(self):
        volunteer = f.make_user()
        self.assertEqual(bot_services.add_volunteer_wishes(volunteer.id, '@a_name хочет на скорость'), ([], 'forbidden'))
        self.assertFalse(bot_services.can_add_volunteer_wishes(volunteer.id))
        self.assertTrue(bot_services.can_add_volunteer_wishes(f.make_team_leader().id))

    def test_summary_text(self):
        tl = f.make_team_leader()
        rows, _ = bot_services.add_volunteer_wishes(tl.id, '@ivan_petrov Петров Иван хочет на СКБС и на Скорость')
        text = bot_services.volunteer_wishes_summary(rows)
        self.assertIn('@ivan_petrov', text)
        self.assertIn('Петров Иван', text)
        self.assertIn('СКБС', text)
        self.assertIn('Скорость', text)


class WishTakenLifecycleTests(TestCase):
    """«Забрали» — не удаление: человек остаётся в табличке со статусом, пока не пройдёт
    мероприятие, куда его забрали, или пока статус висит дольше `wish_taken_hide_days`
    (Const, по умолчанию 3 дня). Потом он уходит в архив — из таблицы желающих пропадает,
    но запись цела, и его можно вернуть в желающие."""

    def setUp(self):
        self.tl = f.make_team_leader()
        self.client.force_login(self.tl)
        self.today = timezone.localdate()
        self.group = self._group('Скорость 2026', 10)
        self.twin = self._group('Скорость весна', 40)
        self.taken = wishes.add_wishes_from_message(self.tl, '@taken_one хочет на скорость', source='web')[0][0]
        self.open = wishes.add_wishes_from_message(self.tl, '@open_one хочет на скорость', source='web')[0][0]
        wishes.mark_wish_taken(self.tl, self.taken.id, self.group.id)

    def _group(self, title, days_from_now):
        group = EventGroup.objects.create(title=title)
        f.make_shift(f.make_event(title='Регистрация', event_group=group), days_from_now=days_from_now)
        return group

    def ids(self, rows):
        return {row.id for row in rows}

    def age_taken(self, days):
        VolunteerWish.objects.filter(pk=self.taken.pk).update(
            taken_at=timezone.now() - datetime.timedelta(days=days, minutes=1))

    def test_taken_stays_in_table_with_status(self):
        self.assertEqual(self.ids(wishes.wishes_list(self.tl, 'active')), {self.taken.id, self.open.id})
        # На другом подходящем мероприятии виден со статусом «забрали», без кнопки «Забрал».
        twin = wishes.wishes_for_event_group(self.twin, self.tl)
        self.assertIn(self.taken.id, self.ids(twin['matched']))
        self.assertEqual(twin['open_count'], 1)
        page = self.client.get(reverse('event_group_detail', args=[self.twin.pk])).content.decode()
        self.assertIn('@taken_one', page)
        self.assertIn('Забрали', page)
        self.assertIn('Скорость 2026', page)
        self.assertEqual(page.count(reverse('volunteer_wish_take', args=[self.taken.pk])), 0)

    def test_hidden_after_hide_days(self):
        self.age_taken(3)
        self.assertEqual(self.ids(wishes.wishes_list(self.tl, 'active')), {self.open.id})
        self.assertNotIn(self.taken.id, self.ids(wishes.wishes_for_event_group(self.group, self.tl)['matched']))
        self.assertEqual(self.ids(wishes.wishes_list(self.tl, 'archive')), {self.taken.id})
        self.assertNotContains(self.client.get(reverse('volunteer_wishes')), '@taken_one')

    def test_hide_days_is_a_const(self):
        f.make_const('wish_taken_hide_days', 10)
        self.age_taken(5)
        self.assertIn(self.taken.id, self.ids(wishes.wishes_list(self.tl, 'active')))

    def test_hidden_after_event_passed(self):
        past = self._group('Скорость прошлая', -1)
        wish = wishes.add_wishes_from_message(self.tl, '@past_one хочет на скорость', source='web')[0][0]
        wishes.mark_wish_taken(self.tl, wish.id, past.id)
        self.assertNotIn(wish.id, self.ids(wishes.wishes_list(self.tl, 'active')))
        self.assertIn(wish.id, self.ids(wishes.wishes_list(self.tl, 'archive')))

    def test_hide_taken_toggle(self):
        event_url = reverse('event_group_detail', args=[self.group.pk])
        self.assertContains(self.client.get(event_url), '@taken_one')
        response = self.client.get(event_url, {'wishes_hide_taken': '1'})
        self.assertNotContains(response, '@taken_one')
        self.assertContains(response, '@open_one')
        self.assertContains(response, 'Показать забранных')
        response = self.client.get(reverse('volunteer_wishes'), {'hide_taken': '1'})
        self.assertNotContains(response, '@taken_one')
        self.assertContains(response, '@open_one')

    def test_return_from_archive_to_wishers(self):
        self.age_taken(4)
        response = self.client.post(reverse('volunteer_wish_untake', args=[self.taken.pk]),
                                    {'next': reverse('volunteer_wishes') + '?status=archive'})
        self.assertEqual(response.status_code, 302)
        self.taken.refresh_from_db()
        self.assertIsNone(self.taken.taken_event_group_id)
        self.assertIn(self.taken.id, self.ids(wishes.wishes_list(self.tl, 'active')))
        self.assertContains(self.client.get(reverse('volunteer_wishes'), {'status': 'archive'}), 'Архив')
