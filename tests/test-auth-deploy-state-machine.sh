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
trap 'rm -rf -- "$sandbox"' EXIT

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
if [[ -n "$output" ]]; then cp "$source_file" "$output"; else cat "$source_file"; fi
EOF
chmod +x "$stub_root/curl"

run_deploy() {
  PATH="$stub_root:$PATH" \
  AUTH_TEST_HTTP_ROOT="$online_root" \
  AUTH_DEPLOY_TEST_MODE=1 \
  AUTH_DEPLOY_UPLOAD_ROOT="$upload_root" \
  AUTH_DEPLOY_ARCHIVE_OWNER="$archive_owner" \
  AUTH_DEPLOY_ROOT="$auth_root" \
  AUTH_DEPLOY_STAGE_PARENT="$sandbox" \
  AUTH_DEPLOY_TEMP_PARENT="$sandbox" \
  AUTH_DEPLOY_PUBLIC_ORIGIN='https://auth.test' \
    "$module" "$archive" "$commit" "$archive_sha256" DEPLOY_AUTH
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

# Installing the restricted dispatcher/module twice stays enabled and creates a backup each time.
install_root="$sandbox/install-root"
mkdir -p "$install_root/usr/local/sbin"
cat > "$install_root/usr/local/sbin/platform-deploy" <<'EOF'
#!/usr/bin/env bash
echo legacy-platform-deploy
EOF
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
