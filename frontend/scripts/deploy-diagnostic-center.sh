#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/../.." && pwd)"
exec bash "$project_root/scripts/deploy_diagnostic.sh"
