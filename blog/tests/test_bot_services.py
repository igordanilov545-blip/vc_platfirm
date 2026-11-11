"""Тесты синхронного сервис-слоя бота (tg_bot/services/*).

Сервисы бота синхронные (хендлеры зовут их через sync_to_async), поэтому тестируются
как обычные функции. Фиксируют поведение ПЕРЕД переносом прямого ORM бота на
data_controller (техдолг Фазы 5) — ловят регрессии в путях данных.
"""
from django.test import TestCase
from django.utils import timezone

from tg_bot import services
from blog.models import Participation, UserComment, Manager
from . import factories as f


class BotUsersServiceTests(TestCase):
    def test_get_user_returns_user(self):
        u = f.make_user()
        self.assertEqual(services.get_user(u.id), u)

    def test_is_guest(self):
        guest = f.make_user(registration_status='guest', phone=None)
        member = f.make_user(registration_status='registered')
        self.assertTrue(services.is_guest(guest))
        self.assertFalse(services.is_guest(member))

    def test_staff_and_complete_accounts_are_never_guests(self):
        """Гость — только тот, кто ещё не заполнил аккаунт и без роли. ТЛ/менеджер или
        человек с ФИО + Telegram + телефоном (заполнил на сайте, пришёл из базы) видит
        полное меню и справку своей роли, даже если в боте /register не проходил."""
        self.assertFalse(services.is_guest(f.make_team_leader(registration_status='guest', phone=None)))
        self.assertFalse(services.is_guest(f.make_manager(registration_status='guest', phone=None)))
        self.assertFalse(services.is_guest(f.make_user(registration_status='guest')))

    def test_validate_login_free_and_taken(self):
        u1 = f.make_user()
        u2 = f.make_user(login='taken_login')
        # свободный валидный логин
        self.assertIsNone(services.validate_login('brand_new', u1.id))
        # занятый другим пользователем
        self.assertIsNotNone(services.validate_login('taken_login', u1.id))
        # тот же логин у того же пользователя — не считается занятым
        self.assertIsNone(services.validate_login('taken_login', u2.id))
        # невалидный формат
        self.assertIsNotNone(services.validate_login('ab', u1.id))

    def test_confirm_recognized_account_merges_guest(self):
        # гость без активности + кандидат → telegram_id переносится, гость удаляется
        candidate = f.make_user(registration_status='member')
        guest = f.make_user(registration_status='guest', telegram_id='guest999')
        result, err = services.confirm_recognized_account(
            guest.id, candidate.id, telegram_id='guest999', telegram_username='cand',
        )
        self.assertIsNone(err)
        self.assertEqual(result.id, candidate.id)
        candidate.refresh_from_db()
        self.assertEqual(candidate.telegram_id, 'guest999')
        self.assertFalse(type(candidate).objects.filter(pk=guest.id).exists())

    def test_confirm_recognized_collision_when_guest_has_activity(self):
        candidate = f.make_user(registration_status='member')
        guest = f.make_user(registration_status='guest')
        event = f.make_event()
        f.make_application(event, user=guest)  # активность у гостя
        result, err = services.confirm_recognized_account(
            guest.id, candidate.id, telegram_id='x', telegram_username='y',
        )
        self.assertEqual(err, 'collision')
        self.assertIsNone(result)


class BotCommentsServiceTests(TestCase):
    def test_add_comment_requires_extended_access(self):
        manager = f.make_manager()
        target = f.make_user()
        comment, err = services.add_user_comment(manager.id, target.id, 'заметка')
        self.assertIsNone(err)
        self.assertIsNotNone(comment)
        self.assertTrue(UserComment.objects.filter(target_user=target, text='заметка').exists())

    def test_add_comment_forbidden_for_plain_volunteer(self):
        author = f.make_user()  # без роли
        target = f.make_user()
        comment, err = services.add_user_comment(author.id, target.id, 'x')
        self.assertEqual(err, 'forbidden')

    def test_add_comment_target_not_found(self):
        manager = f.make_manager()
        comment, err = services.add_user_comment(manager.id, 999999, 'x')
        self.assertEqual(err, 'not_found')


class BotApplicationsServiceTests(TestCase):
    def test_get_own_application_ownership(self):
        owner = f.make_user()
        other = f.make_user()
        event = f.make_event()
        app = f.make_application(event, user=owner)
        # владелец видит
        self.assertEqual(services.get_own_application(owner.id, app.id).id, app.id)
        # чужой — нет
        self.assertIsNone(services.get_own_application(other.id, app.id))


class BotFeedbackQueueTests(TestCase):
    def test_mark_feedback_requested(self):
        event = f.make_event()
        shift = f.make_shift(event)
        user = f.make_user()
        part = f.make_participation(user, shift, status='attended')
        self.assertIsNone(part.feedback_requested_at)
        services.mark_feedback_requested(part.id)
        part.refresh_from_db()
        self.assertIsNotNone(part.feedback_requested_at)

    def test_mark_feedback_requested_missing_is_noop(self):
        # несуществующий id не должен падать
        services.mark_feedback_requested(999999)
