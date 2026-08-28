#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly ROOT_DIR

die() {
  echo "ERROR: $*" >&2
  exit 1
}

main() {
  cd "$ROOT_DIR"
  [[ -x "$ROOT_DIR/stop.sh" ]] || die "stop.sh is missing or not executable"
  command -v docker >/dev/null 2>&1 || die "docker CLI is required"

  ./stop.sh --no-docker
  docker compose --project-name ragweld \
    -f docker-compose.yml \
    -f infra/docker-compose.observability.yml \
    -f deploy/proxmox/docker-compose.yml \
    stop
}

main "$@"
