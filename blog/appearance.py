"""Стабильные идентификаторы оформлений; реестр не зависит от БД и HTTP-запроса."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Appearance:
    key: str
    title: str
    description: str
    stylesheet: str = ''
    decoration: str = ''


APPEARANCES = (
    Appearance('nexus', 'Nexus', 'Чистые линии, лёгкие карточки и фиолетовые акценты.'),
    Appearance('minecraft', 'Minecraft', 'Тёплое дерево, живой камень и свой маленький мир.',
               'blog/css/appearances/minecraft.css', 'blog/partials/_minecraft_world.html'),
)
APPEARANCE_CHOICES = tuple((item.key, item.title) for item in APPEARANCES)
COLOR_THEME_CHOICES = (('system', 'Как на устройстве'), ('light', 'Светлая'), ('dark', 'Тёмная'))


def get_appearance(key):
    """Неизвестный/удалённый вариант безопасно возвращает исходное оформление."""
    return next((item for item in APPEARANCES if item.key == key), APPEARANCES[0])
