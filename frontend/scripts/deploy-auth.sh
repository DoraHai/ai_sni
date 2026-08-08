#!/usr/bin/env bash
set -euo pipefail

frontend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
deploy_target="${DEPLOY_TARGET:-root@101.200.193.83}"
deploy_root="${AUTH_FRONTEND_ROOT:-/opt/auth-frontend}"
release_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
release_dir="${deploy_root}/releases/${release_stamp}"
lock_dir="${deploy_root}/.deploy-lock"

cd "$frontend_root"
npm run build:auth
npm run verify:auth-build

if [[ "${VERIFY_ONLY:-0}" == "1" ]]; then
  printf '%s\n' "Auth frontend build verified; deployment skipped (VERIFY_ONLY=1)"
  exit 0
fi

if ! ssh "$deploy_target" "mkdir -p '$deploy_root' && mkdir '$lock_dir'"; then
  printf '%s\n' "Another auth frontend deployment is active: $lock_dir" >&2
  exit 1
fi

release_lock() {
  ssh "$deploy_target" "rmdir '$lock_dir'" >/dev/null 2>&1 || true
}
trap release_lock EXIT

previous_target="$(
  ssh "$deploy_target" "readlink '${deploy_root}/current' 2>/dev/null || true"
)"

ssh "$deploy_target" "mkdir -p '$release_dir' '${deploy_root}/releases'"
rsync -az --delete dist-auth/ "$deploy_target:${release_dir}/"

ssh "$deploy_target" \
  "set -euo pipefail
   test -s '${release_dir}/index.html'
   grep -q '/auth-assets/' '${release_dir}/index.html'
   grep -Raq 'AI 获客指挥台' '${release_dir}/assets'
   grep -Raq '/api/v1/auth/login' '${release_dir}/assets'
   grep -Raq '图形验证码' '${release_dir}/assets'
   ln -sfn '${release_dir}' '${deploy_root}/current.next'
   mv -Tf '${deploy_root}/current.next' '${deploy_root}/current'
   chown -R nginx:nginx '${release_dir}'
   test \"\$(readlink '${deploy_root}/current')\" = '${release_dir}'"

printf '%s\n' "Auth frontend deployed atomically: ${release_stamp}"
printf '%s\n' "Active release: ${release_dir}"
if [[ -n "$previous_target" ]]; then
  printf '%s\n' "Previous release: ${previous_target}"
fi
