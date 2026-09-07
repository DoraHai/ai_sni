#!/usr/bin/env bash
set -euo pipefail

case "$(uname -s)" in
  MINGW*|MSYS*)
    printf '%s\n' 'Auth deploy state machine tests require native POSIX symlinks; skipped on Windows'
    exit 0
    ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
module="$repo_root/ops/platform-deploy/modules/auth"
installer="$repo_root/ops/platform-deploy/install-auth.sh"
sandbox="$(mktemp -d)"
deploy_pid=''
cleanup_test() {
  if [[ -n "$deploy_pid" ]]; then kill "$deploy_pid" 2>/dev/null || true; fi
  rm -rf -- "$sandbox"
}
trap cleanup_test EXIT

commit='1234567890abcdef1234567890abcdef12345678'
upload_root="$sandbox/uploads"
auth_root="$sandbox/auth"
online_root="$sandbox/online"
candidate_root="$sandbox/candidate/auth-release"
stub_root="$sandbox/bin"
mkdir -p "$upload_root" "$candidate_root/frontend/assets" "$stub_root"

cat > "$candidate_root/MANIFEST" <<EOF
module=auth
commit=$commit
backend=not-included
migration=not-run
service_restart=not-run
EOF
cat > "$candidate_root/frontend/index.html" <<'EOF'
<!doctype html><script src="/auth-assets/assets/app.js"></script><link href="/auth-assets/assets/app.css" rel="stylesheet">
EOF
printf '%s\n' '/api/v1/auth/login /workspace/cockpit /workspace candidate-js' > "$candidate_root/frontend/assets/app.js"
printf '%s\n' 'candidate-css' > "$candidate_root/frontend/assets/app.css"
tar -C "$sandbox/candidate" -czf "$upload_root/auth-${commit}.tgz" auth-release
archive="$upload_root/auth-${commit}.tgz"
archive_sha256="$(sha256sum "$archive" | cut -d' ' -f1)"
archive_owner="$(stat -c '%U' "$archive")"

cat > "$stub_root/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
output=''
url=''
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    -H|--retry|--retry-delay) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  */login\?*) source_file="$AUTH_TEST_HTTP_ROOT/index.html" ;;
  */auth-assets/*) source_file="$AUTH_TEST_HTTP_ROOT/${url#*/auth-assets/}" ;;
  *) exit 22 ;;
esac
[[ -f "$source_file" ]] || exit 22
if [[ "$url" == */login\?* && "${AUTH_TEST_BLOCK_HEALTH:-0}" == '1' ]]; then
  : "${AUTH_TEST_EVENT_DIR:?}"
  : > "$AUTH_TEST_EVENT_DIR/health-entered"
  while [[ ! -f "$AUTH_TEST_EVENT_DIR/release-health" ]]; do sleep 0.05; done
fi
if [[ -n "$output" ]]; then cp "$source_file" "$output"; else cat "$source_file"; fi
EOF
chmod +x "$stub_root/curl"

run_deploy() {
  local run_archive="${1:-$archive}"
  local run_commit="${2:-$commit}"
  local run_archive_sha256="${3:-$archive_sha256}"
  PATH="$stub_root:$PATH" \
  AUTH_TEST_HTTP_ROOT="$online_root" \
  AUTH_DEPLOY_TEST_MODE=1 \
  AUTH_DEPLOY_UPLOAD_ROOT="$upload_root" \
  AUTH_DEPLOY_ARCHIVE_OWNER="$archive_owner" \
  AUTH_DEPLOY_ROOT="$auth_root" \
  AUTH_DEPLOY_STAGE_PARENT="$sandbox" \
  AUTH_DEPLOY_TEMP_PARENT="$sandbox" \
  AUTH_DEPLOY_PUBLIC_ORIGIN='https://auth.test' \
  AUTH_DEPLOY_LOCK_FILE="$sandbox/locks/auth.lock" \
    "$module" "$run_archive" "$run_commit" "$run_archive_sha256" DEPLOY_AUTH
}

prepare_online_candidate() {
  rm -rf -- "$online_root"
  mkdir -p "$online_root"
  cp -a "$candidate_root/frontend/." "$online_root/"
}

