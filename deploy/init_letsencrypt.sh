#!/usr/bin/env bash
# Первичный выпуск сертификата Let's Encrypt для vc-platform.ru (webroot через nginx).
# Идея (стандартный bootstrap certbot под docker-compose):
#   1) кладём ВРЕМЕННЫЙ self-signed сертификат по пути live/<домен>, чтобы nginx
#      вообще смог запуститься с 443-блоком;
#   2) поднимаем nginx;
#   3) certbot по http-01 (webroot) получает НАСТОЯЩИЙ сертификат, заменяя временный;
#   4) перезагружаем nginx.
#
# Запуск от root из каталога проекта (где docker-compose.yml), ПОСЛЕ заполнения .env:
#   DOMAINS="vc-platform.ru www.vc-platform.ru" EMAIL=you@example.com bash deploy/init_letsencrypt.sh
set -euo pipefail

DOMAINS="${DOMAINS:-vc-platform.ru www.vc-platform.ru}"
EMAIL="${EMAIL:-}"
PRIMARY="$(echo "$DOMAINS" | awk '{print $1}')"
STAGING="${STAGING:-0}"   # STAGING=1 — тестовый CA Let's Encrypt (без лимитов), для отладки

if [ -z "$EMAIL" ]; then
  echo "Укажите EMAIL=... (для уведомлений Let's Encrypt)."; exit 1
fi

compose() { docker compose "$@"; }

echo "### Временный self-signed сертификат для $PRIMARY (чтобы nginx стартовал)"
compose run --rm --entrypoint "\
  sh -c 'mkdir -p /etc/letsencrypt/live/$PRIMARY && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout /etc/letsencrypt/live/$PRIMARY/privkey.pem \
    -out /etc/letsencrypt/live/$PRIMARY/fullchain.pem \
    -subj /CN=localhost'" certbot

echo "### Поднимаю nginx с временным сертификатом"
compose up -d nginx

echo "### Удаляю временный сертификат перед запросом настоящего"
compose run --rm --entrypoint "\
  sh -c 'rm -rf /etc/letsencrypt/live/$PRIMARY /etc/letsencrypt/archive/$PRIMARY /etc/letsencrypt/renewal/$PRIMARY.conf'" certbot

# Собираем -d флаги по всем доменам.
DOMAIN_ARGS=""
for d in $DOMAINS; do DOMAIN_ARGS="$DOMAIN_ARGS -d $d"; done
STAGING_ARG=""
[ "$STAGING" = "1" ] && STAGING_ARG="--staging"

echo "### Запрашиваю настоящий сертификат Let's Encrypt"
compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $STAGING_ARG --email $EMAIL $DOMAIN_ARGS \
    --rsa-key-size 2048 --agree-tos --no-eff-email --force-renewal" certbot

echo "### Перезагружаю nginx с настоящим сертификатом"
compose exec nginx nginx -s reload || compose restart nginx

echo "### Готово. Сертификат для: $DOMAINS"
