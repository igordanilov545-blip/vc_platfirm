"""Личные предпочтения и визуальный контекст; контракт — appearance-system.md."""
from functools import lru_cache
import hashlib
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError

from blog.appearance import APPEARANCES, APPEARANCE_CHOICES, COLOR_THEME_CHOICES, get_appearance
from data_base import data_controller as dc


def update_appearance(user, data):
    """Проверяем весь запрос до записи: ошибочный вариант не меняет часть настроек."""
    fields = {}
    for key, choices in (('appearance', APPEARANCE_CHOICES), ('color_theme', COLOR_THEME_CHOICES)):
        if key in data:
            value = data[key]
            if value not in dict(choices):
                raise ValidationError('Выберите оформление и тему из предложенных вариантов.')
            fields[key] = value
    if not fields:
        raise ValidationError('Выберите оформление или тему.')
    dc.save_user_appearance(user, fields)


def appearance_context(user):
    """Гость всегда в Nexus; сохранённый выбор аккаунта важнее браузерного кэша."""
    authenticated = bool(user and user.is_authenticated)
    selected = get_appearance(user.appearance if authenticated else 'nexus')
    context = {
        'active_appearance': selected,
        'appearance_options': APPEARANCES,
        'color_theme_options': COLOR_THEME_CHOICES,
        'selected_color_theme': user.color_theme if authenticated else 'system',
    }
    if selected.key == 'minecraft':
        context.update(_minecraft_assets())
        # Случайное распределение без смены лица при переходах и переключении темы.
        avatars = ('boy', 'bunny', 'cat', 'dog', 'dolphin', 'fox', 'girl', 'old-man', 'old-woman', 'parrot')
        index = int.from_bytes(hashlib.sha256(f'minecraft-avatar-v1:{user.pk}'.encode()).digest()[:4], 'big') % len(avatars)
        context['minecraft_avatar_asset'] = f'blog/appearances/minecraft/avatars/{avatars[index]}-avatar.png'
    return context


@lru_cache(maxsize=1)
def _minecraft_assets():
    """Нет файла — нет запроса 404. После поставки ассетов приложение перезапускают."""
    assets = {}
    for kind in ('world', 'foreground', 'hero'):
        for theme in ('light', 'dark'):
            path = f'blog/appearances/minecraft/{kind}-{theme}.webp'
            if finders.find(path):
                assets[f'minecraft_{kind}_{theme}_asset'] = path
    return assets
