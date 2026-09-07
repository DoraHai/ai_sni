#!/usr/bin/env bash
set -euo pipefail

frontend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$frontend_root"
npm run build:auth
npm run verify:auth-build

if [[ "${VERIFY_ONLY:-0}" != "1" ]]; then
  printf '%s\n' 'Direct Auth SSH deployment is disabled. Merge a reviewed commit into codex/production-auth.' >&2
  exit 64
fi

printf '%s\n' 'Auth frontend build verified; deployment skipped (VERIFY_ONLY=1)'
