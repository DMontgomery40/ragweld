#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/runtime_lifecycle.sh"

BACKEND_PORT="${BACKEND_PORT:-58012}"
FRONTEND_PORT="${FRONTEND_PORT:-55173}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
# Pinned, not operator-overridable: LiteLLM's generated config, the Compose
# api service, and Prometheus all target 58080 through host.docker.internal.
LOCAL_MODEL_PORT=58080
LOCAL_MODEL_VENV="${LOCAL_MODEL_VENV:-$HOME/.venv-vllm-metal}"
LOCAL_MODEL_ID="mlx-community/Qwen3.8-27B-4bit"
LOCAL_MODEL_MAX_LEN=32768
LOCAL_MODEL_MEMORY_FRACTION="0.50"

START_DOCKER=1
START_BACKEND=1
START_FRONTEND=1
START_LOCAL_MODEL=1
BACKEND_MODE="local"
WITH_OBSERVABILITY=0
WITH_FLYTE=0
NATIVE_POSTGRES=0
DRY_RUN=0
BACKEND_PID=""
FRONTEND_PID=""
LOCAL_MODEL_PID=""

usage() {
  cat <<'EOF'
Usage: ./start.sh [options]

Normal development runs Postgres/Neo4j in the `ragweld` Compose project and
runs FastAPI, Vite, and the local-model server (vllm-metal) on the host.

Options:
  --docker-backend       Run the API through Compose instead of on the host
  --with-observability   Add Prometheus, Grafana, Loki, Promtail, Tempo, and Alloy
  --with-flyte           Add the Flyte control plane (Learning Agent orchestration)
  --native-postgres      Use an already-running host Postgres instead of Compose Postgres
  --lan                  Bind Vite to 0.0.0.0
  --no-docker            Do not start Compose services
  --no-backend           Do not start FastAPI
  --no-frontend          Do not start Vite
  --no-local-model       Do not start the host vllm-metal local-model server
  --check                Print the resolved actions without starting anything
  -h, --help             Show this help

Docker/Colima ownership:
  This script never starts, stops, resets, or deletes Docker Desktop or Colima.
  Start the dedicated host profile yourself, then select its Docker context:

    colima start --profile ragweld --vm-type vz --cpu 6 --memory 16
    docker context use colima-ragweld

Local model serving:
  Generation runs on the host (Apple Silicon Metal), not in the VM. The
  `local-model` process serves mlx-community/Qwen3.8-27B-4bit as
  `ragweld-local` on 127.0.0.1:58080 from the dedicated vllm-metal venv:

    uv venv ~/.venv-vllm-metal --python 3.12
    ~/.venv-vllm-metal/bin/python -m pip install vllm-metal
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
  local_docker_ready
}

docker_context_name() {
  env -u DOCKER_HOST -u DOCKER_CONTEXT docker context show 2>/dev/null || echo "unknown"
}

resolve_docker_compose() {
  env -u DOCKER_HOST -u DOCKER_CONTEXT docker compose version >/dev/null 2>&1
}

require_free_port() {
  local label="$1"
  local port="$2"
  local listeners
  listeners="$(port_listen_pids "$port")"
  [[ -z "$listeners" ]] || die "${label} port ${port} is already in use (pid(s): ${listeners//$'\n'/,})"
}

