"""Логи не теряются, если файл занят другим процессом при ротации (Windows, runall)."""
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from blog.log_handlers import SafeRotatingFileHandler


class SafeRotatingFileHandlerTests(SimpleTestCase):
    def test_record_is_written_when_rotation_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'web.log'
            handler = SafeRotatingFileHandler(path, maxBytes=50, backupCount=2, encoding='utf-8')
            logger = logging.getLogger('vc.test.safe_rotation')
            logger.addHandler(handler)
            logger.propagate = False
            try:
                logger.warning('x' * 80)
                with patch.object(logging.handlers.RotatingFileHandler, 'rotate', side_effect=PermissionError(32, 'busy')), \
                        patch.object(handler, 'handleError') as handle_error:
                    logger.warning('после занятого файла')
                    logger.warning('и ещё одна строка')
                handle_error.assert_not_called()
            finally:
                logger.removeHandler(handler)
                handler.close()
            text = path.read_text(encoding='utf-8')
            self.assertIn('после занятого файла', text)
            self.assertIn('и ещё одна строка', text)
