# Деплой на Beget + CI/CD

Прод-домен: **https://vc.iedanimk.beget.tech**
Хостинг: Beget shared («Python-сайт» на Passenger), Python 3.10, SQLite.

## Архитектура на shared-хостинге

- **Веб** — Django под Phusion Passenger (`passenger_wsgi.py`), WSGI-воркер живёт
  постоянно. HTTPS терминируется фронтендом Beget; Django узнаёт схему через
  `SECURE_PROXY_SSL_HEADER` (X-Forwarded-Proto). Статика — WhiteNoise.
- **Telegram-бот** — на **webhook**, не long polling: постоянный фоновый процесс
  на shared-тарифе Beget убивается после закрытия SSH-сессии, а crontab из shell
  недоступен. Входящие апдейты принимает Django-эндпоинт `/tg/webhook/<secret>/`
  (`tg_bot/webhook.py`) через постоянно живой Passenger.
- **Исходящие уведомления** (`tg_bot/notifier`) — не могут крутиться в фоне,
  поэтому вызываются по расписанию из **cron панели Beget** командой
  `manage.py process_notifications` (раз в минуту).

## Каталоги на сервере

```
~/vc.iedanimk.beget.tech/
  ├── public_html/.htaccess     # конфиг Passenger (см. deploy/htaccess.public_html)
  └── vc_platform/              # git-репозиторий проекта (BEGET_PROJECT_DIR)
      ├── .venv/                # virtualenv --copies -p /usr/bin/python3.10
      ├── .env                  # прод-конфиг (НЕ в git)
      ├── tmp/restart.txt       # touch → рестарт Passenger
      └── staticfiles/          # collectstatic
```

## CI/CD (GitHub Actions)

Файл `.github/workflows/deploy.yml`. На каждый push в `main`:
Actions заходит по SSH на Beget → `git reset --hard origin/main` → обновляет venv и
зависимости → `migrate` → `collectstatic` → `touch tmp/restart.txt` → `set_webhook`.

Ключи и секреты:
- **Deploy key** (сервер → GitHub, read-only): `~/.ssh/github_deploy`, публичная часть
  добавлена в Settings → Deploy keys репозитория. Git на сервере ходит через
  `~/.ssh/config` (Host github.com → IdentityFile github_deploy).
- **CI key** (GitHub Actions → сервер): `~/.ssh/gha_ci`, публичная часть в
  `~/.ssh/authorized_keys`. Приватная — в secret `BEGET_SSH_KEY`.
- Secrets репозитория: `BEGET_HOST`, `BEGET_USER`, `BEGET_SSH_PORT`,
  `BEGET_PROJECT_DIR`, `BEGET_SSH_KEY`.

## Первичная настройка (однократно)

1. **SSL**: панель Beget → SSL-сертификаты → выпустить бесплатный Let's Encrypt для
   `vc.iedanimk.beget.tech`. Без HTTPS не работают secure-cookie, Mini App и webhook.
2. **.env на сервере** — заполнить (`DEBUG=False`, домен, `TG_WEBHOOK_SECRET` и т.д.).
3. **Passenger**: положить `deploy/htaccess.public_html` в `public_html/.htaccess`.
4. **Данные**: `migrate`, при необходимости `seed_data` + `seed_report_demo`,
   `create_manager --login … --password …`.
5. **Webhook**: `python manage.py set_webhook` (нужен HTTPS в `WEBAPP_URL`).
6. **Cron панели Beget** (раз в минуту), команда:
   ```
   cd ~/vc.iedanimk.beget.tech/vc_platform && .venv/bin/python manage.py process_notifications >> logs/cron.log 2>&1
   ```

## Полезные команды

```
python manage.py set_webhook --info      # состояние webhook
python manage.py set_webhook --delete    # снять webhook (вернуться к polling локально)
python manage.py process_notifications   # разовый проход диспетчера уведомлений
```

## Локальная разработка

Локально бот по-прежнему на long polling: `python manage.py run_bot` (или `runall`).
Webhook там не нужен — `.env` с `DEBUG=True` и `WEBAPP_URL=http://127.0.0.1:8000`.