validate_port() {
  local label="$1"
  local port="$2"
  [[ "$port" =~ ^[0-9]+$ ]] || die "${label} port must be numeric"
  (( port >= 1024 && port <= 65535 )) || die "${label} port must be between 1024 and 65535"
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

wait_for_local_model() {
  local url="http://127.0.0.1:${LOCAL_MODEL_PORT}/v1/models"
  local timeout_s="${1:-300}"
  local started body
  started="$(date +%s)"
  while true; do
    if [[ -n "$LOCAL_MODEL_PID" ]] && ! kill -0 "$LOCAL_MODEL_PID" >/dev/null 2>&1; then
      die "Local model server exited during startup; see ${RAGWELD_RUNTIME_DIR}/local-model.log"
    fi
    body="$(curl -fsS "$url" 2>/dev/null || true)"
    if [[ -n "$body" ]] && printf '%s' "$body" | grep -q '"id":"ragweld-local"'; then
      # The gate is the serving contract, not just a listener: the alias must
      # front the expected model at the expected context window.
      if ! printf '%s' "$body" | grep -q "\"root\":\"${LOCAL_MODEL_ID}\""; then
        die "Local model on ${LOCAL_MODEL_PORT} serves the wrong model (expected root ${LOCAL_MODEL_ID}): $body"
      fi
      if ! printf '%s' "$body" | grep -q "\"max_model_len\":${LOCAL_MODEL_MAX_LEN}[,}]"; then
        die "Local model on ${LOCAL_MODEL_PORT} has the wrong context window (expected max_model_len ${LOCAL_MODEL_MAX_LEN}): $body"
      fi
      log "Ready: $url (ragweld-local -> ${LOCAL_MODEL_ID}, max_model_len ${LOCAL_MODEL_MAX_LEN})"
      return 0
    fi
    if (( $(date +%s) - started >= timeout_s )); then
      die "Timed out waiting for the local model at $url; see ${RAGWELD_RUNTIME_DIR}/local-model.log"
    fi
    sleep 2
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
  if [[ -n "$FRONTEND_PID" ]]; then
    stop_owned_process_exact "frontend" "$ROOT_DIR/web" "$FRONTEND_PID"
  fi
  if [[ -n "$BACKEND_PID" ]]; then
    stop_owned_process_exact "backend" "$ROOT_DIR" "$BACKEND_PID"
  fi
  if [[ -n "$LOCAL_MODEL_PID" ]]; then
    stop_owned_process_exact "local-model" "$ROOT_DIR" "$LOCAL_MODEL_PID"
  fi
  release_lifecycle_lock
  return 0
}

on_signal() {
  exit 130
}

supervise_host_processes() {
  local record i
  while true; do
    if [[ -n "$BACKEND_PID" ]] && ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
      record="$(sed -n '1p' "$(runtime_pid_file backend)" 2>/dev/null || true)"
      if [[ "${record%%|*}" != "$BACKEND_PID" ]]; then
        i=0
        while [[ "$i" -lt 60 ]]; do
          if owned_host_records_released "$BACKEND_PID" "$FRONTEND_PID" "$LOCAL_MODEL_PID"; then
            log "Ragweld host processes stopped through the owned lifecycle."
            return 0
          fi
          sleep 0.1
          i=$((i + 1))
        done
      fi
      die "Ragweld backend exited unexpectedly"
    fi
    if [[ -n "$FRONTEND_PID" ]] && ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
      record="$(sed -n '1p' "$(runtime_pid_file frontend)" 2>/dev/null || true)"
      if [[ "${record%%|*}" != "$FRONTEND_PID" ]]; then
        i=0
        while [[ "$i" -lt 60 ]]; do
          if owned_host_records_released "$BACKEND_PID" "$FRONTEND_PID" "$LOCAL_MODEL_PID"; then
            log "Ragweld host processes stopped through the owned lifecycle."
            return 0
          fi
          sleep 0.1
          i=$((i + 1))
        done
      fi
      die "Ragweld frontend exited unexpectedly"
    fi
    if [[ -n "$LOCAL_MODEL_PID" ]] && ! kill -0 "$LOCAL_MODEL_PID" >/dev/null 2>&1; then
      record="$(sed -n '1p' "$(runtime_pid_file local-model)" 2>/dev/null || true)"
      if [[ "${record%%|*}" != "$LOCAL_MODEL_PID" ]]; then
        i=0
        while [[ "$i" -lt 60 ]]; do
          if owned_host_records_released "$BACKEND_PID" "$FRONTEND_PID" "$LOCAL_MODEL_PID"; then
            log "Ragweld host processes stopped through the owned lifecycle."
            return 0
          fi
          sleep 0.1
          i=$((i + 1))
        done
      fi
      die "Ragweld local-model server exited unexpectedly; see ${RAGWELD_RUNTIME_DIR}/local-model.log"
    fi
    sleep 1
  done
}

trap cleanup EXIT
trap on_signal INT TERM

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker-backend) BACKEND_MODE="docker" ;;
    --with-observability) WITH_OBSERVABILITY=1 ;;
    --with-flyte) WITH_FLYTE=1 ;;
    --native-postgres) NATIVE_POSTGRES=1 ;;
    --lan) FRONTEND_HOST="0.0.0.0" ;;
    --no-docker) START_DOCKER=0 ;;
    --no-backend) START_BACKEND=0 ;;
    --no-frontend) START_FRONTEND=0 ;;
    --no-local-model) START_LOCAL_MODEL=0 ;;
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

# Upstream provider credentials belong to the LiteLLM container's private
# infra/litellm.env boundary. Never pass inherited shell values into the host
# Ragweld API or Vite processes.
unset OPENROUTER_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY

if [[ -n "${COMPOSE_PROJECT_NAME:-}" && "$COMPOSE_PROJECT_NAME" != "$RAGWELD_COMPOSE_PROJECT" ]]; then
  die "COMPOSE_PROJECT_NAME must be '${RAGWELD_COMPOSE_PROJECT}', got '${COMPOSE_PROJECT_NAME}'"
