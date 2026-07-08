"""Загрузчик текстовых шаблонов сообщений бота (tg-bot.md §11).

Шаблоны лежат в `tg_bot/templates_text/*.txt` — по одному файлу на сообщение
(`start_returning.txt`, `help_volunteer.txt`, ...). Тексты используют HTML-разметку
Telegram (`<b>`, `<i>`, `<code>`, `<a href>`), потому что бот запущен в
`ParseMode.HTML` (см. `bot.py`), и содержат кликабельные команды вида `/events`
(Telegram сам делает их кликабельными в HTML-тексте).

Использование:
    from tg_bot.templates_loader import render
    await message.answer(render('start_returning', name=user.first_name))

`render` кэширует содержимое файлов в памяти процесса (бот — долгоживущий процесс),
подставляет `{placeholders}` через `str.format`. Литеральные фигурные скобки в
шаблоне экранируются как `{{` и `}}` по правилам `str.format`.
"""
from functools import lru_cache
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / 'templates_text'


@lru_cache(maxsize=None)
def _load(template: str) -> str:
    path = TEMPLATES_DIR / f'{template}.txt'
    if not path.exists():
        raise FileNotFoundError(f'Шаблон сообщения не найден: {path}')
    # Храним тексты в UTF-8; хвостовой перевод строки убираем, чтобы у сообщений
    # не появлялась лишняя пустая строка снизу.
    return path.read_text(encoding='utf-8').rstrip('\n')


def render(template: str, **context) -> str:
    """Возвращает готовый текст шаблона `<template>.txt` с подставленными `{placeholders}`.

    Первый аргумент назван `template` (а не `name`), чтобы не конфликтовать с частым
    плейсхолдером `{name}`: `render('start_returning', name=user.first_name)`.
    Без плейсхолдеров вызывается просто `render('help_guest')`.
    """
    text = _load(template)
    return text.format(**context) if context else text
