#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/runtime_lifecycle.sh"
trap release_lifecycle_lock EXIT
require_process_inspector
acquire_lifecycle_lock

STOP_DOCKER=1
if [[ "${1:-}" == "--no-docker" ]]; then
  STOP_DOCKER=0
elif [[ $# -gt 0 ]]; then
  echo "Usage: ./stop.sh [--no-docker]" >&2
  exit 2
fi

stop_owned_process "frontend" "$ROOT_DIR/web"
stop_owned_process "backend" "$ROOT_DIR"
stop_owned_process "local-model" "$ROOT_DIR"

if [[ "$STOP_DOCKER" == "1" ]]; then
  if command -v docker >/dev/null 2>&1 && local_docker_ready; then
    require_local_docker_context
    ragweld_compose stop
  else
    echo "Ragweld Docker runtime is unavailable; host-process stop is complete."
  fi
fi