fi
export COMPOSE_PROJECT_NAME="$RAGWELD_COMPOSE_PROJECT"

# Keep the host API, Vite proxy, and /api/dev/status on one resolved port.
export BACKEND_PORT FRONTEND_PORT
export VITE_API_PROXY_TARGET="http://127.0.0.1:${BACKEND_PORT}"
export LITELLM_BASE_URL="${LITELLM_BASE_URL:-http://127.0.0.1:54000/v1}"
export LITELLM_API_KEY="${LITELLM_API_KEY:-sk-ragweld-local}"
export VLLM_BASE_URL="${VLLM_BASE_URL:-http://127.0.0.1:58080/v1}"

validate_port "Backend" "$BACKEND_PORT"
validate_port "Frontend" "$FRONTEND_PORT"
validate_port "Local model" "$LOCAL_MODEL_PORT"
require_process_inspector
acquire_lifecycle_lock
if owned_pid "backend" "$ROOT_DIR" >/dev/null 2>&1 || \
   owned_pid "frontend" "$ROOT_DIR/web" >/dev/null 2>&1 || \
   owned_pid "local-model" "$ROOT_DIR" >/dev/null 2>&1; then
  die "Ragweld host processes are already owned by another launcher; run ./stop.sh first"
fi
if [[ "$START_BACKEND" == "1" && "$START_FRONTEND" == "1" && "$BACKEND_PORT" == "$FRONTEND_PORT" ]]; then
  die "Backend and frontend ports must be different"
fi
if [[ "$START_LOCAL_MODEL" == "1" ]]; then
  [[ "$BACKEND_PORT" != "$LOCAL_MODEL_PORT" ]] || die "Backend port must not collide with the local-model port ${LOCAL_MODEL_PORT}"
  [[ "$FRONTEND_PORT" != "$LOCAL_MODEL_PORT" ]] || die "Frontend port must not collide with the local-model port ${LOCAL_MODEL_PORT}"
fi
[[ "$START_BACKEND" == "1" ]] && require_free_port "Backend" "$BACKEND_PORT"
[[ "$START_FRONTEND" == "1" ]] && require_free_port "Frontend" "$FRONTEND_PORT"
[[ "$START_LOCAL_MODEL" == "1" ]] && require_free_port "Local model" "$LOCAL_MODEL_PORT"

if [[ "$NATIVE_POSTGRES" == "1" && "$DRY_RUN" == "0" ]]; then
  wait_for_native_postgres
fi

# Launch the local-model server first so the ~15 GiB weight load overlaps the
# Compose startup wait; readiness is enforced before the backend starts.
if [[ "$START_LOCAL_MODEL" == "1" ]]; then
  local_model_bin="${LOCAL_MODEL_VENV}/bin/vllm"
  if [[ ! -x "$local_model_bin" && "$DRY_RUN" == "0" ]]; then
    die "vllm-metal venv is missing at ${LOCAL_MODEL_VENV}; install it with:
  uv venv ${LOCAL_MODEL_VENV} --python 3.12
  ${LOCAL_MODEL_VENV}/bin/python -m pip install vllm-metal"
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    [[ -x "$local_model_bin" ]] || log "vllm-metal venv is missing at ${LOCAL_MODEL_VENV}; a real launch fails closed until it is installed."
    run "$local_model_bin" serve "$LOCAL_MODEL_ID" \
      --served-model-name ragweld-local \
      --host 127.0.0.1 --port "$LOCAL_MODEL_PORT" \
      --max-model-len "$LOCAL_MODEL_MAX_LEN" \
      --gpu-memory-utilization "$LOCAL_MODEL_MEMORY_FRACTION" \
      --max-num-seqs 1 \
      --default-chat-template-kwargs '{"enable_thinking": false}'
  else
    log "Local model: ${LOCAL_MODEL_ID} as ragweld-local on 127.0.0.1:${LOCAL_MODEL_PORT} (log: ${RAGWELD_RUNTIME_DIR}/local-model.log)"
    (
      cd "$ROOT_DIR"
      exec "$local_model_bin" serve "$LOCAL_MODEL_ID" \
        --served-model-name ragweld-local \
        --host 127.0.0.1 --port "$LOCAL_MODEL_PORT" \
        --max-model-len "$LOCAL_MODEL_MAX_LEN" \
        --gpu-memory-utilization "$LOCAL_MODEL_MEMORY_FRACTION" \
        --max-num-seqs 1 \
        --default-chat-template-kwargs '{"enable_thinking": false}'
    ) >"$RAGWELD_RUNTIME_DIR/local-model.log" 2>&1 &
    LOCAL_MODEL_PID="$!"
    write_owned_pid "local-model" "$LOCAL_MODEL_PID" "$LOCAL_MODEL_PORT"
  fi