prepare_old_release() {
  local with_previous="$1"
  rm -rf -- "$auth_root"
  mkdir -p "$auth_root/releases/old/assets" "$auth_root/releases/older/assets"
  printf '%s\n' '<!doctype html><script src="/auth-assets/assets/old.js"></script>' > "$auth_root/releases/old/index.html"
  printf '%s\n' 'old-healthy' > "$auth_root/releases/old/assets/old.js"
  printf '%s\n' 'older' > "$auth_root/releases/older/index.html"
  ln -s "$auth_root/releases/old" "$auth_root/current"
  if [[ "$with_previous" == true ]]; then
    ln -s "$auth_root/releases/older" "$auth_root/previous"
  fi
}

# A first deployment is refused because there is no known-good current release.
rm -rf -- "$auth_root"
mkdir -p "$auth_root/releases"
prepare_online_candidate
if run_deploy >/dev/null 2>&1; then
  echo 'first deployment unexpectedly succeeded' >&2
  exit 1
fi
[[ ! -e "$auth_root/current" && ! -L "$auth_root/current" ]]
[[ ! -e "$auth_root/previous" && ! -L "$auth_root/previous" ]]

# A matching candidate succeeds and records the former current as previous.
prepare_old_release true
prepare_online_candidate
run_deploy >/dev/null
new_release="$(readlink "$auth_root/current")"
[[ "$new_release" == "$auth_root"/releases/*-${commit:0:12} ]]
[[ "$(readlink "$auth_root/previous")" == "$auth_root/releases/old" ]]
[[ "$(cat "$new_release/RELEASE_COMMIT")" == "$commit" ]]

# A healthy but stale online index is rejected and both prior links are restored.
prepare_old_release true
rm -rf -- "$online_root"
mkdir -p "$online_root"
cp -a "$auth_root/releases/old/." "$online_root/"
if run_deploy >/dev/null 2>&1; then
  echo 'stale healthy index unexpectedly passed candidate binding' >&2
  exit 1
fi
[[ "$(readlink "$auth_root/current")" == "$auth_root/releases/old" ]]
[[ "$(readlink "$auth_root/previous")" == "$auth_root/releases/older" ]]

# A candidate index with stale asset bytes also fails and restores both links.
prepare_old_release true
prepare_online_candidate
printf '%s\n' 'stale-but-readable-js' > "$online_root/assets/app.js"
if run_deploy >/dev/null 2>&1; then
  echo 'stale healthy asset unexpectedly passed candidate binding' >&2
  exit 1
fi
[[ "$(readlink "$auth_root/current")" == "$auth_root/releases/old" ]]
[[ "$(readlink "$auth_root/previous")" == "$auth_root/releases/older" ]]

# When previous did not exist, a failed deployment restores that absence.
prepare_old_release false
rm -rf -- "$online_root"
mkdir -p "$online_root"
cp -a "$auth_root/releases/old/." "$online_root/"
if run_deploy >/dev/null 2>&1; then
  echo 'stale index unexpectedly passed without an old previous link' >&2
  exit 1
fi
[[ "$(readlink "$auth_root/current")" == "$auth_root/releases/old" ]]
[[ ! -e "$auth_root/previous" && ! -L "$auth_root/previous" ]]

# A concurrent deployment cannot enter while the switched candidate is awaiting acceptance.
prepare_old_release true
prepare_online_candidate
event_root="$sandbox/events"
mkdir -p "$event_root"
AUTH_TEST_BLOCK_HEALTH=1 AUTH_TEST_EVENT_DIR="$event_root" run_deploy >"$sandbox/deploy-a.out" 2>&1 &
deploy_pid=$!
for _ in $(seq 1 200); do
  [[ -f "$event_root/health-entered" ]] && break
  kill -0 "$deploy_pid" 2>/dev/null || { cat "$sandbox/deploy-a.out" >&2; exit 1; }
  sleep 0.05
done
[[ -f "$event_root/health-entered" ]] || { echo 'deployment A did not reach acceptance window' >&2; exit 1; }
commit_b='abcdefabcdefabcdefabcdefabcdefabcdefabcd'
candidate_b="$sandbox/candidate-b/auth-release"
mkdir -p "$candidate_b/frontend/assets"
sed "s/commit=$commit/commit=$commit_b/" "$candidate_root/MANIFEST" > "$candidate_b/MANIFEST"
cp "$candidate_root/frontend/index.html" "$candidate_b/frontend/index.html"
printf '%s\n' '/api/v1/auth/login /workspace/cockpit /workspace unaccepted-candidate-b' > "$candidate_b/frontend/assets/app.js"
cp "$candidate_root/frontend/assets/app.css" "$candidate_b/frontend/assets/app.css"
tar -C "$sandbox/candidate-b" -czf "$upload_root/auth-${commit_b}.tgz" auth-release
archive_b="$upload_root/auth-${commit_b}.tgz"
archive_b_sha256="$(sha256sum "$archive_b" | cut -d' ' -f1)"
if run_deploy "$archive_b" "$commit_b" "$archive_b_sha256" >"$sandbox/deploy-b.out" 2>&1; then
  echo 'deployment B unexpectedly entered the locked state window' >&2
  exit 1
fi
grep -Fq 'another Auth deployment is already running' "$sandbox/deploy-b.out"
: > "$event_root/release-health"
wait "$deploy_pid"
deploy_pid=''
new_release="$(readlink "$auth_root/current")"
[[ "$new_release" == "$auth_root"/releases/*-${commit:0:12} ]]
[[ "$(readlink "$auth_root/previous")" == "$auth_root/releases/old" ]]
[[ "$(cat "$new_release/RELEASE_COMMIT")" == "$commit" ]]
if find "$auth_root/releases" -mindepth 1 -maxdepth 1 -type d -name "*-${commit_b:0:12}" | grep -q .; then
  echo 'unaccepted concurrent candidate left a release directory' >&2
  exit 1
fi

# Unknown shared dispatchers are rejected before dispatcher, module, or enabled state changes.
install_root="$sandbox/install-root"
mkdir -p "$install_root/usr/local/sbin"
cat > "$install_root/usr/local/sbin/platform-deploy" <<'EOF'
#!/usr/bin/env bash
echo unknown-platform-deploy
EOF
chmod +x "$install_root/usr/local/sbin/platform-deploy"
mkdir -p "$install_root/etc/platform-deploy/modules" "$install_root/etc/platform-deploy/enabled"
printf '%s\n' 'existing-module' > "$install_root/etc/platform-deploy/modules/auth"
printf '%s\n' 'existing-enabled' > "$install_root/etc/platform-deploy/enabled/auth"
cp -a "$install_root/usr/local/sbin/platform-deploy" "$sandbox/unknown-dispatcher.before"
cp -a "$install_root/etc/platform-deploy/modules/auth" "$sandbox/unknown-module.before"
cp -a "$install_root/etc/platform-deploy/enabled/auth" "$sandbox/unknown-enabled.before"
if AUTH_INSTALL_TEST_ROOT="$install_root" "$installer" --enable >"$sandbox/unknown-install.out" 2>&1; then
  echo 'unknown shared dispatcher was unexpectedly overwritten' >&2
  exit 1
fi
grep -Eq 'Refusing unknown platform-deploy dispatcher: observed=[0-9a-f]{64}' "$sandbox/unknown-install.out"
cmp -s "$sandbox/unknown-dispatcher.before" "$install_root/usr/local/sbin/platform-deploy"
cmp -s "$sandbox/unknown-module.before" "$install_root/etc/platform-deploy/modules/auth"
cmp -s "$sandbox/unknown-enabled.before" "$install_root/etc/platform-deploy/enabled/auth"
[[ ! -e "$install_root/var/backups/platform-deploy" ]]

# The reviewed base upgrades once; the reviewed candidate can be installed repeatedly.
git -C "$repo_root" show eaa2c93c6ddb839e2bfdf4acabb06eb2910cd01e:ops/platform-deploy/platform-deploy \
  > "$install_root/usr/local/sbin/platform-deploy"
chmod +x "$install_root/usr/local/sbin/platform-deploy"
AUTH_INSTALL_TEST_ROOT="$install_root" "$installer" --enable >/dev/null
AUTH_INSTALL_TEST_ROOT="$install_root" "$installer" --enable >/dev/null
[[ -x "$install_root/etc/platform-deploy/modules/auth" ]]
[[ -f "$install_root/etc/platform-deploy/enabled/auth" ]]
cmp -s "$module" "$install_root/etc/platform-deploy/modules/auth"
backup_count="$(find "$install_root/var/backups/platform-deploy" -mindepth 1 -maxdepth 1 -type d -name 'auth-*' | wc -l | tr -d ' ')"
[[ "$backup_count" == 2 ]]
upgrade_backup="$(find "$install_root/var/backups/platform-deploy" -mindepth 2 -maxdepth 2 -type f -name 'auth.module' -printf '%h\n')"
[[ -n "$upgrade_backup" ]]
[[ -f "$upgrade_backup/platform-deploy" ]]
[[ -f "$upgrade_backup/auth.module" ]]
[[ -f "$upgrade_backup/auth.enabled" ]]

printf '%s\n' 'Auth deploy state machine tests passed'
