#!/usr/bin/env bash
set -euo pipefail

deploy_target="${DEPLOY_TARGET:-root@101.200.193.83}"
deploy_root="${DEPLOY_ROOT:-/opt/growth-sniper}"
release_stamp="$(date -u +%Y%m%dT%H%M%SZ)"

npm run build:website

ssh "$deploy_target" \
  "mkdir -p '$deploy_root/releases/$release_stamp' '$deploy_root/dist' &&
   tar -czf '$deploy_root/releases/$release_stamp/dist.tgz' -C '$deploy_root' dist"

rsync -az --delete dist-website/ "$deploy_target:$deploy_root/dist/"

printf '%s\n' "Website deployed: $release_stamp"
