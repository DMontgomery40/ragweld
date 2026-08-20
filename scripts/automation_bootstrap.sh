#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

artifact_ts="$(date -u +%Y%m%dT%H%M%SZ)"
artifact_dir="$ROOT_DIR/output/automation/bootstrap/$artifact_ts"
latest_path="$ROOT_DIR/output/automation/bootstrap/latest.json"
runtime_dir="$ROOT_DIR/output/automation/runtime"
mkdir -p "$artifact_dir" "$runtime_dir"

CORPUS_ID="${CORPUS_ID:-ragweld-acceptance}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
PREFERRED_BACKEND_PORT="${BACKEND_PORT:-58012}"
BACKEND_PORT_CANDIDATE_TEXT="${BACKEND_PORT_CANDIDATES:-8013 8014 8015}"
BACKEND_PORT_SEARCH_WINDOW="${BACKEND_PORT_SEARCH_WINDOW:-5}"
PREFERRED_UI_PORT="${UI_PORT:-55173}"
UI_PORT_CANDIDATE_TEXT="${UI_PORT_CANDIDATES:-4173 4174 4175 5174}"
UI_PORT_SEARCH_WINDOW="${UI_PORT_SEARCH_WINDOW:-5}"
IFS=' ' read -r -a BACKEND_PORT_CANDIDATES <<<"$BACKEND_PORT_CANDIDATE_TEXT"
IFS=' ' read -r -a UI_PORT_CANDIDATES <<<"$UI_PORT_CANDIDATE_TEXT"

status="passed"
failure_reason=""
resolved_ui_root=""
resolved_ui_base=""
resolved_api_base="${API_BASE:-}"
corpus_ready=0
corpus_action="skipped"
corpus_path=""
ui_listener_pid=""
ui_listener_command=""
api_listener_pid=""
api_listener_command=""
git_health_error=""
GIT_HEALTH_SCRIPT="$ROOT_DIR/scripts/git_worktree_health.py"

log() {
  echo "[automation_bootstrap] $*" >&2
}

check_git_health() {
  local output=""
  if [ ! -f "$GIT_HEALTH_SCRIPT" ]; then
    git_health_error="missing git health script: $GIT_HEALTH_SCRIPT"
    return 1
  fi

  if ! output="$(python3 "$GIT_HEALTH_SCRIPT" --strict --current-branch-only --allow-missing-upstream 2>&1)"; then
    git_health_error="$output"
    return 1
  fi

  git_health_error=""
  return 0
}

listener_pid() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true
}

listener_command() {
  local port="$1"
  local pid
  pid="$(listener_pid "$port")"
  if [ -z "$pid" ]; then
    return 0
  fi
  ps -p "$pid" -o command= 2>/dev/null || true
}

stop_listener() {
  local port="$1"
  local pid
  pid="$(listener_pid "$port")"
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    local deadline=$((SECONDS + 10))
    while [ "$SECONDS" -lt "$deadline" ]; do
      if port_free "$port"; then
        return 0
      fi
      sleep 1
    done
  fi
  port_free "$port"
}

port_from_url() {
  local url="$1"
  python3 - "$url" <<'PY'
from urllib.parse import urlparse
import sys

parsed = urlparse(sys.argv[1])
print(parsed.port or "")
PY
}

api_root_from_base() {
  local api_base="$1"
  printf '%s\n' "${api_base%/api}"
}

port_free() {
  local port="$1"
  [ -z "$(listener_pid "$port")" ]
}

highest_port() {
  local max_port="$1"
  shift || true
  local port
  for port in "$@"; do
    if [ "$port" -gt "$max_port" ]; then
      max_port="$port"
    fi
  done
  printf '%s\n' "$max_port"
}

is_current_worktree_listener() {
  local port="$1"
  local cmd
  cmd="$(listener_command "$port")"
  [ -n "$cmd" ] && [[ "$cmd" == *"$ROOT_DIR"* ]]
}

probe_code() {
  local url="$1"
  local out_path="$2"
  local code
  if code="$(curl -sS -o "$out_path" -w "%{http_code}" "$url" 2>/dev/null)"; then
    printf '%s\n' "$code"
    return 0
  fi
  : >"$out_path"
  printf '000\n'
}

ui_code_ok() {
  local code="$1"
  [ "$code" != "000" ] && [ "$code" != "404" ]
}

