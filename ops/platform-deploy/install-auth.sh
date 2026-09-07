#!/usr/bin/env bash
set -euo pipefail

[[ "${1:-}" == '--enable' ]] || { echo 'usage: install-auth.sh --enable' >&2; exit 2; }

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_root="${AUTH_INSTALL_TEST_ROOT:-}"
install_owner_args=(-o root -g root)
if [[ -z "$install_root" ]]; then
  [[ "${EUID}" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
else
  [[ "$install_root" == /* ]] || { echo 'AUTH_INSTALL_TEST_ROOT must be absolute' >&2; exit 2; }
  install_owner_args=()
fi
dispatcher_source="$source_dir/platform-deploy"
module_source="$source_dir/modules/auth"
dispatcher_target="$install_root/usr/local/sbin/platform-deploy"
config_root="$install_root/etc/platform-deploy"
module_target="$config_root/modules/auth"
enabled_target="$config_root/enabled/auth"
backup_parent="$install_root/var/backups/platform-deploy"
auth_root="$install_root/opt/auth-frontend"
reviewed_base_dispatcher_sha256='ed0c8ece980a0a9c5905f77a8c8cf2ba28d05bb5de45f38c992e12182dab549a'
reviewed_candidate_dispatcher_sha256='0330e2c14f2ff7074df140e02d56136aa2a5248ebce296d9c35007437c09937a'

[[ -f "$dispatcher_source" && -f "$module_source" ]] || { echo 'Reviewed Auth deploy sources are missing' >&2; exit 1; }
[[ -x "$dispatcher_target" ]] || { echo 'Base platform-deploy helper is missing' >&2; exit 1; }
bash -n "$dispatcher_source"
bash -n "$module_source"
source_dispatcher_sha256="$(sha256sum "$dispatcher_source" | cut -d' ' -f1)"
observed_dispatcher_sha256="$(sha256sum "$dispatcher_target" | cut -d' ' -f1)"
[[ "$source_dispatcher_sha256" == "$reviewed_candidate_dispatcher_sha256" ]] || {
  echo "Reviewed candidate dispatcher digest mismatch: observed=$source_dispatcher_sha256" >&2
  exit 1
}
case "$observed_dispatcher_sha256" in
  "$reviewed_base_dispatcher_sha256") install_dispatcher=true ;;
  "$reviewed_candidate_dispatcher_sha256") install_dispatcher=false ;;
  *)
    echo "Refusing unknown platform-deploy dispatcher: observed=$observed_dispatcher_sha256" >&2
    exit 1
    ;;
esac
install -d -m 755 "$backup_parent" "$(dirname "$dispatcher_target")" "$config_root/modules" "$config_root/enabled" "$auth_root/releases"
backup_root="$(mktemp -d "$backup_parent/auth-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"

cp -a "$dispatcher_target" "$backup_root/platform-deploy"
if [[ -e "$module_target" ]]; then cp -a "$module_target" "$backup_root/auth.module"; fi
if [[ -e "$enabled_target" ]]; then cp -a "$enabled_target" "$backup_root/auth.enabled"; fi

restore_previous() {
  if [[ -f "$backup_root/platform-deploy" ]]; then
    install "${install_owner_args[@]}" -m 755 "$backup_root/platform-deploy" "$dispatcher_target"
  fi
  if [[ -f "$backup_root/auth.module" ]]; then
    install "${install_owner_args[@]}" -m 755 "$backup_root/auth.module" "$module_target"
  else
    rm -f "$module_target"
  fi
  if [[ -f "$backup_root/auth.enabled" ]]; then
    install "${install_owner_args[@]}" -m 644 /dev/null "$enabled_target"
  else
    rm -f "$enabled_target"
  fi
}

install_succeeded=false
cleanup() {
  rm -f "$dispatcher_target.next" "$module_target.next"
  if [[ "$install_succeeded" != true ]]; then restore_previous; fi
}
trap cleanup EXIT

if [[ "$install_dispatcher" == true ]]; then
  install "${install_owner_args[@]}" -m 755 "$dispatcher_source" "$dispatcher_target.next"
fi
install "${install_owner_args[@]}" -m 755 "$module_source" "$module_target.next"
if [[ "$install_dispatcher" == true ]]; then mv -Tf "$dispatcher_target.next" "$dispatcher_target"; fi
mv -Tf "$module_target.next" "$module_target"
install "${install_owner_args[@]}" -m 644 /dev/null "$enabled_target"

status_output="$(
  PLATFORM_DEPLOY_CONFIG_ROOT="$config_root" AUTH_DEPLOY_ROOT="$auth_root" \
    "$dispatcher_target" status
)"
grep -Fxq 'auth=enabled' <<< "$status_output"
install_succeeded=true
echo "backup_root=$backup_root"
echo "dispatcher_sha256=$(sha256sum "$dispatcher_target" | cut -d' ' -f1)"
echo "auth_module_sha256=$(sha256sum "$module_target" | cut -d' ' -f1)"
