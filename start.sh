#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8012}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"

START_DOCKER=1
START_BACKEND=1
START_FRONTEND=1

BACKEND_MODE="local" # local|docker
WITH_OBSERVABILITY=0
DRY_RUN=0

BACKEND_PID=""

usage() {
  cat <<'EOF'
Usage:
  ./start.sh [options]

Starts:
  - Docker services (postgres + neo4j)
  - Backend API on http://127.0.0.1:8012 (FastAPI)
  - Frontend UI on http://localhost:5173/web (Vite)

Options:
  --docker-backend         Run backend via Docker Compose (maps host :8012 -> container :8000)
  --with-observability     Also start prometheus + grafana (optional)
  --lan                    Bind frontend dev server to 0.0.0.0 (accessible on your LAN)
  --no-docker              Skip Docker services
  --no-backend             Skip backend
  --no-frontend            Skip frontend
  --check                  Print what would run, then exit
  -h, --help               Show help

Environment overrides:
  BACKEND_PORT=8012        Backend host port (defaults to 8012)
  FRONTEND_PORT=5173       Frontend dev server port (defaults to 5173)
  FRONTEND_HOST=127.0.0.1  Frontend dev server host (defaults to 127.0.0.1; set 0.0.0.0 for LAN)

Notes:
  - The frontend code + Vite proxy expect the backend on port 8012 during dev.
  - If .env is missing, this script copies .env.example -> .env (you still need to add keys).
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo "[start.sh] $*"
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

port_listen_pids() {
  local port="$1"
  if have_cmd lsof; then
    # One PID per line (may be multiple listeners in edge cases)
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null || true
    return 0
  fi
  # Best-effort when lsof is unavailable: can't detect listeners.
  return 0
}

DOCKER_COMPOSE=()
resolve_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
    return 0
  fi
  if have_cmd docker-compose; then
    DOCKER_COMPOSE=(docker-compose)
    return 0
  fi
  return 1
}

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ $*"
    return 0
  fi
  "$@"
}

wait_for_container_healthy() {
  local cname="$1"
  local timeout_s="${2:-120}"
  local start_s
  start_s="$(date +%s)"

  log "Waiting for $cname to become healthy (timeout ${timeout_s}s)..."
  while true; do
    local status=""
    status="$(docker inspect -f '{{.State.Health.Status}}' "$cname" 2>/dev/null || true)"
    if [[ "$status" == "healthy" ]]; then
      log "$cname is healthy."
      return 0
    fi
    if [[ "$status" == "unhealthy" ]]; then
      die "$cname is unhealthy. Check logs: docker logs $cname"
    fi
    if [[ -z "$status" ]]; then
      die "Could not inspect $cname (is Docker running? did the container start?)"
    fi

    local now_s
    now_s="$(date +%s)"
    if (( now_s - start_s >= timeout_s )); then
      die "Timed out waiting for $cname health (current status: $status)"
    fi
    sleep 2
  done
}

wait_for_http_ok() {
  local url="$1"
  local timeout_s="${2:-60}"
  local start_s
  start_s="$(date +%s)"

  log "Waiting for HTTP OK: $url (timeout ${timeout_s}s)..."
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "OK: $url"
      return 0
    fi
    local now_s
    now_s="$(date +%s)"
    if (( now_s - start_s >= timeout_s )); then
      die "Timed out waiting for: $url"
    fi
    sleep 1
  done
}

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    if kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
      log "Stopping backend (pid=$BACKEND_PID)..."
      kill "$BACKEND_PID" >/dev/null 2>&1 || true
    fi
  fi
}
trap cleanup EXIT INT TERM

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker-backend)
      BACKEND_MODE="docker"
      ;;
    --with-observability)
      WITH_OBSERVABILITY=1
      ;;
    --lan)
      FRONTEND_HOST="0.0.0.0"
      ;;
    --no-docker)
      START_DOCKER=0
      ;;
    --no-backend)
      START_BACKEND=0
      ;;
    --no-frontend)
      START_FRONTEND=0
      ;;
    --check)
      DRY_RUN=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "Unknown option: $1"
      ;;
  esac
  shift
done

if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    log ".env not found; copying .env.example -> .env"
    run cp ".env.example" ".env"
    log "Reminder: edit .env with your API keys if you want embeddings/LLM calls."
  else
    log ".env not found and .env.example missing; continuing."
  fi
fi

# Load .env for local backend so Neo4j/Postgres credentials are available.
# (Docker Compose reads .env automatically, but local uvicorn does not.)
if [[ -f ".env" ]]; then
  log "Loading environment from .env"
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

