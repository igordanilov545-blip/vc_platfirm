"""Чистая нормализация имён соцсетей и восстановление ссылок, без сетевых запросов."""
import re
from urllib.parse import unquote, urlsplit

HOSTS = {'vk': ('vk.com', 'vkontakte.ru'), 'instagram': ('instagram.com',),
         'telegram': ('t.me', 'telegram.me')}
PREFIXES = {'vk': 'https://vk.com/', 'instagram': 'https://www.instagram.com/', 'telegram': 'https://t.me/'}


def social_username(value, platform):
    text = str(value or '').strip().lstrip('@').strip()
    if not text:
        return ''
    candidate = text if '://' in text else 'https://' + text
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or '').casefold().removeprefix('www.')
    except ValueError:
        return ''
    if host in HOSTS[platform]:
        text = unquote(parsed.path).strip('/').split('/')[0].lstrip('@')
    elif '://' in text:
        return ''
    else:
        text = text.split('?', 1)[0].split('#', 1)[0].strip('/').lstrip('@')
    maximum = 255 if platform == 'instagram' else 100
    return text if len(text) <= maximum and re.fullmatch(r'[A-Za-z0-9_.-]+', text) else ''


def social_url(value, platform):
    handle = social_username(value, platform)
    return PREFIXES[platform] + handle + ('/' if platform == 'instagram' else '') if handle else ''


def social_value(value, platform):
    """Нормализовать понятный ник, иначе сохранить исходный свободный текст."""
    return social_username(value, platform) or str(value if value is not None else '').strip()