fi

# The containerized API's healthcheck calls /api/ready, which requires the
# local model; in --docker-backend mode the model must be ready before Compose
# starts counting healthcheck retries.
if [[ "$BACKEND_MODE" == "docker" && "$START_LOCAL_MODEL" == "1" && "$DRY_RUN" == "0" ]]; then
  wait_for_local_model 300
fi

if [[ "$START_DOCKER" == "1" ]]; then
  have_cmd docker || die "Docker CLI is unavailable"
  resolve_docker_compose || die "Docker Compose plugin is unavailable"

  context="$(docker_context_name)"
  if docker_daemon_ready; then
    require_local_docker_context
    log "Using host-owned Docker runtime (context=${context})"
  elif [[ "$DRY_RUN" == "1" ]]; then
    log "Host-owned Docker runtime is unavailable (context=${context}); start/select it before a real launch."
  else
    die "Host-owned Docker runtime is unavailable (context=${context}). Start/select the dedicated runtime, then retry."
  fi

  compose=(env -u DOCKER_HOST -u DOCKER_CONTEXT docker compose --project-name "$RAGWELD_COMPOSE_PROJECT" -f docker-compose.yml)
  if [[ "$NATIVE_POSTGRES" == "1" ]]; then
    compose+=(-f infra/docker-compose.native-postgres.yml)
  fi
  if [[ "$WITH_OBSERVABILITY" == "1" ]]; then
    compose+=(-f infra/docker-compose.observability.yml)
  fi

  services=(postgres neo4j qdrant mlflow litellm)
  [[ "$NATIVE_POSTGRES" == "1" ]] && services=(neo4j qdrant mlflow litellm)
  if [[ "$WITH_OBSERVABILITY" == "1" ]]; then
    services+=(postgres-exporter prometheus grafana loki promtail tempo alloy)
  fi
  if [[ "$WITH_FLYTE" == "1" ]]; then
    services+=(flyte)
  fi
  if [[ "$BACKEND_MODE" == "docker" && "$START_BACKEND" == "1" ]]; then
    services+=(api)
  fi

  log "Compose project=${RAGWELD_COMPOSE_PROJECT}; services=${services[*]}"
  if [[ "$DRY_RUN" == "1" ]]; then
    run env SERVER_PORT="$BACKEND_PORT" "${compose[@]}" up -d --wait "${services[@]}"
  else
    env SERVER_PORT="$BACKEND_PORT" "${compose[@]}" up -d --wait "${services[@]}"
  fi
fi

if [[ "$START_LOCAL_MODEL" == "1" && "$DRY_RUN" == "0" ]]; then
  wait_for_local_model 300
fi

if [[ "$START_BACKEND" == "1" && "$BACKEND_MODE" == "local" ]]; then
  have_cmd uv || die "uv is unavailable"

  if [[ ! -d .venv ]]; then
    if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
      run uv sync --extra mlx
    else
      run uv sync
    fi
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    run "$ROOT_DIR/.venv/bin/uvicorn" server.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
  else
    [[ -x "$ROOT_DIR/.venv/bin/uvicorn" ]] || die "Expected .venv/bin/uvicorn after dependency setup"
    (
      cd "$ROOT_DIR"
      exec "$ROOT_DIR/.venv/bin/uvicorn" server.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
    ) &
    BACKEND_PID="$!"
    write_owned_pid "backend" "$BACKEND_PID" "$BACKEND_PORT"
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
  log "UI: http://localhost:${FRONTEND_PORT}/web/"
  if [[ "$DRY_RUN" == "1" ]]; then
    run env FRONTEND_PORT="$FRONTEND_PORT" web/node_modules/.bin/vite \
      --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort
  else
    (
      cd "$ROOT_DIR/web"
      exec ./node_modules/.bin/vite --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort
    ) &
    FRONTEND_PID="$!"
    write_owned_pid "frontend" "$FRONTEND_PID" "$FRONTEND_PORT"
    wait_for_http_ok "http://127.0.0.1:${FRONTEND_PORT}/web/" 60
  fi
fi

if [[ "$DRY_RUN" == "1" ]]; then
  log "Check complete."
elif [[ -n "$BACKEND_PID" || -n "$FRONTEND_PID" || -n "$LOCAL_MODEL_PID" ]]; then
  release_lifecycle_lock
  log "Ragweld is running. Press Ctrl-C or run ./stop.sh from another terminal."
  supervise_host_processes
else
  log "Done."
fi
