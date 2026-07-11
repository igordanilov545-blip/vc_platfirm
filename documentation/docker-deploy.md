# Развёртывание в Docker на VPS

Целевая архитектура для VPS (где вы — root), с изоляцией отказов: **упал web — бот
жив, упал бот — web жив; БД — отдельный сервис, доступный обоим.** Уходит крон
(notifier крутится внутри бота) и Passenger.

> Это НЕ для shared-хостинга Beget — там нет root/docker-демона. См. [deploy.md](deploy.md)
> про текущий shared-прод. Docker-обвязка — для переезда на VPS.

## Минимальные характеристики VPS

Рекомендуется: **2 vCPU / 2 ГБ RAM / 25–30 ГБ NVMe, Ubuntu 22.04 LTS, публичный IPv4**.
Минимум заведётся на 1 vCPU / 1 ГБ, но Postgres + `docker build` будут упираться в
память (свопа на VPS обычно нет). GPU не нужен.

## Сервисы (`docker-compose.yml`)

| Сервис | Что | Зависит от | Порты |
|---|---|---|---|
| `db` | PostgreSQL 16, том `pgdata` | — | только внутри сети |
| `web` | Django + gunicorn (3 воркера); мигрирует и собирает статику на старте | `db` (healthy) | внутри сети |
| `bot` | `manage.py run_bot` — long polling + notifier-цикл | **только `db`** (не web) | — |
| `nginx` | reverse-proxy, TLS, отдача статики | `web` | 80, 443 |

Ключевое: у всех `restart: unless-stopped`; `bot` зависит **только от `db`**, поэтому
падение `web` его не касается. Миграции применяет только `web` (одна точка).

## Первый запуск

```sh
# 1) На чистом VPS (Ubuntu 22.04/24.04), от root: установить Docker + открыть порты.
git clone git@github.com:Willi-Wonkaa/vc_platform.git && cd vc_platform
bash deploy/vps_bootstrap.sh

# 2) DNS: A-запись vc-platform.ru (и www) → IP VPS. Дождаться распространения.

# 3) Подготовить .env (не в git):
cp .env.docker.example .env && nano .env      # SECRET_KEY, DB_*, TG_*, домены

# 4) Собрать образ и поднять БД+web+bot (без HTTPS пока):
docker compose up -d --build db web bot

# 5) (если переезжаем со старого прода) перенести данные из SQLite:
#    положить старую db.sqlite3 в корень проекта, затем:
bash deploy/migrate_sqlite_to_postgres.sh

# 6) Выпустить сертификат Let's Encrypt и поднять nginx:
DOMAINS="vc-platform.ru www.vc-platform.ru" EMAIL=you@example.com bash deploy/init_letsencrypt.sh

# 7) Поднять весь стек (на случай, если что-то не запущено):
docker compose up -d --build

# 8) Создать менеджера (первый вход):
docker compose exec web python manage.py create_manager --login … --password …
```

Продление сертификата — автоматически: сервис `certbot` пытается `renew` раз в 12 часов,
nginx подхватывает новый сертификат при следующем reload/рестарте.

## Эксплуатация

```sh
docker compose ps                       # статусы + healthcheck
docker compose logs -f web              # логи веба (stdout, LOG_TO_STDOUT=1)
docker compose logs -f bot              # логи бота
docker compose restart bot              # перезапуск только бота (web не трогается)
docker compose exec web python manage.py <cmd>
```

- **Health**: `web` проверяется по `GET /healthz/` (200 если БД отвечает, иначе 503).
- **Бэкап БД**: `docker compose exec db pg_dump -U $DB_USER $DB_NAME > backup.sql`.
- **Обновление кода**: `git pull && docker compose up -d --build` (web сам применит миграции).

## CI/CD (GitHub Actions → VPS)

`.github/workflows/deploy.yml`: на push в `main` заходит по SSH на VPS →
`git reset --hard origin/main` → `docker compose up -d --build` (миграции/статику
применяет entrypoint web).

Нужны два ключа:
- **Deploy key** (VPS → GitHub, для `git clone/pull` приватного репо): пара
  `~/.ssh/github_deploy` на VPS, публичная часть добавлена в **Settings → Deploy keys**
  репозитория. `~/.ssh/config` направляет `github.com` на этот ключ.
- **CI key** (GitHub Actions → VPS): пара `~/.ssh/gha_ci` на VPS, публичная часть в
  `~/.ssh/authorized_keys`, приватная — в secret `VPS_SSH_KEY`.

Секреты репозитория: `VPS_HOST`, `VPS_USER`, `VPS_SSH_PORT`, `VPS_SSH_KEY`,
`VPS_PROJECT_DIR` (необязателен — по умолчанию `~/vc_platform`).

## Отличия от shared-прода

- Бот: **long polling** вместо webhook — не нужен `/tg/webhook/`, бот независим от web.
- Уведомления: **внутри бота** (`run_notifier_loop`), а не cron панели Beget.
- БД: **PostgreSQL** (отдельный контейнер) вместо файла SQLite.
- Веб: **gunicorn + nginx** вместо Passenger.
