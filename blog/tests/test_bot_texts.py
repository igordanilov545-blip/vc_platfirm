"""Тексты бота: бот бегового сообщества, без ПГАС, со статусом пользователя.

Решение пользователя (2026-11-11): бот говорит от лица бегового сообщества, а не
«Волонтёрского центра»; про ПГАС в боте не упоминается вовсе (ни в справке, ни в
/stats, ни в уведомлениях, которые сайт отправляет через бота); статус (волонтёр /
тим-лидер / менеджер) бот называет в /start, /help, /stats и после регистрации."""
import re
from pathlib import Path

from django.test import TestCase

from blog.services import notifications
from tg_bot import services
from tg_bot.templates_loader import render
from . import factories as f

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = re.compile(r'пгас|pgas|волонт[её]рск\w* центр|центра\b|\bВЦ\b', re.IGNORECASE)


def bot_sources():
    for path in sorted((ROOT / 'tg_bot').rglob('*')):
        if path.suffix in ('.py', '.txt') and '__pycache__' not in path.parts:
            yield path


class BotBrandingTests(TestCase):
    def test_no_volunteer_center_or_pgas_in_bot(self):
        found = []
        for path in bot_sources():
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if FORBIDDEN.search(line):
                    found.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual(found, [])

    def test_bot_introduces_itself_as_running_community(self):
        for template in ('start_new', 'help_guest'):
            self.assertIn('бегового сообщества', render(template))

    def test_notifications_sent_through_bot_have_no_pgas_or_center(self):
        """Уведомления, которые сайт отправляет через бота (стал ТЛ, снята верификация)."""
        from unittest import mock
        from blog.services import pgas_certificate
        user = f.make_user()
        f.make_manager()
        with (mock.patch('blog.services.notifications.notify_user') as notify,
              mock.patch.object(pgas_certificate, 'verification_invalidated', return_value=True)):
            notifications.notify_became_team_leader(user)
            pgas_certificate.revoke_verification_if_changed(user)
        sent = [call.args[1] for call in notify.call_args_list]
        self.assertGreaterEqual(len(sent), 2)
        for text in sent:
            self.assertIsNone(FORBIDDEN.search(text), text)
        self.assertIn('бегового сообщества', sent[0])


class BotStatusTests(TestCase):
    def test_stats_tell_status_and_no_pgas(self):
        stats = services.user_stats(f.make_team_leader().id)
        self.assertEqual(stats['role'], 'Тим-лидер')
        self.assertFalse({'is_star', 'hours_to_pgas'} & set(stats))
        self.assertEqual(services.user_stats(f.make_user().id)['role'], 'Волонтёр')
        self.assertEqual(services.user_stats(f.make_manager().id)['role'], 'Менеджер')

    def test_texts_show_status(self):
        self.assertIn('Статус: Менеджер', render('start_returning', name='Аня', role='Менеджер'))
        self.assertIn('Статус: Тим-лидер', render('help_role_footer', role='Тим-лидер'))
        self.assertIn('Статус: Волонтёр', render('register_done', role='Волонтёр'))
