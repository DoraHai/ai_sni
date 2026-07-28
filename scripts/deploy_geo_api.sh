#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
deploy_target="${DEPLOY_TARGET:-root@101.200.193.83}"
deploy_root="${GEO_API_ROOT:-/opt/geo-service}"
release_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
release_dir="${deploy_root}/releases/${release_stamp}"

ssh "$deploy_target" "mkdir -p '${release_dir}/app' '${deploy_root}/releases'"
rsync -az --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$project_root/app/" "$deploy_target:${release_dir}/app/"
rsync -az \
  "$project_root/requirements.txt" \
  "$project_root/alembic.ini" \
  "$deploy_target:${release_dir}/"
rsync -az --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$project_root/migrations/" "$deploy_target:${release_dir}/migrations/"

previous_target="$(
  ssh "$deploy_target" \
    "readlink '${deploy_root}/current' 2>/dev/null || true"
)"

ssh "$deploy_target" \
  "set -euo pipefail
   ln -sfn '${release_dir}' '${deploy_root}/current.next'
   mv -Tf '${deploy_root}/current.next' '${deploy_root}/current'
   chown -R sem:sem '${release_dir}'
   systemctl restart geo-service"

if ! ssh "$deploy_target" \
  "curl -fsS --retry 15 --retry-delay 1 --retry-connrefused http://127.0.0.1:8010/health/geo"; then
  if [[ -n "$previous_target" ]]; then
    ssh "$deploy_target" \
      "ln -sfn '${previous_target}' '${deploy_root}/current.next' &&
       mv -Tf '${deploy_root}/current.next' '${deploy_root}/current' &&
       systemctl restart geo-service"
  fi
  printf '%s\n' "GEO API health check failed; previous release restored." >&2
  exit 1
fi

printf '%s\n' "GEO API deployed independently: ${release_stamp}"
