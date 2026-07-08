# Текстовые шаблоны сообщений бота

Один `.txt` = одно шаблонное сообщение. Загружаются через
[`tg_bot/templates_loader.py`](../templates_loader.py):

```python
from tg_bot.templates_loader import render
await message.answer(render('start_returning', name=user.first_name))
```

## Правила

- **Кодировка** — UTF-8.
- **Разметка** — HTML Telegram (`<b>`, `<i>`, `<u>`, `<code>`, `<a href="...">`),
  потому что бот работает в `ParseMode.HTML`. Чистый текст тоже допустим.
- **Кликабельные команды** — пишем прямо в тексте как `/events`, `/register`.
  Telegram делает их кликабельными автоматически; пользователь может вызвать команду
  тапом по ней в тексте, а не только кнопкой меню.
- **Плейсхолдеры** — `{name}`, `{role}` и т.п., подставляются `str.format`.
  Литеральные фигурные скобки экранируются удвоением: `{{` и `}}`.
- Хвостовой перевод строки в конце файла обрезается загрузчиком.

## Именование

`<область>_<состояние>.txt`: `start_new`, `start_returning`, `help_guest`,
`help_volunteer`, `appnotify_on`, `appnotify_off`, `register_ask_name`, ...

Составные сообщения (например `/help` для ТЛ = `help_volunteer` + `help_team_leader`
+ `help_role_footer`) собираются конкатенацией нескольких шаблонов в хендлере.
