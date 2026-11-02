"""Foreground supervisor for the local web server and Telegram polling bot.

Ctrl+C stops all owned processes. --noreload prevents detached reloader workers.
"""
import os
import signal
import subprocess
import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _stop_process(process):
    if process.poll() is not None:
        process.wait()
        return
    if os.name == 'nt':
        # A Windows venv's python.exe can launch a child Python. Stop that too.
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class Command(BaseCommand):
    help = 'Веб и Telegram-бот в одном окне; Ctrl+C останавливает оба сервиса.'

    def add_arguments(self, parser):
        parser.add_argument('addrport', nargs='?', default='127.0.0.1:8000')
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--no-web', action='store_true', help='Только Telegram-бот.')
        mode.add_argument('--web-only', action='store_true', help='Только сайт, токен не нужен.')

    def handle(self, *args, **options):
        if not options['web_only'] and not settings.TG_BOT_TOKEN:
            raise CommandError('TG_BOT_TOKEN не задан в .env. Для сайта используйте --web-only.')
        commands = []
        if not options['no_web']:
            commands.append(['runserver', options['addrport'], '--noreload'])
        if not options['web_only']:
            commands.append(['run_bot'])
        processes = []
        previous_handlers = {}
        try:
            # Windows terminals also use Ctrl+Break; handle it with the same cleanup.
            if os.name == 'nt':
                import ctypes
                ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
                for sig in (signal.SIGINT, signal.SIGBREAK):
                    previous_handlers[sig] = signal.signal(sig, signal.default_int_handler)
            for command in commands:
                self.stdout.write(self.style.SUCCESS(f'Запускаю {command[0]}…'))
                process = subprocess.Popen(
                    [sys.executable, str(settings.BASE_DIR / 'manage.py'), *command],
                    cwd=settings.BASE_DIR,
                )
                processes.append((command[0], process))
            self.stdout.write('Остановка всей системы: Ctrl+C в этом окне.')
            while True:
                for name, process in processes:
                    exit_code = process.poll()
                    if exit_code is not None:
                        raise CommandError(f'{name} завершился (код {exit_code}). Сервисы остановлены.')
                time.sleep(0.25)
        except KeyboardInterrupt:
            self.stdout.write('Останавливаю систему…')
        finally:
            try:
                # Ignore repeated console interrupts while reaping child processes.
                for sig in previous_handlers:
                    signal.signal(sig, signal.SIG_IGN)
                for _, process in reversed(processes):
                    _stop_process(process)
                self.stdout.write('Система остановлена.')
            finally:
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)
