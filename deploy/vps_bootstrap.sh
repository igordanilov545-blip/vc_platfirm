#!/usr/bin/env bash
# Первичная подготовка чистого VPS (Ubuntu 22.04/24.04) под запуск проекта в Docker.
# Ставит Docker Engine + compose-plugin из официального репозитория Docker.
# Запуск от root:  bash deploy/vps_bootstrap.sh
set -euo pipefail

echo "==> Swap-файл (на VPS с малым RAM сборка образа/Postgres иначе упирается в память)"
if ! swapon --show | grep -q swapfile && [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "   swap 2G включён"
else
  echo "   swap уже есть"
fi

echo "==> Обновляю индекс пакетов"
apt-get update -y

echo "==> Базовые зависимости"
apt-get install -y ca-certificates curl gnupg git ufw

echo "==> Ключ и репозиторий Docker"
install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

echo "==> Установка Docker Engine + compose"
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

echo "==> Файрвол: разрешаю SSH, HTTP, HTTPS"
ufw allow OpenSSH || ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable || true

echo "==> Готово."
docker --version
docker compose version
echo "Дальше: скопировать проект, заполнить .env, запустить deploy/init_letsencrypt.sh, затем docker compose up -d --build"
