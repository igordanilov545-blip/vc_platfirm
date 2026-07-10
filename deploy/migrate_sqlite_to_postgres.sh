#!/bin/sh
# Перенос данных из SQLite в Postgres через ORM Django (dumpdata → loaddata).
# ORM-уровень выбран сознательно: он корректно переносит кастомную модель User,
# внешние ключи и natural keys, не завися от различий типов SQLite/Postgres.
#
# Запуск (на VPS, из каталога проекта, где лежит docker-compose.yml):
#   1) Скопировать старую db.sqlite3 в корень проекта.
#   2) sh deploy/migrate_sqlite_to_postgres.sh
#
# Скрипт:
#   - дампит данные из SQLite во временный JSON (внутри одноразового контейнера
#     с DB_ENGINE=sqlite),
#   - поднимает db (Postgres), применяет миграции,
#   - загружает JSON в Postgres.
set -e

DUMP=data_dump.json

echo "==> 1/4 Поднимаю Postgres (db)"
docker compose up -d db
sleep 3

echo "==> 2/4 Дамп данных из SQLite (contenttypes/permissions исключаем — их пересоздаст migrate)"
# Одноразовый прогон образа web с переопределённым DB_ENGINE=sqlite: тот же код,
# но читает локальный файл db.sqlite3, смонтированный в контейнер.
docker compose run --rm \
  -e DB_ENGINE=sqlite \
  -e WAIT_FOR_DB=0 -e RUN_MIGRATIONS=0 -e COLLECT_STATIC=0 \
  -v "$(pwd)/db.sqlite3:/app/db.sqlite3" \
  web \
  python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    --exclude admin.logentry --exclude sessions.session \
    --indent 2 --output "/app/$DUMP"

echo "==> 3/4 Миграции в Postgres"
docker compose run --rm \
  -e WAIT_FOR_DB=1 -e RUN_MIGRATIONS=1 -e COLLECT_STATIC=0 \
  web \
  python manage.py migrate --noinput

echo "==> 4/4 Загрузка данных в Postgres"
docker compose run --rm \
  -e WAIT_FOR_DB=1 -e RUN_MIGRATIONS=0 -e COLLECT_STATIC=0 \
  web \
  python manage.py loaddata "/app/$DUMP"

echo "==> Готово. Проверьте данные, затем поднимите весь стек: docker compose up -d"
