#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
seo_source="$source_dir/modules/seo"
frontend_source="$source_dir/modules/seo-frontend"
seo_target='/etc/platform-deploy/modules/seo'
frontend_target='/etc/platform-deploy/modules/seo-frontend'
enabled_target='/etc/platform-deploy/enabled/seo'
backup_root="/var/backups/platform-deploy/seo-frontend-$(date -u +%Y%m%dT%H%M%SZ)"

[[ -x /usr/local/sbin/platform-deploy ]] || { echo 'Base platform-deploy helper is missing' >&2; exit 1; }
[[ -x "$seo_target" ]] || { echo 'Existing SEO deploy entry is missing' >&2; exit 1; }
[[ -f "$enabled_target" ]] || { echo 'Existing SEO deploy entry is locked' >&2; exit 1; }
[[ -f "$seo_source" && -f "$frontend_source" ]] || { echo 'Reviewed SEO frontend module sources are missing' >&2; exit 1; }

install -d -o root -g root -m 755 "$backup_root"
cp -a "$seo_target" "$backup_root/seo"
if [[ -e "$frontend_target" ]]; then
  cp -a "$frontend_target" "$backup_root/seo-frontend"
fi

install -o root -g root -m 755 "$frontend_source" "$frontend_target"
install -o root -g root -m 755 "$seo_source" "$seo_target"

echo "backup_root=$backup_root"
sha256sum "$seo_target" "$frontend_target"
/usr/local/sbin/platform-deploy status
