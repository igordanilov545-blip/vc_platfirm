#!/bin/sh
# Точка входа контейнеров web/bot. Единый скрипт для обоих: поведение управляется
# переменными окружения, чтобы не держать два почти одинаковых скрипта.
#
#   WAIT_FOR_DB=1        — ждать доступности Postgres перед стартом (db может ещё
#                          подниматься; и web, и bot должны дождаться БД).
#   RUN_MIGRATIONS=1     — применить миграции (обычно только у web — одна точка,
#                          чтобы web и bot не гонялись за миграции одновременно).
#   COLLECT_STATIC=1     — собрать статику (только web).
#
# После подготовки exec'аем переданную команду (gunicorn / manage.py run_bot).
set -e

# --- Ожидание Postgres (если используется) ---
if [ "${WAIT_FOR_DB:-0}" = "1" ] && [ "${DB_ENGINE:-sqlite}" = "postgres" ]; then
  echo "[entrypoint] Ожидаю Postgres ${DB_HOST:-db}:${DB_PORT:-5432} ..."
  # Пытаемся установить TCP-соединение силами самого Python (psycopg2 уже в образе),
  # чтобы не тащить отдельный клиент pg_isready.
  until python - <<'PY'
import os, sys
import psycopg2
try:
    psycopg2.connect(
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        host=os.environ.get("DB_HOST", "db"),
        port=os.environ.get("DB_PORT", "5432"),
        connect_timeout=3,
    ).close()
except Exception as e:
    sys.exit(1)
PY
  do
    echo "[entrypoint] Postgres ещё не готов, жду 2с..."
    sleep 2
  done
  echo "[entrypoint] Postgres доступен."
fi

# --- Миграции (обычно только web) ---
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] Применяю миграции..."
  python manage.py migrate --noinput
fi

# --- Сборка статики (только web) ---
if [ "${COLLECT_STATIC:-0}" = "1" ]; then
  echo "[entrypoint] collectstatic..."
  python manage.py collectstatic --noinput
fi

echo "[entrypoint] Старт: $*"
exec "$@"
