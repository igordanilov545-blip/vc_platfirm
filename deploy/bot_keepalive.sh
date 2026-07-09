#!/bin/bash
# Запускать по cron каждые 5 минут: держит tg-бота (long polling) живым на
# shared-хостинге Beget, где нет systemd/supervisor. Если процесс уже работает —
# ничего не делает; если упал — перезапускает.
#
# Важно для Beget: процесс запускается через `setsid ... < /dev/null` и `exec`,
# чтобы полностью отвязать его от управляющего терминала SSH-сессии. Без этого
# бот получает SIGTERM при закрытии сессии деплоя и мгновенно умирает.
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PID_FILE="$PROJECT_DIR/deploy/bot.pid"
LOG_FILE="$PROJECT_DIR/deploy/bot.log"

cd "$PROJECT_DIR"

# Уже жив? Проверяем и pid-файл, и фактический процесс по имени команды
# (на случай, если pid-файл потерялся, но бот работает — не плодим второй polling).
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    exit 0
fi
if pgrep -u "$(id -un)" -f 'manage.py run_bot' >/dev/null 2>&1; then
    pgrep -u "$(id -un)" -f 'manage.py run_bot' | head -1 > "$PID_FILE"
    exit 0
fi

# Запуск полностью отвязанного процесса. exec заменяет промежуточный bash на
# python, поэтому записанный pid — это и есть pid бота.
setsid bash -c "cd '$PROJECT_DIR' && source '$VENV_DIR/bin/activate' && exec python manage.py run_bot" \
    >> "$LOG_FILE" 2>&1 < /dev/null &
echo $! > "$PID_FILE"

sleep 3
if pgrep -u "$(id -un)" -f 'manage.py run_bot' >/dev/null 2>&1; then
    pgrep -u "$(id -un)" -f 'manage.py run_bot' | head -1 > "$PID_FILE"
    echo "bot started, pid=$(cat "$PID_FILE")"
else
    echo "bot FAILED to start, see $LOG_FILE" >&2
    exit 1
fi
