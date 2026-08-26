#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
module_source="$source_dir/modules/seo"
module_target='/etc/platform-deploy/modules/seo'
enabled_target='/etc/platform-deploy/enabled/seo'
service_source="$source_dir/../../deploy/seo-service.service"
backup_root="/var/backups/platform-deploy/seo-$(date -u +%Y%m%dT%H%M%SZ)"

[[ -x /usr/local/sbin/platform-deploy ]] || { echo 'Install the base platform-deploy helper first' >&2; exit 1; }
[[ -f "$module_source" ]] || { echo 'SEO module source is missing' >&2; exit 1; }
[[ -f "$service_source" ]] || { echo 'SEO service unit is missing' >&2; exit 1; }

install -d -o root -g root -m 755 "$backup_root"
for existing in "$module_target" "$enabled_target" /etc/systemd/system/seo-service.service; do
  if [[ -e "$existing" ]]; then
    cp -a "$existing" "$backup_root/"
  fi
done

install -d -o root -g root -m 755 \
  /etc/platform-deploy/modules \
  /etc/platform-deploy/enabled \
  /opt/seo-service/releases \
  /opt/seo-frontend/releases
install -d -o sem -g sem -m 755 /var/log/seo-service
install -o root -g root -m 755 "$module_source" "$module_target"
install -o root -g root -m 644 "$service_source" /etc/systemd/system/seo-service.service
systemctl daemon-reload

case "${1:-}" in
  --enable)
    install -o root -g root -m 644 /dev/null "$enabled_target"
    systemctl enable seo-service
    ;;
  '')
    rm -f "$enabled_target"
    ;;
  *)
    echo 'usage: install-seo.sh [--enable]' >&2
    exit 2
    ;;
esac

echo "backup_root=$backup_root"
/usr/local/sbin/platform-deploy status
