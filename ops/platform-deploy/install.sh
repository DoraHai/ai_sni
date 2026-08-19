#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backup_root="/var/backups/platform-deploy/setup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_root"

for file in /usr/local/sbin/platform-deploy /etc/sudoers.d/platform-deploy; do
  if [[ -e "$file" ]]; then
    cp -a "$file" "$backup_root/"
  fi
done

install -d -o root -g root -m 755 /etc/platform-deploy/modules /etc/platform-deploy/enabled
install -d -o platform-deploy -g platform-deploy -m 700 /home/platform-deploy/uploads
install -o root -g root -m 755 "$source_dir/platform-deploy" /usr/local/sbin/platform-deploy
install -o root -g root -m 440 "$source_dir/platform-deploy.sudoers" /etc/sudoers.d/platform-deploy
visudo -cf /etc/sudoers.d/platform-deploy

echo "backup_root=$backup_root"
/usr/local/sbin/platform-deploy status
