"""Чтение страницы не ждёт завершения записи в локальную SQLite."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from django.conf import settings
from django.db import connections
from django.db.backends.sqlite3.base import DatabaseWrapper


@skipUnless(settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3', 'Локальный SQLite')
class SQLiteNavigationConcurrencyTests(TestCase):
    def test_connection_can_read_committed_data_while_another_request_writes(self):
        """Переход читает данные, пока сканер/бот держит запись."""
        with TemporaryDirectory() as folder:
            config = connections['default'].settings_dict.copy()
            config['NAME'] = str(Path(folder) / 'navigation.sqlite3')
            config['OPTIONS'] = {**config['OPTIONS'], 'timeout': .1}
            writer = DatabaseWrapper(config, alias='navigation_writer')
            reader = DatabaseWrapper(config, alias='navigation_reader')
            try:
                with writer.cursor() as cursor:
                    cursor.execute('CREATE TABLE navigation_probe (id INTEGER PRIMARY KEY)')
                reader.ensure_connection()
                with writer.cursor() as cursor:
                    cursor.execute('BEGIN EXCLUSIVE')
                    cursor.execute('INSERT INTO navigation_probe (id) VALUES (1)')
                with reader.cursor() as cursor:
                    cursor.execute('SELECT COUNT(*) FROM navigation_probe')
                    self.assertEqual(cursor.fetchone()[0], 0)
                writer.commit()
                with reader.cursor() as cursor:
                    cursor.execute('SELECT COUNT(*) FROM navigation_probe')
                    self.assertEqual(cursor.fetchone()[0], 1)
            finally:
                reader.close()
                writer.close()