probe_ui_root() {
  local root="$1"
  local out_prefix="$2"
  local web_url="${root}/web/rag?subtab=synthetic&corpus=${CORPUS_ID}"
  local root_url="${root}/rag?subtab=synthetic&corpus=${CORPUS_ID}"
  local web_code
  local root_code
  web_code="$(probe_code "$web_url" "${out_prefix}_web.html")"
  root_code="$(probe_code "$root_url" "${out_prefix}_root.html")"
  if ui_code_ok "$web_code" || ui_code_ok "$root_code"; then
    return 0
  fi
  return 1
}

wait_for_ui_root() {
  local root="$1"
  local out_prefix="$2"
  local deadline=$((SECONDS + 90))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if probe_ui_root "$root" "$out_prefix"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_api() {
  local api_base="$1"
  local deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    local health_code
    health_code="$(curl -sS -o /dev/null -w "%{http_code}" "${api_base}/health" || echo "000")"
    if [ "$health_code" = "200" ]; then
      local ready_body
      ready_body="$(curl -sS "${api_base}/ready" 2>/dev/null || true)"
      if [[ "$ready_body" == *'"ready":true'* ]]; then
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

start_frontend_on_port() {
  local port="$1"
  local api_root="$2"
  local log_path="$runtime_dir/frontend-${port}.log"
  local session_name="ragweld-ui-proof-ui-${port}"
  if [ ! -d "$ROOT_DIR/web/node_modules" ]; then
    log "Installing frontend dependencies"
    npm --prefix web install >/dev/null
  fi
  log "Starting frontend on ${FRONTEND_HOST}:${port}"
  if command -v tmux >/dev/null 2>&1; then
    tmux kill-session -t "$session_name" 2>/dev/null || true
    tmux new-session -d -s "$session_name" \
      "cd '$ROOT_DIR' && env VITE_API_PROXY_TARGET='$api_root' npm --prefix web run dev -- --host '$FRONTEND_HOST' --port '$port' > '$log_path' 2>&1"
  else
    nohup env VITE_API_PROXY_TARGET="$api_root" npm --prefix web run dev -- --host "$FRONTEND_HOST" --port "$port" >"$log_path" 2>&1 &
  fi
  wait_for_ui_root "http://${FRONTEND_HOST}:${port}" "$artifact_dir/ui_probe_started_${port}"
}

dev_status_backend_url() {
  local root="$1"
  local status_path="$artifact_dir/dev_status_$(printf '%s' "$root" | tr ':/' '__').json"
  local code
  code="$(curl -sS -o "$status_path" -w "%{http_code}" "${root}/api/dev/status" 2>/dev/null || echo "000")"
  if [ "$code" != "200" ]; then
    return 1
  fi
  python3 - "$status_path" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], "r", encoding="utf-8"))
print(str(data.get("backend_url") or "").strip())
PY
}

ui_matches_resolved_api() {
  local root="$1"
  if [ -z "${resolved_api_base:-}" ]; then
    return 0
  fi
  local expected
  local actual
  expected="$(printf '%s\n' "$resolved_api_base")"
  actual="$(dev_status_backend_url "$root" || true)"
  [ -n "$actual" ] && [ "$actual" = "$expected" ]
}

