#!/bin/bash
# Запускать по cron каждые 5 минут: держит tg-бота (long polling) живым на
# shared-хостинге, где нет systemd/supervisor. Если процесс уже работает —
# ничего не делает; если упал — перезапускает.
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PID_FILE="$PROJECT_DIR/deploy/bot.pid"
LOG_FILE="$PROJECT_DIR/deploy/bot.log"

cd "$PROJECT_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    exit 0
fi

source "$VENV_DIR/bin/activate"
nohup python manage.py run_bot >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
