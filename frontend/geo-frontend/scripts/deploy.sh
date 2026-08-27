#!/usr/bin/env bash
set -euo pipefail

unit_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
deploy_target="${DEPLOY_TARGET:-root@101.200.193.83}"
deploy_root="${GEO_FRONTEND_ROOT:-/opt/geo-frontend}"
release_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
release_dir="${deploy_root}/releases/${release_stamp}"

cd "$unit_root"
npm run build

ssh "$deploy_target" "mkdir -p '${release_dir}' '${deploy_root}/releases'"
rsync -az --delete dist/ "$deploy_target:${release_dir}/"

ssh "$deploy_target" \
  "set -euo pipefail
   test -f '${release_dir}/index.html'
   test -f '${release_dir}/dashboard.html'
   ln -sfn '${release_dir}' '${deploy_root}/current.next'
   mv -Tf '${deploy_root}/current.next' '${deploy_root}/current'"

curl -fsS "https://gsniper.snipers.com.cn/deal-sniper/geo/" >/dev/null
printf '%s\n' "GEO frontend deployed independently: ${release_stamp}"
