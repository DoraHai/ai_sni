#!/usr/bin/env bash
set -euo pipefail

fail() { printf 'platform-route-publish: %s\n' "$*" >&2; exit 65; }

archive="${1:-}"
release_sha="${2:-}"
archive_sha256="${3:-}"
branch_ref='refs/heads/codex/production-sem'
deploy_host="${DEPLOY_HOST:-}"
deploy_port="${DEPLOY_PORT:-}"
deploy_user="${DEPLOY_USER:-}"
run_id="${GITHUB_RUN_ID:-manual}"
run_attempt="${GITHUB_RUN_ATTEMPT:-1}"

[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'release SHA must be full lowercase hex'
[[ "$archive_sha256" =~ ^[0-9a-f]{64}$ ]] || fail 'archive digest is invalid'
[[ -f "$archive" && ! -L "$archive" ]] || fail 'release archive is missing or is a symlink'
[[ -n "$deploy_host" && -n "$deploy_port" && -n "$deploy_user" ]] || fail 'deployment identity is incomplete'
[[ "$deploy_port" =~ ^[0-9]+$ ]] || fail 'deployment port is invalid'
[[ "$run_id" =~ ^[0-9]+$ && "$run_attempt" =~ ^[0-9]+$ ]] || fail 'workflow run identity is invalid'
[[ "$(sha256sum "$archive" | cut -d' ' -f1)" == "$archive_sha256" ]] || fail 'local archive digest mismatch'

authoritative_head() {
  git ls-remote origin "$branch_ref" | cut -f1
}

require_current_head() {
  local observed
  observed="$(authoritative_head)" || return 1
  [[ "$observed" == "$release_sha" ]] || {
    printf 'platform-route-publish: stale release: expected=%s observed=%s\n' "$release_sha" "${observed:-missing}" >&2
    return 1
  }
}

ssh_options=(-i ~/.ssh/platform-deploy -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes)
remote="/home/platform-deploy/uploads/platform-routes-${release_sha}.tgz"
remote_part="${remote}.part-${run_id}-${run_attempt}"

# A queued newer push cancels this run. This authoritative check also prevents
# an already-stale run from making even a temporary remote upload.
require_current_head || fail 'branch head changed before upload'
scp "${ssh_options[@]}" -P "$deploy_port" "$archive" "$deploy_user@$deploy_host:$remote_part"

# Re-read the authoritative branch before entering the trusted remote boundary.
# The server module performs its own independent live check while holding the
# deploy lock; runner-supplied values are never accepted as authorization.
require_current_head || fail 'branch head changed after upload; refusing activation'
ssh "${ssh_options[@]}" -p "$deploy_port" "$deploy_user@$deploy_host" \
  "sudo -n /usr/local/sbin/platform-deploy apply platform '$remote_part' '$release_sha' '$archive_sha256' DEPLOY_PLATFORM_ROUTES"