ensure_ui_root() {
  local expected_api_root=""
  local highest_ui_port
  local extra_ui_port
  if [ -n "${resolved_api_base:-}" ]; then
    expected_api_root="$(api_root_from_base "$resolved_api_base")"
  fi

  if [ -n "${UI_BASE:-}" ]; then
    local explicit="${UI_BASE%/}"
    explicit="${explicit%/web}"
    if wait_for_ui_root "$explicit" "$artifact_dir/ui_probe_explicit"; then
      printf '%s\n' "$explicit"
      return 0
    fi
    return 1
  fi

  if is_current_worktree_listener "$PREFERRED_UI_PORT" && wait_for_ui_root "http://${FRONTEND_HOST}:${PREFERRED_UI_PORT}" "$artifact_dir/ui_probe_port_${PREFERRED_UI_PORT}"; then
    local root="http://${FRONTEND_HOST}:${PREFERRED_UI_PORT}"
    if ui_matches_resolved_api "$root"; then
      printf '%s\n' "$root"
      return 0
    fi
    stop_listener "$PREFERRED_UI_PORT" >/dev/null || true
  fi

  local port
  for port in "${UI_PORT_CANDIDATES[@]}"; do
    if is_current_worktree_listener "$port" && wait_for_ui_root "http://${FRONTEND_HOST}:${port}" "$artifact_dir/ui_probe_port_${port}"; then
      local root="http://${FRONTEND_HOST}:${port}"
      if ui_matches_resolved_api "$root"; then
        printf '%s\n' "$root"
        return 0
      fi
      stop_listener "$port" >/dev/null || true
    fi
  done

  highest_ui_port="$(highest_port "$PREFERRED_UI_PORT" "${UI_PORT_CANDIDATES[@]}")"
  for ((extra_ui_port=highest_ui_port + 1; extra_ui_port<=highest_ui_port + UI_PORT_SEARCH_WINDOW; extra_ui_port++)); do
    if is_current_worktree_listener "$extra_ui_port" && wait_for_ui_root "http://${FRONTEND_HOST}:${extra_ui_port}" "$artifact_dir/ui_probe_port_${extra_ui_port}"; then
      printf '%s\n' "http://${FRONTEND_HOST}:${extra_ui_port}"
      return 0
    fi
  done

  if port_free "$PREFERRED_UI_PORT"; then
    if start_frontend_on_port "$PREFERRED_UI_PORT" "$expected_api_root"; then
      printf '%s\n' "http://${FRONTEND_HOST}:${PREFERRED_UI_PORT}"
      return 0
    fi
  fi

  for port in "${UI_PORT_CANDIDATES[@]}"; do
    if port_free "$port" && start_frontend_on_port "$port" "$expected_api_root"; then
      printf '%s\n' "http://${FRONTEND_HOST}:${port}"
      return 0
    fi
  done

  for ((extra_ui_port=highest_ui_port + 1; extra_ui_port<=highest_ui_port + UI_PORT_SEARCH_WINDOW; extra_ui_port++)); do
    if port_free "$extra_ui_port" && start_frontend_on_port "$extra_ui_port" "$expected_api_root"; then
      printf '%s\n' "http://${FRONTEND_HOST}:${extra_ui_port}"
      return 0
    fi
  done

  return 1
}

start_backend() {
  local port="$1"
  local api_base="http://${BACKEND_HOST}:${port}/api"
  local log_path="$runtime_dir/backend-${port}.log"
  local session_name="ragweld-ui-proof-api-${port}"
  log "Starting backend on ${BACKEND_HOST}:${port}"
  if command -v tmux >/dev/null 2>&1; then
    tmux kill-session -t "$session_name" 2>/dev/null || true
    tmux new-session -d -s "$session_name" \
      "cd '$ROOT_DIR' && env BACKEND_PORT='$port' POSTGRES_HOST='${POSTGRES_HOST:-127.0.0.1}' POSTGRES_PORT='${POSTGRES_PORT:-5432}' POSTGRES_DB='${POSTGRES_DB:-tribrid_rag}' POSTGRES_USER='${POSTGRES_USER:-postgres}' POSTGRES_PASSWORD='${POSTGRES_PASSWORD:-postgres}' NEO4J_URI='${NEO4J_URI:-bolt://127.0.0.1:7687}' NEO4J_USER='${NEO4J_USER:-neo4j}' NEO4J_PASSWORD='${NEO4J_PASSWORD:-password}' uv run uvicorn server.main:app --host '$BACKEND_HOST' --port '$port' --reload --log-level warning > '$log_path' 2>&1"
  else
    nohup env \
      BACKEND_PORT="$port" \
      POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
      POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
      POSTGRES_DB="${POSTGRES_DB:-tribrid_rag}" \
      POSTGRES_USER="${POSTGRES_USER:-postgres}" \
      POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}" \
      NEO4J_URI="${NEO4J_URI:-bolt://127.0.0.1:7687}" \
      NEO4J_USER="${NEO4J_USER:-neo4j}" \
      NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}" \
      uv run uvicorn server.main:app --host "$BACKEND_HOST" --port "$port" --reload --log-level warning >"$log_path" 2>&1 &
  fi
  wait_for_api "$api_base"
}

