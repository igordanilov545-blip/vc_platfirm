# Запуск в Windows

Проект подготовлен в `D:\runc\vc_platform`: зависимости в `.venv`, локальная база
SQLite создана, миграции применены, статика собрана. Ubuntu, Docker, PostgreSQL,
Redis и Node.js для этого запуска не нужны.

## Обычный запуск

Открой PowerShell:

```powershell
cd D:\runc\vc_platform
# Сайт и Telegram-бот вместе:
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1 -WithBot
```

Сайт: http://127.0.0.1:8000/ . Остановка всей системы — **Ctrl+C** в том же окне
(также поддерживается Ctrl+Break). Дождись сообщения «Система остановлена».
Скрипт работает в текущем окне, без фоновых служб и автоперезапуска.
При ошибке одного сервиса второй также завершается.

После обновления кода и миграций нужен **полный перезапуск** этой команды: локальные
сайт и бот запускаются с `--noreload` и продолжают использовать загруженные модели.
Перед изменением схемы останови систему через Ctrl+C. Если после удаления поля
появляется `no such column: users.faculty`, старый процесс ещё запрашивает прежние
столбцы — останови его и запусти систему заново. Возвращать удалённые поля в БД не нужно.

Только сайт / только бот:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1 -BotOnly
```

Для другого порта добавь `-Port 8001`. Если будешь отправлять формы с другого
порта, добавь `http://127.0.0.1:8001` в `CSRF_TRUSTED_ORIGINS` в `.env`.

## Вход

Создан локальный менеджер `local_admin`. Его случайный пароль находится в
`documentation/dev_credentials.md` (файл исключён из Git). Вход: `/login/`.
Это отдельная локальная база; данные пользователей с сервера не переносились.

## Токены и настройки

Все значения указываются в **`.env` в корне проекта**. После изменения перезапусти
систему. Файл исключён из Git.

| Параметр | Что указать |
|---|---|
| `TG_BOT_TOKEN` | Токен от @BotFather. Переданный токен уже сохранён локально. |
| `TG_BOT_USERNAME` | Имя бота без `@`. Получено автоматически через Telegram API. |
| `SECRET_KEY` | Секрет Django. Уже сгенерирован автоматически. |
| `WEBAPP_URL` | Публичный HTTPS-адрес для Mini App и ссылок входа из бота. Для обычного сайта в браузере можно оставить пустым. |
| `TG_WEBHOOK_SECRET` | Для локального polling не нужен; оставить пустым. |
| `ANALYTICS_ADMIN_TG_IDS` | Необязательно: Telegram ID пользователей с доступом к технической аналитике, через запятую. |
| `SOFFICE_BIN` | Необязательно: полный путь к `soffice.exe`, если LibreOffice установлен нестандартно. |

Других обязательных API-токенов, SMTP-настроек или платных сервисов в текущем коде нет.
База SQLite работает без пароля. Настройки `DB_USER`, `DB_PASSWORD` и остальные
параметры PostgreSQL нужны только при переходе на `DB_ENGINE=postgres`.

Для Mini App нужен доступный из Telegram HTTPS-адрес (например, туннель к локальному
порту 8000): укажи его в `WEBAPP_URL`, его домен в `ALLOWED_HOSTS`, полный HTTPS-origin
в `CSRF_TRUSTED_ORIGINS`, настрой Mini App в @BotFather. Для Telegram Login Widget
домен привязывается через `/setdomain`. Обычный вход по логину/паролю работает без этого.

Локальный бот работает через long polling. Для одного токена запускай один экземпляр
бота. Если включён серверный webhook, локальный запуск сообщит об этом и остановится.
Команда снятия webhook существует (`manage.py set_webhook --delete`), но меняет
маршрутизацию обновлений этого бота и отключает их доставку на сервер.

## Повторная установка и проверки

На этом компьютере повторная установка не требуется. Для нового окружения нужны
Python 3.12 либо `uv` (он скачает Python). Затем:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-windows.ps1
```

Скрипт создаёт `.venv`, устанавливает зависимости, при отсутствии `.env` создаёт его
из `.env.windows.example` со случайным `SECRET_KEY`, выполняет миграции и сборку
статики. Существующий `.env` не перезаписывается. Для своего интерпретатора используй
`-PythonPath C:\path\to\python.exe` (Python 3.12).

LibreOffice нужен для PDF-справок из Word-шаблонов. На этом компьютере он уже найден
в `C:\Program Files\LibreOffice\program\soffice.exe`; реальная конвертация проверена.
Остальные PDF-письма создаются через PyMuPDF без системных библиотек GTK/Pango.

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test blog.tests
```

Логи: `logs/web.log`, `logs/bot.log`, `logs/db.log`.

Справка Telegram: [создание ботов](https://core.telegram.org/bots/features#botfather),
[Mini Apps](https://core.telegram.org/bots/webapps),
[polling и webhook](https://core.telegram.org/bots/api#getupdates).
