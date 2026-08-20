#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/runtime_lifecycle.sh"

if [[ "${1:-}" != "--confirm=DELETE-RAGWELD-DATA" || $# -ne 1 ]]; then
  echo "Refusing data reset. Run ./stop.sh, then pass --confirm=DELETE-RAGWELD-DATA exactly." >&2
  exit 2
fi

trap release_lifecycle_lock EXIT
require_process_inspector
acquire_lifecycle_lock

if owned_pid "frontend" "$ROOT_DIR/web" >/dev/null 2>&1 || \
   owned_pid "backend" "$ROOT_DIR" >/dev/null 2>&1; then
  echo "Refusing data reset while Ragweld host processes are running. Run ./stop.sh first." >&2
  exit 1
fi

repo_pids="$(ragweld_repo_process_pids)"
backend_listeners="$(port_listen_pids "${BACKEND_PORT:-58012}")"
frontend_listeners="$(port_listen_pids "${FRONTEND_PORT:-55173}")"
if [[ -n "$repo_pids" || -n "$backend_listeners" || -n "$frontend_listeners" ]]; then
  echo "Refusing data reset while Ragweld-like host processes or resolved-port listeners remain active." >&2
  echo "Repo process pids: ${repo_pids:-none}; port listener pids: ${backend_listeners:-none} ${frontend_listeners:-none}" >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker CLI is unavailable" >&2; exit 1; }
local_docker_ready || { echo "ERROR: local Docker runtime is unavailable" >&2; exit 1; }
require_local_docker_context
validate_reset_docker_scope

echo "Ragweld project volumes selected for deletion:"
env -u DOCKER_HOST -u DOCKER_CONTEXT docker volume ls \
  --filter "label=com.docker.compose.project=${RAGWELD_COMPOSE_PROJECT}" \
  --format '{{.Name}}'

ragweld_compose down --volumes --remove-orphans
