#!/usr/bin/env bash
# Read-only facts for the server owner. Does not read .env, change routes or deploy.
set -euo pipefail
printf 'checked_at='; date -u +%FT%TZ
if [[ -x /usr/local/sbin/platform-deploy ]]; then
  /usr/local/sbin/platform-deploy status
  sha256sum /usr/local/sbin/platform-deploy
fi
for file in /etc/platform-deploy/modules/platform /etc/nginx/conf.d/gsnipers.conf; do
  if [[ -f "$file" ]]; then sha256sum "$file"; else printf 'missing=%s\n' "$file"; fi
done
if [[ -f /etc/nginx/conf.d/gsnipers.conf ]]; then
  # Only route declarations and include paths, never connection strings or credentials.
  awk '/^[[:space:]]*(include|location)[[:space:]]/ {print}' /etc/nginx/conf.d/gsnipers.conf
fi
for root in /opt/sem-frontend /opt/auth-frontend /opt/customer-workbench; do
  printf 'release_root=%s\n' "$root"
  for link in current previous; do
    printf '%s=' "$link"; readlink "$root/$link" || true
  done
done
if [[ -f /etc/nginx/conf.d/gsnipers.conf ]]; then nginx -t; fi
printf 'readiness=read-only-complete\n'
