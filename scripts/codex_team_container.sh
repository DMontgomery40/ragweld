#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${CODEX_TEAM_IMAGE:-codex-agent-teams:latest}"
BUILD=0
SOURCE_DIR="${HOME}/.codex/agent-teams/lib/team_bus"

usage() {
  cat <<'EOF'
Run Codex Agent Teams in Docker.

Usage:
  scripts/codex_team_container.sh [--build] [--source DIR] <codex-team args>

Examples:
  scripts/codex_team_container.sh --build list
  scripts/codex_team_container.sh --source ~/.codex/agent-teams/lib/team_bus list
  scripts/codex_team_container.sh create incident --lead-name orchestrator --lead-agent-id lead-1
  scripts/codex_team_container.sh relay incident --once
EOF
}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

if [[ "${1:-}" == "--build" ]]; then
  BUILD=1
  shift
fi

if [[ "${1:-}" == "--source" ]]; then
  SOURCE_DIR="$2"
  shift 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for containerized mode" >&2
  exit 1
fi

if [[ ! -d "${SOURCE_DIR}" ]]; then
  if [[ -d "${REPO_ROOT}/server/team_bus" ]]; then
    SOURCE_DIR="${REPO_ROOT}/server/team_bus"
  else
    echo "team_bus source not found: ${SOURCE_DIR}" >&2
    echo "Provide --source DIR or run ./scripts/install_codex_agent_teams.sh first." >&2
    exit 1
  fi
fi

if [[ ${BUILD} -eq 1 ]] || ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  BUILD_CTX="$(mktemp -d)"
  trap 'rm -rf "${BUILD_CTX}"' EXIT
  cp -R "${SOURCE_DIR}" "${BUILD_CTX}/team_bus"
  cat > "${BUILD_CTX}/Dockerfile" <<'EOF'
FROM python:3.12-slim
WORKDIR /opt/codex-agent-teams
RUN pip install --no-cache-dir "pydantic>=2.5,<3"
COPY team_bus /opt/codex-agent-teams/team_bus
ENV PYTHONPATH=/opt/codex-agent-teams
ENTRYPOINT ["python", "-m", "team_bus.cli"]
EOF
  docker build \
    -f "${BUILD_CTX}/Dockerfile" \
    -t "${IMAGE}" \
    "${BUILD_CTX}"
fi

TTY_FLAGS=(-i)
if [[ -t 0 && -t 1 ]]; then
  TTY_FLAGS=(-it)
fi

docker run --rm "${TTY_FLAGS[@]}" \
  -v "${HOME}/.codex/teams:/root/.codex/teams" \
  -v "${HOME}/.claude:/root/.claude:ro" \
  "${IMAGE}" "$@"
