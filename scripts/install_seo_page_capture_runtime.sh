#!/usr/bin/env bash
# Install optional SEO screenshot runtime on the SEO server. Run as root.
# Usage: [--service-user USER] [--python VENV_PYTHON] [--storage-dir ABS_PATH] [--dry-run]
# Environment overrides: SEO_PAGE_CAPTURE_SERVICE_USER, SEO_PAGE_CAPTURE_PYTHON,
# SEO_PAGE_CAPTURE_STORAGE_DIR. This script does not enable SEO_PAGE_CAPTURE_ENABLED.
set -euo pipefail

service_user="${SEO_PAGE_CAPTURE_SERVICE_USER:-sem}"
python_bin="${SEO_PAGE_CAPTURE_PYTHON:-/opt/sem-backend/.venv/bin/python}"
storage_dir="${SEO_PAGE_CAPTURE_STORAGE_DIR:-/var/lib/seo-service/page-captures}"
dry_run=false

while (($#)); do
  case "$1" in
    --service-user|--python|--storage-dir)
      (($# >= 2)) || { echo "Missing value for $1" >&2; exit 2; }
      case "$1" in
        --service-user) service_user="$2" ;;
        --python) python_bin="$2" ;;
        --storage-dir) storage_dir="$2" ;;
      esac
      shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ "$storage_dir" == /* ]] || { echo 'Storage directory must be absolute' >&2; exit 2; }
storage_dir="$(realpath -m -- "$storage_dir")"
case "$storage_dir" in
  /|/opt/seo-service|/opt/seo-service/*|/opt/sem-backend|/opt/sem-backend/*|/opt/seo-frontend|/opt/seo-frontend/*|*/releases|*/releases/*)
    echo 'Storage directory must be outside release directories and /' >&2; exit 2 ;;
esac
[[ "$python_bin" == /* ]] || { echo 'Venv Python path must be absolute' >&2; exit 2; }
if [[ "$dry_run" != true ]]; then
  ((EUID == 0)) || { echo 'Run as root' >&2; exit 1; }
  [[ -x "$python_bin" ]] || { echo "Missing SEO venv Python: $python_bin" >&2; exit 1; }
  id "$service_user" >/dev/null || { echo "Unknown service user: $service_user" >&2; exit 1; }
fi

run() {
  if [[ "$dry_run" == true ]]; then
    printf 'dry-run:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if [[ "$dry_run" == true ]]; then
  echo 'dry-run: check fonts-noto-cjk with dpkg-query; install with apt-get if absent'
elif ! dpkg-query -W -f='${Status}' fonts-noto-cjk 2>/dev/null | grep -q 'install ok installed'; then
  run apt-get update
  run apt-get install -y fonts-noto-cjk
fi
# System libraries need root; the browser itself goes into the service user's
# own Playwright cache (~/.cache/ms-playwright), which is where the service
# (systemd User=) looks for it. Installing it as root would put it in /root.
run "$python_bin" -m playwright install-deps chromium
service_home="$(getent passwd "$service_user" | cut -d: -f6 || true)"
if [[ -z "$service_home" ]]; then
  [[ "$dry_run" == true ]] || { echo "No home directory for $service_user" >&2; exit 1; }
  service_home='<service user home>'
fi
# runuser keeps the caller's HOME, so set it explicitly to the service user's home.
run runuser -u "$service_user" -- env HOME="$service_home" "$python_bin" -m playwright install chromium
if [[ "$dry_run" == true ]]; then
  run install -d -o "$service_user" -g '<service primary group>' -m 750 -- "$storage_dir"
else
  service_group="$(id -gn "$service_user")"
  run install -d -o "$service_user" -g "$service_group" -m 750 -- "$storage_dir"
fi
