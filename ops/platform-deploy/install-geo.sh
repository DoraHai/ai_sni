#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
module_source="$source_dir/modules/geo"
module_target='/etc/platform-deploy/modules/geo'
enabled_target='/etc/platform-deploy/enabled/geo'
backup_root="/var/backups/platform-deploy/geo-$(date -u +%Y%m%dT%H%M%SZ)"

[[ -x /usr/local/sbin/platform-deploy ]] || { echo 'Install the base platform-deploy helper first' >&2; exit 1; }
[[ -f "$module_source" ]] || { echo 'GEO module source is missing' >&2; exit 1; }

install -d -o root -g root -m 755 "$backup_root"
if [[ -e "$module_target" ]]; then
  cp -a "$module_target" "$backup_root/geo.module"
fi
if [[ -e "$enabled_target" ]]; then
  cp -a "$enabled_target" "$backup_root/geo.enabled"
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

echo "backup_root=$backup_root"
/usr/local/sbin/platform-deploy status
