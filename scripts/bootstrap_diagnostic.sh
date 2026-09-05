#!/usr/bin/env bash
# One-time provisioning on production; existing services are not restarted.
set -Eeuo pipefail
[[ "$EUID" == 0 ]]
source_root="$1"
root=/opt/diagnostic-service
[[ ! -e /etc/systemd/system/diagnostic-service.service ]] || {
  echo "Already provisioned; use independent deploy." >&2; exit 1;
}
[[ -f "$source_root/deploy/diagnostic-service.service" ]]
[[ "$(grep -c 'include /etc/nginx/snippets/geo-routes.conf;' /etc/nginx/conf.d/gsnipers.conf)" == 1 ]]
install -d -m 755 "$root/releases"
[[ ! -e "$root/.venv" ]]
cp -a /opt/sem-backend/.venv "$root/.venv"
install -o root -g sem -m 640 /opt/sem-backend/.env "$root/shared.env"
if [[ -f /opt/geo-service/.env ]]; then
  install -o root -g sem -m 640 /opt/geo-service/.env "$root/providers.env"
fi
install -o root -g sem -m 640 "$source_root/deploy/diagnostic-service.env.example" "$root/.env"
install -m 644 "$source_root/deploy/diagnostic-service.service" /etc/systemd/system/diagnostic-service.service
systemctl daemon-reload
install -m 644 "$source_root/deploy/diagnostic-api.nginx.conf" /etc/nginx/snippets/diagnostic-api.conf
backup="/etc/nginx/conf.d/gsnipers.conf.pre-diagnostic-$(date -u +%Y%m%dT%H%M%SZ)"
cp -a /etc/nginx/conf.d/gsnipers.conf "$backup"
sed -i '/include \/etc\/nginx\/snippets\/geo-routes.conf;/i\    include /etc/nginx/snippets/diagnostic-api.conf;' /etc/nginx/conf.d/gsnipers.conf
if ! nginx -t || ! systemctl reload nginx; then
  cp -a "$backup" /etc/nginx/conf.d/gsnipers.conf
  nginx -t && systemctl reload nginx
  exit 1
fi
echo "Diagnostic provisioned; nginx backup=$backup"