wait_for_backend_ready() {
  local url="http://127.0.0.1:${BACKEND_PORT}/api/ready"
  local timeout_s="${1:-90}"
  local start_s
  start_s="$(date +%s)"

  log "Waiting for backend readiness: $url (timeout ${timeout_s}s)..."
  while true; do
    local body=""
    body="$(curl -fsS "$url" 2>/dev/null || true)"
    if [[ -n "$body" ]] && echo "$body" | grep -Eq '"ready"[[:space:]]*:[[:space:]]*true'; then
      log "Ready: $url"
      return 0
    fi
    local now_s
    now_s="$(date +%s)"
    if (( now_s - start_s >= timeout_s )); then
      echo "$body" >&2
      die "Timed out waiting for backend readiness: $url"
    fi
    sleep 1
  done
}

if [[ "$START_DOCKER" == "1" ]]; then
  resolve_docker_compose || die "Docker Compose not found. Install Docker Desktop."

  services=(postgres neo4j)
  if [[ "$WITH_OBSERVABILITY" == "1" ]]; then
    services+=(prometheus grafana loki promtail)
  fi
  if [[ "$BACKEND_MODE" == "docker" && "$START_BACKEND" == "1" ]]; then
    services+=(api)
  fi

  log "Starting Docker services: ${services[*]}"
  if [[ "$BACKEND_MODE" == "docker" && "$START_BACKEND" == "1" ]]; then
    run env SERVER_PORT="$BACKEND_PORT" "${DOCKER_COMPOSE[@]}" up -d "${services[@]}"
  else
    run "${DOCKER_COMPOSE[@]}" up -d "${services[@]}"
  fi

  if [[ "$DRY_RUN" == "0" ]]; then
    wait_for_container_healthy "tribrid-postgres" 120
    wait_for_container_healthy "tribrid-neo4j" 180
  fi
fi

if [[ "$START_BACKEND" == "1" && "$BACKEND_MODE" == "local" ]]; then
  have_cmd uv || die "uv not found. Install uv, then re-run (see README prerequisites)."
  log "Ensuring Python deps are installed (uv sync)..."
  # Run once per machine; safe/no-op if already synced.
  run uv sync

  log "Starting backend (uvicorn) on port $BACKEND_PORT..."
  existing_pids="$(port_listen_pids "$BACKEND_PORT")"
  if [[ -n "${existing_pids:-}" ]]; then
    log "Backend port $BACKEND_PORT is already in use."
    log "Listener PID(s):"
    echo "$existing_pids" | sed 's/^/[start.sh]   - /'
    die "Port $BACKEND_PORT is already in use. Stop the existing process, or run ./start.sh --no-backend if you want to reuse an already-running backend, or set BACKEND_PORT."
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    run uv run uvicorn server.main:app --reload --port "$BACKEND_PORT"
  else
    uv run uvicorn server.main:app --reload --port "$BACKEND_PORT" &
    BACKEND_PID="$!"
    # If uvicorn fails fast (e.g., bind error), fail loudly instead of
    # accidentally proceeding with a stale process on the port.
    sleep 0.2
    if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
      die "Backend failed to start (uvicorn exited immediately). Scroll up for the error."
    fi
    wait_for_http_ok "http://127.0.0.1:${BACKEND_PORT}/api/health" 60
    wait_for_backend_ready 120

    log "MCP (Streamable HTTP): http://localhost:${BACKEND_PORT}/mcp/"
  fi
elif [[ "$START_BACKEND" == "1" && "$BACKEND_MODE" == "docker" ]]; then
  if [[ "$DRY_RUN" == "0" ]]; then
    wait_for_http_ok "http://127.0.0.1:${BACKEND_PORT}/api/health" 90
    wait_for_backend_ready 120

    log "MCP (Streamable HTTP): http://localhost:${BACKEND_PORT}/mcp/"
  fi
fi

if [[ "$START_FRONTEND" == "1" ]]; then
  have_cmd npm || die "npm not found. Install Node.js 18+, then re-run."
  if [[ ! -d "web" ]]; then
    die "web/ directory not found."
  fi

  if [[ "$DRY_RUN" == "0" && ! -d "web/node_modules" ]]; then
    log "web/node_modules missing; running npm install..."
    run npm --prefix web install
  fi

  log "Starting frontend (Vite) on ${FRONTEND_HOST}:${FRONTEND_PORT}..."
  log "UI: http://localhost:${FRONTEND_PORT}/web"
  if [[ "$FRONTEND_HOST" == "0.0.0.0" ]]; then
    log "UI (LAN): http://<your-ip>:${FRONTEND_PORT}/web"
  fi
  # Bind explicitly to IPv4 loopback so tests and scripts that use 127.0.0.1 work
  # even when "localhost" resolves to ::1 first.
  run npm --prefix web run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
else
  log "Done. (Nothing left to run in foreground.)"
fi
