"""Local startup must fail cleanly and stop every owned service on exit."""
import io
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings

from blog.services import pgas_pdf


class LocalStartupTests(SimpleTestCase):
    def setUp(self):
        taskkill = patch('blog.management.commands.runall.subprocess.run')
        taskkill.start()
        self.addCleanup(taskkill.stop)

    @override_settings(TG_BOT_TOKEN='')
    @patch('blog.management.commands.runall.subprocess.Popen')
    def test_missing_bot_token_does_not_start_web(self, popen):
        with self.assertRaisesMessage(CommandError, 'TG_BOT_TOKEN'):
            call_command('runall', stdout=io.StringIO())
        popen.assert_not_called()

    @patch('blog.management.commands.runall.subprocess.Popen')
    def test_web_only_needs_no_bot_and_stops_after_interrupt(self, popen):
        web = popen.return_value
        web.poll.side_effect = [None, None]
        with patch('blog.management.commands.runall.time.sleep', side_effect=KeyboardInterrupt):
            call_command('runall', '--web-only', stdout=io.StringIO())
        self.assertEqual(popen.call_count, 1)
        self.assertIn('--noreload', popen.call_args.args[0])
        self.assertIn('runserver', popen.call_args.args[0])
        web.wait.assert_called()

    @override_settings(TG_BOT_TOKEN='123456:TEST')
    @patch('blog.management.commands.runall.subprocess.Popen')
    def test_service_failure_stops_its_sibling(self, popen):
        web, bot = Mock(), Mock()
        web.poll.return_value = 1
        bot.poll.return_value = None
        popen.side_effect = [web, bot]
        with self.assertRaisesMessage(CommandError, 'runserver'):
            call_command('runall', stdout=io.StringIO())
        bot.wait.assert_called()

    @override_settings(TG_BOT_TOKEN='123456:TEST')
    @patch('blog.management.commands.runall.subprocess.Popen')
    def test_failed_second_spawn_stops_web(self, popen):
        web = Mock()
        web.poll.return_value = None
        popen.side_effect = [web, OSError('cannot start bot')]
        with self.assertRaises(OSError):
            call_command('runall', stdout=io.StringIO())
        web.wait.assert_called()


class LibreOfficeWindowsTests(SimpleTestCase):
    @override_settings(SOFFICE_BIN=r'C:\Program Files\LibreOffice\program\soffice.exe')
    def test_configured_libreoffice_is_used(self):
        with patch.object(pgas_pdf.shutil, 'which', return_value='soffice.exe') as which:
            self.assertTrue(pgas_pdf.soffice_available())
        which.assert_called_once_with(r'C:\Program Files\LibreOffice\program\soffice.exe')

    def test_profile_uri_handles_spaces_and_conversion_returns_pdf(self):
        seen = []

        def convert(cmd, **kwargs):
            seen.extend(cmd)
            output_dir = Path(cmd[cmd.index('--outdir') + 1])
            (output_dir / 'template.pdf').write_bytes(b'%PDF-test')
            return subprocess.CompletedProcess(cmd, 0, b'', b'')

        with TemporaryDirectory(prefix='vc windows space ') as tmp:
            with patch.object(pgas_pdf.tempfile, 'TemporaryDirectory') as temporary:
                temporary.return_value.__enter__.return_value = tmp
                with patch.object(pgas_pdf.subprocess, 'run', side_effect=convert):
                    self.assertEqual(pgas_pdf.docx_to_pdf_bytes(b'docx'), b'%PDF-test')
            self.assertIn('-env:UserInstallation=' + (Path(tmp) / 'lo_profile').as_uri(), seen)


class BotStartupCleanupTests(SimpleTestCase):
    def test_api_failure_closes_http_session(self):
        from blog.management.commands.run_bot import Command
        bot = Mock()
        bot.get_webhook_info = AsyncMock(side_effect=RuntimeError('API unavailable'))
        bot.set_my_commands = AsyncMock(side_effect=RuntimeError('API unavailable'))
        bot.session.close = AsyncMock()
        with patch('blog.management.commands.run_bot.create_bot', return_value=bot):
            with self.assertRaisesMessage(RuntimeError, 'API unavailable'):
                from asgiref.sync import async_to_sync
                async_to_sync(Command()._run)()
        bot.session.close.assert_awaited_once()
