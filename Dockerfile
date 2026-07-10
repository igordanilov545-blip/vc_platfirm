# Единый образ для web (gunicorn) и bot (long polling) — оба запускаются из одного
# кода, различается только команда (см. docker-compose.yml). Multi-stage не используем:
# образ и так небольшой, а общий слой зависимостей кэшируется между web и bot.
FROM python:3.10-slim AS base

# Системные зависимости:
#  - WeasyPrint (PDF-отчёты в web) требует cairo/pango/gdk-pixbuf и шрифты;
#  - libpq5 — рантайм для psycopg2 (Postgres);
#  - curl — для healthcheck'ов в compose.
# Ставим одним слоем и чистим кэш apt, чтобы образ был компактным.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        libpq5 \
        fonts-dejavu-core \
        fonts-liberation \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала только requirements — слой с зависимостями пересобирается лишь при их изменении.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Затем код приложения.
COPY . .

# Непривилегированный пользователь — не гоняем контейнеры от root.
# chmod на entrypoint: executable-бит может теряться при копировании/архивации кода,
# поэтому выставляем его явно в образе, а не полагаемся на права из git.
RUN chmod +x /app/deploy/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/logs /app/staticfiles \
    && chown -R appuser:appuser /app
USER appuser

# Точка входа: ждёт БД, применяет миграции/сборку статики для web (управляется через
# переменные окружения RUN_MIGRATIONS / COLLECT_STATIC), затем exec'ает переданную команду.
ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]

# По умолчанию — web (gunicorn). Бот переопределяет command в docker-compose.yml.
CMD ["gunicorn", "myproject.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
