#!/usr/bin/env bash
set -euo pipefail

deploy_target="${DEPLOY_TARGET:-root@101.200.193.83}"
deploy_root="${DEPLOY_ROOT:-/opt/diagnostic-center}"
release_stamp="$(date -u +%Y%m%dT%H%M%SZ)"

npm run build:diagnostic-center

ssh "$deploy_target" \
  "mkdir -p '$deploy_root/releases/$release_stamp' '$deploy_root/dist' &&
   tar -czf '$deploy_root/releases/$release_stamp/dist.tgz' -C '$deploy_root' dist"

rsync -az --delete dist-diagnostic-center/ "$deploy_target:$deploy_root/dist/"

printf '%s\n' "Diagnostic center deployed: $release_stamp"
