#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8012}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ragweld}"

START_DOCKER=1
START_BACKEND=1
START_FRONTEND=1
BACKEND_MODE="local"
WITH_OBSERVABILITY=0
NATIVE_POSTGRES=0
DRY_RUN=0
BACKEND_PID=""

usage() {
  cat <<'EOF'
Usage: ./start.sh [options]

Normal development runs Postgres/Neo4j in the `ragweld` Compose project and
runs FastAPI plus Vite on the host.

Options:
  --docker-backend       Run the API through Compose instead of on the host
  --with-observability   Add Prometheus, Grafana, Loki, Promtail, Tempo, and Alloy
  --native-postgres      Use an already-running host Postgres instead of Compose Postgres
  --lan                  Bind Vite to 0.0.0.0
  --no-docker            Do not start Compose services
  --no-backend           Do not start FastAPI
  --no-frontend          Do not start Vite
  --check                Print the resolved actions without starting anything
  -h, --help             Show this help

Docker/Colima ownership:
  This script never starts, stops, resets, or deletes Docker Desktop or Colima.
  Start the dedicated host profile yourself, then select its Docker context:

    colima start --profile ragweld --vm-type vz --cpu 4 --memory 8
    docker context use colima-ragweld
EOF
}

log() {
  echo "[start.sh] $*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

docker_daemon_ready() {
  docker info >/dev/null 2>&1
}

docker_context_name() {
  docker context show 2>/dev/null || echo "unknown"
}

resolve_docker_compose() {
  docker compose version >/dev/null 2>&1
}

port_listen_pids() {
  local port="$1"
  if have_cmd lsof; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null || true
  fi
}

wait_for_http_ok() {
  local url="$1"
  local timeout_s="${2:-60}"
  local started
  started="$(date +%s)"
  while ! curl -fsS "$url" >/dev/null 2>&1; do
    if (( $(date +%s) - started >= timeout_s )); then
      die "Timed out waiting for $url"
    fi
    sleep 1
  done
  log "Ready: $url"
}

wait_for_backend_ready() {
  local url="http://127.0.0.1:${BACKEND_PORT}/api/ready"
  local timeout_s="${1:-120}"
  local started
  started="$(date +%s)"
  while true; do
    local body
    body="$(curl -fsS "$url" 2>/dev/null || true)"
    if [[ "$body" == *'"ready":true'* || "$body" == *'"ready": true'* ]]; then
      log "Ready: $url"
      return 0
    fi
    if (( $(date +%s) - started >= timeout_s )); then
      [[ -n "$body" ]] && echo "$body" >&2
      die "Timed out waiting for backend readiness at $url"
    fi
    sleep 1
  done
}

wait_for_native_postgres() {
  have_cmd pg_isready || die "pg_isready is required for --native-postgres"
  local host="${POSTGRES_HOST:-127.0.0.1}"
  local port="${POSTGRES_PORT:-5432}"
  local user="${POSTGRES_USER:-postgres}"
  [[ "$host" == "host.docker.internal" ]] && host="127.0.0.1"
  PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_isready -h "$host" -p "$port" -U "$user" >/dev/null \
    || die "Host Postgres is not ready at ${host}:${port}"
}

cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    log "Stopping backend pid=$BACKEND_PID"
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker-backend) BACKEND_MODE="docker" ;;
    --with-observability) WITH_OBSERVABILITY=1 ;;
    --native-postgres) NATIVE_POSTGRES=1 ;;
    --lan) FRONTEND_HOST="0.0.0.0" ;;
    --no-docker) START_DOCKER=0 ;;
    --no-backend) START_BACKEND=0 ;;
    --no-frontend) START_FRONTEND=0 ;;
    --check) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "Unknown option: $1" ;;
  esac
  shift
done

if [[ ! -f .env && -f .env.example ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    log "Would copy .env.example to .env"
  else
    cp .env.example .env
    log "Created .env from .env.example; add secrets only when a provider needs them."
  fi
fi

if [[ -f .env ]]; then
  log "Loading environment from .env"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Keep the host API, Vite proxy, and /api/dev/status on one resolved port.
export BACKEND_PORT FRONTEND_PORT
export VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://127.0.0.1:${BACKEND_PORT}}"

if [[ "$NATIVE_POSTGRES" == "1" && "$DRY_RUN" == "0" ]]; then
  wait_for_native_postgres
fi

if [[ "$START_DOCKER" == "1" ]]; then
  have_cmd docker || die "Docker CLI is unavailable"
  resolve_docker_compose || die "Docker Compose plugin is unavailable"

  context="$(docker_context_name)"
  if docker_daemon_ready; then
    log "Using host-owned Docker runtime (context=${context})"
  elif [[ "$DRY_RUN" == "1" ]]; then
    log "Host-owned Docker runtime is unavailable (context=${context}); start/select it before a real launch."
  else
    die "Host-owned Docker runtime is unavailable (context=${context}). Start/select the dedicated runtime, then retry."
  fi

  compose=(docker compose --project-name "$COMPOSE_PROJECT_NAME" -f docker-compose.yml)
  if [[ "$NATIVE_POSTGRES" == "1" ]]; then
    compose+=(-f infra/docker-compose.native-postgres.yml)
  fi
  if [[ "$WITH_OBSERVABILITY" == "1" ]]; then
    compose+=(-f infra/docker-compose.observability.yml)
  fi

  services=(postgres neo4j)
  [[ "$NATIVE_POSTGRES" == "1" ]] && services=(neo4j)
  if [[ "$WITH_OBSERVABILITY" == "1" ]]; then
    services+=(postgres-exporter prometheus grafana loki promtail tempo alloy)
  fi
  if [[ "$BACKEND_MODE" == "docker" && "$START_BACKEND" == "1" ]]; then
    services+=(api)
  fi

  log "Compose project=${COMPOSE_PROJECT_NAME}; services=${services[*]}"
  if [[ "$DRY_RUN" == "1" ]]; then
    run env SERVER_PORT="$BACKEND_PORT" "${compose[@]}" up -d --wait "${services[@]}"
  else
    env SERVER_PORT="$BACKEND_PORT" "${compose[@]}" up -d --wait "${services[@]}"
  fi
fi

if [[ "$START_BACKEND" == "1" && "$BACKEND_MODE" == "local" ]]; then
  have_cmd uv || die "uv is unavailable"
  existing_pids="$(port_listen_pids "$BACKEND_PORT")"
  [[ -n "$existing_pids" ]] && die "Backend port ${BACKEND_PORT} is already in use"

  if [[ ! -d .venv ]]; then
    if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
      run uv sync --extra mlx
    else
      run uv sync
    fi
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    run uv run uvicorn server.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload
  else
    uv run uvicorn server.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload &
    BACKEND_PID="$!"
    wait_for_http_ok "http://127.0.0.1:${BACKEND_PORT}/api/health" 60
    wait_for_backend_ready 120
  fi
elif [[ "$START_BACKEND" == "1" && "$BACKEND_MODE" == "docker" && "$DRY_RUN" == "0" ]]; then
  wait_for_http_ok "http://127.0.0.1:${BACKEND_PORT}/api/health" 90
  wait_for_backend_ready 120
fi

if [[ "$START_FRONTEND" == "1" ]]; then
  have_cmd npm || die "npm is unavailable"
  [[ -d web ]] || die "web directory is missing"
  [[ -d web/node_modules || "$DRY_RUN" == "1" ]] || npm --prefix web install
  log "UI: http://localhost:${FRONTEND_PORT}/web"
  run npm --prefix web run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
else
  log "Done."
fi
