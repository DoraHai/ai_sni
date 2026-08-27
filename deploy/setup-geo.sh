#!/usr/bin/env bash
# Bootstrap independent GEO unit dirs + systemd unit (CentOS/RHEL style host).
# Does not run migrations or start SEM. Idempotent mkdir/chown.
set -euo pipefail

GEO_API_ROOT="${GEO_API_ROOT:-/opt/geo-service}"
GEO_FE_ROOT="${GEO_FE_ROOT:-/opt/geo-frontend}"
GEO_LOG_DIR="${GEO_LOG_DIR:-/var/log/geo-service}"
SEM_USER="${SEM_USER:-sem}"
GEO_ENV_FILE="${GEO_ENV_FILE:-${GEO_API_ROOT}/.env}"
UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/geo-service.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (or with sudo)." >&2
  exit 1
fi

id -u "$SEM_USER" >/dev/null 2>&1 || {
  echo "User $SEM_USER not found; create SEM app user first." >&2
  exit 1
}

mkdir -p \
  "${GEO_API_ROOT}/releases" \
  "${GEO_FE_ROOT}/releases" \
  "${GEO_LOG_DIR}"

chown -R "${SEM_USER}:${SEM_USER}" "${GEO_API_ROOT}" "${GEO_FE_ROOT}" "${GEO_LOG_DIR}"

if [[ -L "$GEO_ENV_FILE" ]]; then
  echo "Refusing symlink GEO env file: $GEO_ENV_FILE" >&2
  exit 1
fi
if [[ -e "$GEO_ENV_FILE" && ! -f "$GEO_ENV_FILE" ]]; then
  echo "GEO env path is not a regular file: $GEO_ENV_FILE" >&2
  exit 1
fi
if [[ ! -e "$GEO_ENV_FILE" ]]; then
  install -o root -g "$SEM_USER" -m 0640 /dev/null "$GEO_ENV_FILE"
  echo "Created GEO-only environment file: $GEO_ENV_FILE"
else
  chown root:"$SEM_USER" "$GEO_ENV_FILE"
  chmod 0640 "$GEO_ENV_FILE"
fi

if [[ -f "$UNIT_SRC" ]]; then
  install -m 0644 "$UNIT_SRC" /etc/systemd/system/geo-service.service
  systemctl daemon-reload
  systemctl enable geo-service.service
  echo "Installed and enabled geo-service.service"
else
  echo "WARN: $UNIT_SRC missing; skip unit install" >&2
fi

cat <<EOF
GEO host bootstrap done.

Next:
  1) Keep shared DATABASE_URL + auth/crypto settings in /opt/sem-backend/.env
  2) Put GEO-only DASHSCOPE_* or DEEPSEEK_* values in ${GEO_ENV_FILE}
  3) Include deploy/geo-routes.nginx.conf inside HTTPS server block (before catch-all /api/)
  4) nginx -t && systemctl reload nginx
  5) Deploy API:  scripts/deploy_geo_api.sh
  6) Deploy FE:   cd frontend/geo-frontend && npm run deploy
  7) Accept:      curl -fsS http://127.0.0.1:8010/health/geo | grep '\"db\":\"ok\"'
EOF
