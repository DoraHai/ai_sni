#!/usr/bin/env bash
set -euo pipefail
[[ "$EUID" == 0 ]]
source_dir="$(cd "$(dirname "$0")" && pwd)"
[[ -x /usr/local/sbin/platform-deploy ]]
[[ -x /opt/diagnostic-service/.venv/bin/python ]]
[[ -L /opt/diagnostic-service/current && -L /opt/diagnostic-center/dist ]]
backup="/var/backups/platform-deploy/diagnostic-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup"
for name in diagnostic diagnostic_archive.py; do
  if [[ -e "/etc/platform-deploy/modules/$name" ]]; then
    cp -a "/etc/platform-deploy/modules/$name" "$backup/"
  fi
done
install -o root -g root -m 755 "$source_dir/modules/diagnostic" /etc/platform-deploy/modules/diagnostic
install -o root -g root -m 644 "$source_dir/modules/diagnostic_archive.py" /etc/platform-deploy/modules/diagnostic_archive.py
install -o root -g root -m 644 /dev/null /etc/platform-deploy/enabled/diagnostic
/usr/local/sbin/platform-deploy status
