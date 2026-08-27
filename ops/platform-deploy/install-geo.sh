#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
module_source="$source_dir/modules/geo"
module_target='/etc/platform-deploy/modules/geo'
enabled_target='/etc/platform-deploy/enabled/geo'
geo_routes_source="$source_dir/../../deploy/geo-routes.nginx.conf"
geo_routes_target='/etc/nginx/snippets/geo-routes.conf'
backup_root="/var/backups/platform-deploy/geo-$(date -u +%Y%m%dT%H%M%SZ)"

[[ -x /usr/local/sbin/platform-deploy ]] || { echo 'Install the base platform-deploy helper first' >&2; exit 1; }
[[ -f "$module_source" ]] || { echo 'GEO module source is missing' >&2; exit 1; }
[[ -f "$geo_routes_source" ]] || { echo 'GEO nginx routes source is missing' >&2; exit 1; }
[[ -d "$(dirname "$geo_routes_target")" ]] || { echo 'Nginx snippets directory is missing' >&2; exit 1; }

install -d -o root -g root -m 755 "$backup_root"
if [[ -e "$module_target" ]]; then
  cp -a "$module_target" "$backup_root/geo.module"
fi
if [[ -e "$enabled_target" ]]; then
  cp -a "$enabled_target" "$backup_root/geo.enabled"
fi
if [[ -e "$geo_routes_target" ]]; then
  cp -a "$geo_routes_target" "$backup_root/geo-routes.conf"
fi

install -o root -g root -m 755 "$module_source" "$module_target"

case "${1:-}" in
  --enable)
    install -o root -g root -m 644 /dev/null "$enabled_target"
    ;;
  '')
    rm -f "$enabled_target"
    ;;
  *)
    echo 'usage: install-geo.sh [--enable]' >&2
    exit 2
    ;;
esac

restore_geo_routes() {
  if [[ -f "$backup_root/geo-routes.conf" ]]; then
    install -o root -g root -m 644 "$backup_root/geo-routes.conf" "$geo_routes_target"
  else
    rm -f "$geo_routes_target"
  fi
}

install -o root -g root -m 644 "$geo_routes_source" "$geo_routes_target"
if ! nginx -t; then
  restore_geo_routes
  nginx -t || true
  echo 'GEO nginx routes failed validation; previous routes restored' >&2
  exit 1
fi
if ! systemctl reload nginx; then
  restore_geo_routes
  nginx -t && systemctl reload nginx || true
  echo 'GEO nginx reload failed; previous routes restored' >&2
  exit 1
fi

echo "backup_root=$backup_root"
/usr/local/sbin/platform-deploy status
