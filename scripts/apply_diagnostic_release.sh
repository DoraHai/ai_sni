#!/usr/bin/env bash
set -Eeuo pipefail
stamp="$1"
[[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]
root=/opt/diagnostic-service
payload="$root/releases/$stamp"
[[ -f "$payload/app/diagnostic_main.py" && -f "$payload/frontend/index.html" ]]
[[ -x "$root/.venv/bin/python" ]]
previous="$(readlink "$root/current" || true)"
previous_front="$(readlink /opt/diagnostic-center/dist || true)"
backup_front="/opt/diagnostic-center/releases/pre-independent-$stamp"
switched=0
front_changed=0
rollback() {
  if [[ "$front_changed" == 1 ]]; then
    if [[ -n "$previous_front" ]]; then
      ln -sfn "$previous_front" /opt/diagnostic-center/dist.next
      mv -Tf /opt/diagnostic-center/dist.next /opt/diagnostic-center/dist
    elif [[ -d "$backup_front" ]]; then
      mv /opt/diagnostic-center/dist "/opt/diagnostic-center/releases/failed-link-$stamp"
      mv "$backup_front" /opt/diagnostic-center/dist
    fi
  fi
  if [[ "$switched" == 1 ]]; then
    if [[ -n "$previous" ]]; then
      ln -sfn "$previous" "$root/current.next"
      mv -Tf "$root/current.next" "$root/current"
      systemctl restart diagnostic-service
    else
      systemctl stop diagnostic-service || true
    fi
  fi
  echo "Diagnostic deployment failed; previous served version restored." >&2
}
trap rollback ERR
(cd "$payload" && "$root/.venv/bin/python" -m compileall -q app/diagnostic app/diagnostic_main.py)
chown -R sem:sem "$payload"
ln -sfn "$payload" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
switched=1
systemctl restart diagnostic-service
curl -fsS --retry 20 --retry-delay 1 --retry-connrefused http://127.0.0.1:8012/health/diagnostic | grep -q '"db":"ok"'
code="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8012/api/v1/diagnostic/assets/brand/discover)"
[[ "$code" == 401 ]]
install -d /opt/diagnostic-center/releases
if [[ -d /opt/diagnostic-center/dist && ! -L /opt/diagnostic-center/dist ]]; then
  mv /opt/diagnostic-center/dist "$backup_front"
fi
front_changed=1
ln -sfn "$payload/frontend" /opt/diagnostic-center/dist.next
mv -Tf /opt/diagnostic-center/dist.next /opt/diagnostic-center/dist
systemctl enable diagnostic-service
trap - ERR
echo "Diagnostic released: $stamp"
echo "previous_backend=$previous"
echo "previous_frontend=$previous_front; directory_backup=$backup_front"
