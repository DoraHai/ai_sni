#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ "${1:-}" == '--enable' ]] || { echo 'usage: install-auth.sh --enable' >&2; exit 2; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dispatcher_source="$source_dir/platform-deploy"
module_source="$source_dir/modules/auth"
dispatcher_target='/usr/local/sbin/platform-deploy'
module_target='/etc/platform-deploy/modules/auth'
enabled_target='/etc/platform-deploy/enabled/auth'
backup_parent='/var/backups/platform-deploy'

[[ -f "$dispatcher_source" && -f "$module_source" ]] || { echo 'Reviewed Auth deploy sources are missing' >&2; exit 1; }
[[ -x "$dispatcher_target" ]] || { echo 'Base platform-deploy helper is missing' >&2; exit 1; }
bash -n "$dispatcher_source"
bash -n "$module_source"
install -d -o root -g root -m 755 "$backup_parent" /etc/platform-deploy/modules /etc/platform-deploy/enabled /opt/auth-frontend/releases
backup_root="$(mktemp -d "$backup_parent/auth-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"

cp -a "$dispatcher_target" "$backup_root/platform-deploy"
if [[ -e "$module_target" ]]; then cp -a "$module_target" "$backup_root/auth.module"; fi
if [[ -e "$enabled_target" ]]; then cp -a "$enabled_target" "$backup_root/auth.enabled"; fi

restore_previous() {
  if [[ -f "$backup_root/platform-deploy" ]]; then
    install -o root -g root -m 755 "$backup_root/platform-deploy" "$dispatcher_target"
  fi
  if [[ -f "$backup_root/auth.module" ]]; then
    install -o root -g root -m 755 "$backup_root/auth.module" "$module_target"
  else
    rm -f "$module_target"
  fi
  if [[ -f "$backup_root/auth.enabled" ]]; then
    install -o root -g root -m 644 /dev/null "$enabled_target"
  else
    rm -f "$enabled_target"
  fi
}

install_succeeded=false
cleanup() {
  rm -f "$dispatcher_target.next" "$module_target.next"
  if [[ "$install_succeeded" != true ]]; then restore_previous; fi
}
trap cleanup EXIT

install -o root -g root -m 755 "$dispatcher_source" "$dispatcher_target.next"
install -o root -g root -m 755 "$module_source" "$module_target.next"
mv -Tf "$dispatcher_target.next" "$dispatcher_target"
mv -Tf "$module_target.next" "$module_target"
install -o root -g root -m 644 /dev/null "$enabled_target"

/usr/local/sbin/platform-deploy status | grep -Fxq 'auth=enabled'
install_succeeded=true
echo "backup_root=$backup_root"
echo "dispatcher_sha256=$(sha256sum "$dispatcher_target" | cut -d' ' -f1)"
echo "auth_module_sha256=$(sha256sum "$module_target" | cut -d' ' -f1)"