ensure_api_base() {
  local highest_backend_port
  local extra_backend_port
  if [ -n "${API_BASE:-}" ]; then
    if wait_for_api "$API_BASE"; then
      printf '%s\n' "$API_BASE"
      return 0
    fi
    return 1
  fi

  local default_api="http://${BACKEND_HOST}:${PREFERRED_BACKEND_PORT}/api"
  local pid
  pid="$(listener_pid "$PREFERRED_BACKEND_PORT")"
  if [ -n "$pid" ]; then
    if is_current_worktree_listener "$PREFERRED_BACKEND_PORT" && wait_for_api "$default_api"; then
      printf '%s\n' "$default_api"
      return 0
    fi
  else
    if start_backend "$PREFERRED_BACKEND_PORT"; then
      printf '%s\n' "$default_api"
      return 0
    fi
  fi

  local port
  for port in "${BACKEND_PORT_CANDIDATES[@]}"; do
    local api_base="http://${BACKEND_HOST}:${port}/api"
    if is_current_worktree_listener "$port" && wait_for_api "$api_base"; then
      printf '%s\n' "$api_base"
      return 0
    fi
  done

  highest_backend_port="$(highest_port "$PREFERRED_BACKEND_PORT" "${BACKEND_PORT_CANDIDATES[@]}")"
  for ((extra_backend_port=highest_backend_port + 1; extra_backend_port<=highest_backend_port + BACKEND_PORT_SEARCH_WINDOW; extra_backend_port++)); do
    local api_base="http://${BACKEND_HOST}:${extra_backend_port}/api"
    if is_current_worktree_listener "$extra_backend_port" && wait_for_api "$api_base"; then
      printf '%s\n' "$api_base"
      return 0
    fi
  done

  for port in "${BACKEND_PORT_CANDIDATES[@]}"; do
    local api_base="http://${BACKEND_HOST}:${port}/api"
    if port_free "$port" && start_backend "$port"; then
      printf '%s\n' "$api_base"
      return 0
    fi
  done

  for ((extra_backend_port=highest_backend_port + 1; extra_backend_port<=highest_backend_port + BACKEND_PORT_SEARCH_WINDOW; extra_backend_port++)); do
    local api_base="http://${BACKEND_HOST}:${extra_backend_port}/api"
    if port_free "$extra_backend_port" && start_backend "$extra_backend_port"; then
      printf '%s\n' "$api_base"
      return 0
    fi
  done

  return 1
}

resolve_corpus_path() {
  if [ -n "${CORPUS_PATH:-}" ]; then
    [ -d "$CORPUS_PATH" ] || return 1
    printf '%s\n' "$CORPUS_PATH"
    return 0
  fi

  case "$CORPUS_ID" in
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  local fixture_dir="$ROOT_DIR/output/automation/fixtures/$CORPUS_ID"
  mkdir -p "$fixture_dir"
  printf '%s\n' \
    '# Ragweld acceptance corpus' \
    '' \
    'This deterministic fixture verifies clean corpus creation, indexing, retrieval, and UI routing.' \
    'Northwind Labs builds retrieval systems in Denver. Alex Rivera works for Northwind Labs.' \
    >"$fixture_dir/README.md"
  printf '%s\n' "$fixture_dir"
}

ensure_corpus_exists() {
  local api_base="$1"
  local corpora_path="$artifact_dir/corpora.json"
  curl -sS "${api_base}/corpora" >"$corpora_path"
  local existing_path
  existing_path="$(python3 - "$corpora_path" "$CORPUS_ID" <<'PY'
import json
import sys

rows = json.load(open(sys.argv[1], "r", encoding="utf-8"))
target = sys.argv[2]
for row in rows:
    if str(row.get("corpus_id") or "").strip() == target:
        print(str(row.get("path") or "").strip())
        break
PY
)"
  if [ -n "$existing_path" ]; then
    corpus_action="reused"
    corpus_path="$existing_path"
    return 0
  fi

  corpus_path="$(resolve_corpus_path)"
  if [ -z "$corpus_path" ]; then
    corpus_action="missing_source_path"
    return 1
  fi

  local create_status
  create_status="$(
    curl -sS -o "$artifact_dir/corpus_create.json" -w "%{http_code}" \
      -X POST "${api_base}/corpora" \
      -H 'Content-Type: application/json' \
      -d "{\"corpus_id\":\"${CORPUS_ID}\",\"name\":\"${CORPUS_ID}\",\"path\":\"${corpus_path}\"}"
  )"
  if [ "$create_status" != "200" ]; then
    corpus_action="create_failed_${create_status}"
    return 1
  fi

  corpus_action="created"
  return 0
}

if ! check_git_health; then
  status="failed"
  failure_reason="git_worktree_health_failed"
fi

if [ "$status" = "passed" ] && ! resolved_api_base="$(ensure_api_base)"; then
  status="failed"
  failure_reason="api_unavailable_or_foreign_listener"
fi

if [ "$status" = "passed" ] && ! resolved_ui_root="$(ensure_ui_root)"; then
  status="failed"
  if [ -z "$failure_reason" ]; then
    failure_reason="ui_unavailable_or_foreign_listener"
  fi
fi

