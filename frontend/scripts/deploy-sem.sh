#!/usr/bin/env bash
set -euo pipefail

frontend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(git -C "$frontend_root" rev-parse --show-toplevel)"
deploy_target="${DEPLOY_TARGET:-sem-deploy@101.200.193.83}"
deploy_root="${SEM_FRONTEND_ROOT:-/opt/sem-frontend}"
release_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
git_commit="$(git -C "$repo_root" rev-parse HEAD)"
git_short="$(git -C "$repo_root" rev-parse --short=12 HEAD)"
release_dir="${deploy_root}/releases/${release_stamp}-${git_short}"
lock_dir="${deploy_root}/.deploy-lock"
ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=yes)

cd "$frontend_root"
if ! git -C "$repo_root" diff --quiet \
  || ! git -C "$repo_root" diff --cached --quiet \
  || [[ -n "$(git -C "$repo_root" ls-files --others --exclude-standard)" ]]; then
  printf '%s\n' "Refusing to deploy from a dirty Git worktree" >&2
  exit 1
fi
npm run build
npm run verify:sem-build
printf '%s\n' "$git_commit" > dist/DEPLOYED_GIT_COMMIT

if [[ "${VERIFY_ONLY:-0}" == "1" ]]; then
  printf '%s\n' "SEM frontend build verified; deployment skipped (VERIFY_ONLY=1)"
  exit 0
fi

if ! ssh "${ssh_options[@]}" "$deploy_target" "mkdir -p '$deploy_root' && mkdir '$lock_dir'"; then
  printf '%s\n' "Another SEM frontend deployment is active: $lock_dir" >&2
  exit 1
fi

release_lock() {
  ssh "${ssh_options[@]}" "$deploy_target" "rmdir '$lock_dir'" >/dev/null 2>&1 || true
}
trap release_lock EXIT

previous_target="$(
  ssh "${ssh_options[@]}" "$deploy_target" "readlink '${deploy_root}/current' 2>/dev/null || true"
)"

ssh "${ssh_options[@]}" "$deploy_target" "mkdir -p '$release_dir' '${deploy_root}/releases'"
rsync \
  -rltz \
  --delete \
  --chmod=D0755,F0644 \
  -e "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes" \
  dist/ \
  "$deploy_target:${release_dir}/"

ssh "${ssh_options[@]}" "$deploy_target" \
  "set -euo pipefail
   test -s '${release_dir}/index.html'
   test \"\$(cat '${release_dir}/DEPLOYED_GIT_COMMIT')\" = '${git_commit}'
   grep -Raq '授权新客户账号' '${release_dir}/assets'
   grep -Raq '/api/v1/oauth/baidu/authorize' '${release_dir}/assets'
   if grep -Raq '图形验证码' '${release_dir}/assets'; then
     echo 'Login application detected in SEM release' >&2
     exit 1
   fi
   if grep -Raq '服务商接入准备中' '${release_dir}/assets'; then
     echo 'Obsolete OAuth placeholder detected in uploaded release' >&2
     exit 1
   fi
   if find '${release_dir}' -type d ! -perm -0005 -print -quit | grep -q .; then
     echo 'SEM release contains a directory nginx cannot read' >&2
     exit 1
   fi
   if find '${release_dir}' -type f ! -perm -0004 -print -quit | grep -q .; then
     echo 'SEM release contains a file nginx cannot read' >&2
     exit 1
   fi
   ln -sfn '${release_dir}' '${deploy_root}/current.next'
   mv -Tf '${deploy_root}/current.next' '${deploy_root}/current'
   test \"\$(readlink '${deploy_root}/current')\" = '${release_dir}'"

printf '%s\n' "SEM frontend deployed atomically: ${release_stamp} (${git_commit})"
printf '%s\n' "Active release: ${release_dir}"
if [[ -n "$previous_target" ]]; then
  printf '%s\n' "Previous release: ${previous_target}"
fi
