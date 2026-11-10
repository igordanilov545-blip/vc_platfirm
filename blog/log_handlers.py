"""Файловый обработчик логов, переживающий занятый файл при ротации (Windows).

`runall` запускает сайт и бота отдельными процессами, оба пишут в одни файлы
logs/*.log. На Windows переименовать открытый другим процессом файл нельзя:
стандартный RotatingFileHandler при достижении размера падает с PermissionError
на КАЖДОЙ записи, и строки лога теряются. Здесь неудачная ротация не теряет запись:
дописываем в текущий файл и повторяем попытку не чаще раза в минуту.
Модуль не импортирует Django — его подхватывает настройка LOGGING.
"""
import logging.handlers
import time

RETRY_SECONDS = 60


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    _retry_after = 0.0

    def shouldRollover(self, record):
        if time.monotonic() < self._retry_after:
            return False
        return super().shouldRollover(record)

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            self._retry_after = time.monotonic() + RETRY_SECONDS
            if self.stream is None:
                self.stream = self._open()