if [ -n "$resolved_ui_root" ]; then
  resolved_ui_base="${resolved_ui_root}/web"
fi

if [ "$status" = "passed" ] && [ -n "$resolved_api_base" ]; then
  if ensure_corpus_exists "$resolved_api_base"; then
    corpus_ready=1
  else
    status="failed"
    if [ -z "$failure_reason" ]; then
      failure_reason="corpus_unavailable"
    fi
  fi
fi

if [ -n "$resolved_ui_root" ]; then
  ui_listener_pid="$(listener_pid "${resolved_ui_root##*:}")"
  ui_listener_command="$(listener_command "${resolved_ui_root##*:}")"
fi
if [ -n "$resolved_api_base" ]; then
  resolved_api_port="$(port_from_url "$resolved_api_base")"
  api_listener_pid="$(listener_pid "$resolved_api_port")"
  api_listener_command="$(listener_command "$resolved_api_port")"
fi

ui_url_web=""
ui_url_root=""
ui_web_http_code=0
ui_root_http_code=0
api_url=""
api_http_code=0

if [ -n "$resolved_ui_root" ]; then
  ui_url_web="${resolved_ui_root}/web/rag?subtab=synthetic&corpus=${CORPUS_ID}"
  ui_url_root="${resolved_ui_root}/rag?subtab=synthetic&corpus=${CORPUS_ID}"
  ui_web_http_code="$(probe_code "$ui_url_web" "$artifact_dir/ui_probe_web.html")"
  ui_root_http_code="$(probe_code "$ui_url_root" "$artifact_dir/ui_probe_root.html")"
fi
if [ -n "$resolved_api_base" ]; then
  api_url="${resolved_api_base}/health"
  api_http_code="$(probe_code "$api_url" "$artifact_dir/api_health.json")"
fi

if ! ui_code_ok "$ui_web_http_code" && ! ui_code_ok "$ui_root_http_code"; then
  status="failed"
  if [ -z "$failure_reason" ]; then
    failure_reason="ui_probe_failed"
  fi
fi
if [ "$api_http_code" = "000" ] || [ "$api_http_code" = "404" ]; then
  status="failed"
  if [ -z "$failure_reason" ]; then
    failure_reason="api_probe_failed"
  fi
fi
if [ "$corpus_ready" -ne 1 ]; then
  status="failed"
  if [ -z "$failure_reason" ]; then
    failure_reason="corpus_unavailable"
  fi
fi

export artifact_ts status failure_reason CORPUS_ID resolved_ui_base resolved_ui_root resolved_api_base
export ui_url_web ui_url_root ui_web_http_code ui_root_http_code api_url api_http_code
export corpus_ready corpus_action corpus_path ui_listener_pid ui_listener_command api_listener_pid api_listener_command
export git_health_error

python3 - "$artifact_dir/summary.json" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

payload = {
    "started_at": os.environ["artifact_ts"],
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "status": os.environ["status"],
    "failure_reason": os.environ.get("failure_reason") or None,
    "git_health_error": os.environ.get("git_health_error") or None,
    "corpus_id": os.environ["CORPUS_ID"],
    "ui_base": os.environ.get("resolved_ui_base") or None,
    "ui_root": os.environ.get("resolved_ui_root") or None,
    "api_base": os.environ.get("resolved_api_base") or None,
    "ui_probe_web": {
        "url": os.environ.get("ui_url_web") or None,
        "http_code": int(os.environ.get("ui_web_http_code") or 0),
    },
    "ui_probe_root": {
        "url": os.environ.get("ui_url_root") or None,
        "http_code": int(os.environ.get("ui_root_http_code") or 0),
    },
    "api_probe": {
        "url": os.environ.get("api_url") or None,
        "http_code": int(os.environ.get("api_http_code") or 0),
    },
    "corpus_probe": {
        "ready": bool(int(os.environ.get("corpus_ready") or "0")),
        "action": os.environ.get("corpus_action") or "unknown",
        "path": os.environ.get("corpus_path") or None,
    },
    "ui_listener": {
        "pid": int(os.environ.get("ui_listener_pid") or 0) or None,
        "command": os.environ.get("ui_listener_command") or None,
    },
    "api_listener": {
        "pid": int(os.environ.get("api_listener_pid") or 0) or None,
        "command": os.environ.get("api_listener_command") or None,
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY

cp "$artifact_dir/summary.json" "$latest_path"
cat "$artifact_dir/summary.json"
if [ "$status" != "passed" ]; then
  exit 1
fi
