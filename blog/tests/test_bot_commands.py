"""Команды бота, меню «/» Telegram и /help не расходятся (tg-bot.md §0).

Единый реестр — tg_bot/commands.py: из него строится меню команд по роли, а тексты
справки обязаны упоминать каждую команду своей роли. Тест страхует от ситуации «команда
есть, но о ней нигде не сказано» (так потерялись /get_qr, /weblogin, /publish…)."""
import re
from pathlib import Path

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TestCase

from tg_bot import commands
from tg_bot.templates_loader import render
from . import factories as f

HANDLERS = Path(__file__).resolve().parents[2] / 'tg_bot' / 'handlers'


def handler_commands():
    found = set()
    for path in HANDLERS.glob('*.py'):
        found |= set(re.findall(r"Command\('([a-z_]+)'\)", path.read_text(encoding='utf-8')))
    return found


def names(items):
    return {name for name, _ in items}


class BotCommandsRegistryTests(SimpleTestCase):
    def test_every_handler_command_is_registered(self):
        registered = set(commands.DESCRIPTIONS)
        self.assertEqual(handler_commands() - registered, set())
        self.assertEqual(registered - handler_commands() - {'start'}, set())

    def test_descriptions_fit_telegram_limits(self):
        for name, description in commands.DESCRIPTIONS.items():
            self.assertRegex(name, r'^[a-z0-9_]{1,32}$')
            self.assertTrue(3 <= len(description) <= 256, name)

    def test_role_menus(self):
        guest = names(commands.commands_for(is_guest=True))
        volunteer = names(commands.commands_for())
        leader = names(commands.commands_for(is_team_leader=True))
        manager = names(commands.commands_for(is_manager=True))
        self.assertIn('register', guest)
        self.assertNotIn('myapps', guest)
        self.assertIn('myapps', volunteer)
        self.assertNotIn('register', volunteer)
        self.assertTrue({'myevents', 'wish', 'appnotify'} <= leader)
        self.assertNotIn('publish', leader)
        self.assertTrue({'allapplications', 'publish', 'broadcast', 'wish', 'appnotify'} <= manager)
        self.assertNotIn('wish', volunteer)

    def test_help_mentions_every_command_of_the_role(self):
        guest_help = render('help_guest')
        for name in names(commands.commands_for(is_guest=True)) - {'start', 'help'}:
            self.assertIn(f'/{name}', guest_help, name)
        volunteer_help = render('help_volunteer')
        for name in names(commands.commands_for()) - {'start', 'help'}:
            self.assertIn(f'/{name}', volunteer_help, name)
        leader_help = volunteer_help + render('help_team_leader')
        for name in names(commands.commands_for(is_team_leader=True)) - {'start', 'help'}:
            self.assertIn(f'/{name}', leader_help, name)
        manager_help = volunteer_help + render('help_manager')
        for name in names(commands.commands_for(is_manager=True)) - {'start', 'help'}:
            self.assertIn(f'/{name}', manager_help, name)

    def test_every_menu_button_has_a_handler(self):
        """Кнопка нижнего меню без хендлера уходит в «Не знаю такую команду»."""
        from tg_bot import keyboards as kb
        source = ''.join(path.read_text(encoding='utf-8') for path in HANDLERS.glob('*.py'))
        handled = set(re.findall(r"F\.text == '([^']+)'", source))
        for group in re.findall(r"\.in_\(\{([^}]*)\}\)", source):
            handled |= set(re.findall(r"'([^']+)'", group))
        if 'F.text == kb.WISHES_BUTTON' in source:
            handled.add(kb.WISHES_BUTTON)
        for label in kb.MENU_BUTTONS - {'🖥 Личный кабинет'}:  # web_app-кнопка сообщений не шлёт
            self.assertTrue(label in handled or label.lower() in handled, label)


class RefreshChatCommandsTests(TestCase):
    """Личное меню «/» чата строится по роли; сбой Telegram не ломает /start."""

    class FakeBot:
        def __init__(self, fail=False):
            self.calls, self.fail = [], fail

        async def set_my_commands(self, items, scope=None):
            if self.fail:
                raise RuntimeError('telegram down')
            self.calls.append(([item.command for item in items], scope.chat_id))

    def test_team_leader_gets_personal_menu(self):
        leader = f.make_team_leader(registration_status='registered')
        bot = self.FakeBot()
        async_to_sync(commands.refresh_chat_commands)(bot, 42, leader)
        names_, chat_id = bot.calls[0]
        self.assertEqual(chat_id, 42)
        self.assertIn('wish', names_)
        self.assertIn('myevents', names_)
        self.assertNotIn('register', names_)

    def test_guest_menu_and_errors_are_swallowed(self):
        guest = f.make_user(registration_status='guest')
        bot = self.FakeBot()
        async_to_sync(commands.refresh_chat_commands)(bot, 7, guest)
        self.assertIn('register', bot.calls[0][0])
        async_to_sync(commands.refresh_chat_commands)(self.FakeBot(fail=True), 7, guest)
