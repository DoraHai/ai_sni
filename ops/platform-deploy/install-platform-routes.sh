#!/usr/bin/env bash
set -euo pipefail

[[ "${1:-}" == '--enable' ]] || { echo 'usage: install-platform-routes.sh --enable' >&2; exit 2; }
[[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_module="$source_dir/modules/platform"
source_helper="$source_dir/../customer-workbench/static_release.py"
target_helper='/etc/platform-deploy/customer-workbench.py'
target_module='/etc/platform-deploy/modules/platform'
enabled='/etc/platform-deploy/enabled/platform'
backup_parent='/var/backups/platform-deploy'
dispatcher='/usr/local/sbin/platform-deploy'
reviewed_dispatcher_sha256='0330e2c14f2ff7074df140e02d56136aa2a5248ebce296d9c35007437c09937a'

[[ -x "$dispatcher" && -f "$source_module" ]] || { echo 'dispatcher or reviewed module missing' >&2; exit 1; }
[[ "$(sha256sum "$dispatcher" | cut -d' ' -f1)" == "$reviewed_dispatcher_sha256" ]] || {
  echo "Refusing unknown dispatcher: observed=$(sha256sum "$dispatcher" | cut -d' ' -f1)" >&2; exit 1;
}
bash -n "$source_module"
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$source_helper"
install -d -m 755 "$backup_parent" /etc/platform-deploy/modules /etc/platform-deploy/enabled
backup="$(mktemp -d "$backup_parent/platform-routes-install-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"
had_module=false
had_enabled=false
had_helper=false
[[ ! -e "$target_module" ]] || { cp -a "$target_module" "$backup/platform.module"; had_module=true; }
[[ ! -e "$enabled" ]] || { cp -a "$enabled" "$backup/platform.enabled"; had_enabled=true; }
[[ ! -e "$target_helper" ]] || { cp -a "$target_helper" "$backup/customer-workbench.py"; had_helper=true; }
committed=false

restore() {
  rm -f -- "$target_module" "$enabled" "${target_module}.next"
  [[ "$had_module" != true ]] || cp -a "$backup/platform.module" "$target_module"
  [[ "$had_enabled" != true ]] || cp -a "$backup/platform.enabled" "$enabled"
  rm -f -- "$target_helper"
  [[ "$had_helper" != true ]] || cp -a "$backup/customer-workbench.py" "$target_helper"
  if [[ "$had_module" == true ]]; then
    cmp -s "$backup/platform.module" "$target_module"
  else
    [[ ! -e "$target_module" ]]
  fi
  if [[ "$had_enabled" == true ]]; then
    cmp -s "$backup/platform.enabled" "$enabled"
  else
    [[ ! -e "$enabled" ]]
  fi
  if [[ "$had_helper" == true ]]; then
    cmp -s "$backup/customer-workbench.py" "$target_helper"
  else
    [[ ! -e "$target_helper" ]]
  fi
  status="$($dispatcher status)"
  if [[ "$had_enabled" == true ]]; then
    grep -Fxq 'platform=enabled' <<<"$status"
  else
    ! grep -Fxq 'platform=enabled' <<<"$status"
  fi
}

cleanup() {
  result=$?
  trap - EXIT
  rm -f -- "${target_module}.next"
  if [[ "$committed" != true ]]; then
    if ! restore; then
      echo 'platform route installer rollback failed' >&2
      result=70
    fi
  fi
  exit "$result"
}
trap cleanup EXIT

install -o root -g root -m 755 "$source_module" "${target_module}.next"
install -o root -g root -m 644 "$source_helper" "$target_helper"
mv -Tf "${target_module}.next" "$target_module"
install -o root -g root -m 644 /dev/null "$enabled"
status="$($dispatcher status)"
grep -Fxq 'platform=enabled' <<<"$status"
committed=true
printf 'backup=%s\nplatform=enabled\nmodule_sha256=%s\nhelper_sha256=%s\n' "$backup" "$(sha256sum "$target_module" | cut -d' ' -f1)" "$(sha256sum "$target_helper" | cut -d' ' -f1)"
