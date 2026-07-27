"""fest_platform: раздача статичных HTML-макетов независимого демо-стенда.

ВНИМАНИЕ (для ИИ-агентов): это НЕ часть платформы ВЦ. Вьюхи просто отдают готовые
статичные файлы из documentation/fest_platform/mockups/ по адресам /demo/<page>,
чтобы владелец мог кинуть заказчику публичную ссылку на демку. Никакой бизнес-логики,
моделей, ACL — только FileResponse с готовым HTML. Подробнее — см.
documentation/fest_platform/_IGNORE_INDEPENDENT_PROJECT.md.
"""
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404

# Каталог с готовыми HTML-макетами (относительно корня репозитория).
_DEMO_DIR = Path(settings.BASE_DIR) / 'documentation' / 'fest_platform' / 'mockups'

# Белый список страниц: имя в URL -> имя файла. Только эти файлы и отдаём.
_PAGES = {
    '': 'overview.html',            # /demo/  -> обзор для ЛПР
    'overview': 'overview.html',
    'fest': 'fest.html',
    'market': 'market.html',
    'cabinet': 'cabinet.html',
    'organizer': 'organizer.html',
}


def demo_page(request, page=''):
    """Отдаёт статичный HTML-макет демо-стенда по имени страницы (белый список)."""
    filename = _PAGES.get(page.strip('/'))
    if not filename:
        raise Http404('demo page not found')
    path = _DEMO_DIR / filename
    if not path.exists():
        raise Http404('demo file missing')
    # content_type фиксируем явно — файл отдаётся как есть, без шаблонизатора Django.
    return FileResponse(open(path, 'rb'), content_type='text/html; charset=utf-8')
