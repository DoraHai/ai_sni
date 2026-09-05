#!/usr/bin/env bash
# Diagnostic-only deploy: never invoke the GEO/SEM/SEO release helpers.
set -Eeuo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
target="root@101.200.193.83"
if [[ -n "${DEPLOY_TARGET:-}" ]]; then target="$DEPLOY_TARGET"; fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
release="/opt/diagnostic-service/releases/$stamp"
cd "$project_root/frontend"
npm run build:diagnostic-center
cd "$project_root"
ssh "$target" "test -x /opt/diagnostic-service/.venv/bin/python && test -f /etc/nginx/snippets/diagnostic-api.conf && test ! -e '$release' && mkdir -p '$release/app' '$release/frontend'"
rsync -az --exclude '__pycache__' --exclude '*.pyc' app/ "$target:$release/app/"
rsync -az frontend/dist-diagnostic-center/ "$target:$release/frontend/"
rsync -az scripts/apply_diagnostic_release.sh "$target:$release/apply.sh"
rsync -az requirements.txt "$target:$release/"
ssh "$target" "bash '$release/apply.sh' '$stamp'"
