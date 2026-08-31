#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
module_source="$source_dir/modules/sem"
module_target='/etc/platform-deploy/modules/sem'
module_next="${module_target}.next"
enabled_target='/etc/platform-deploy/enabled/sem'
backup_parent='/var/backups/platform-deploy'

[[ -x /usr/local/sbin/platform-deploy ]] || { echo 'Install the base platform-deploy helper first' >&2; exit 1; }
[[ -f "$module_source" ]] || { echo 'SEM module source is missing' >&2; exit 1; }
bash -n "$module_source"

case "${1:-}" in
  --enable|--locked) ;;
  *) echo 'usage: install-sem.sh --enable|--locked' >&2; exit 2 ;;
esac

install -d -o root -g root -m 755 \
  "$backup_parent" \
  /etc/platform-deploy/modules \
  /etc/platform-deploy/enabled \
  /opt/sem-backend/releases
backup_root="$(mktemp -d "$backup_parent/sem-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"

if [[ -e "$module_target" ]]; then
  cp -a "$module_target" "$backup_root/sem.module"
fi
if [[ -e "$enabled_target" ]]; then
  cp -a "$enabled_target" "$backup_root/sem.enabled"
fi

restore_previous() {
  if [[ -f "$backup_root/sem.module" ]]; then
    install -o root -g root -m 755 "$backup_root/sem.module" "$module_target"
  else
    rm -f "$module_target"
  fi
  if [[ -f "$backup_root/sem.enabled" ]]; then
    install -o root -g root -m 644 /dev/null "$enabled_target"
  else
    rm -f "$enabled_target"
  fi
}

install_succeeded=false
cleanup() {
  rm -f "$module_next"
  if [[ "$install_succeeded" != true ]]; then
    restore_previous
  fi
}
trap cleanup EXIT
install -o root -g root -m 755 "$module_source" "$module_next"
mv -Tf "$module_next" "$module_target"
cmp -s "$module_source" "$module_target" || { echo 'Installed SEM module differs from source' >&2; exit 1; }
[[ "$(stat -c '%U:%G:%a' "$module_target")" == 'root:root:755' ]] || { echo 'Installed SEM module ownership or mode is invalid' >&2; exit 1; }

if [[ "$1" == '--enable' ]]; then
  install -o root -g root -m 644 /dev/null "$enabled_target"
else
  rm -f "$enabled_target"
fi

if ! /usr/local/sbin/platform-deploy status; then
  echo 'SEM module installation failed validation; previous module restored' >&2
  exit 1
fi

install_succeeded=true
echo "backup_root=$backup_root"
echo "module_sha256=$(sha256sum "$module_target" | cut -d' ' -f1)"
