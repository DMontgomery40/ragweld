#!/usr/bin/env bash

# Shared ownership checks for Ragweld's host processes and fixed Compose project.
# Callers must set ROOT_DIR before sourcing this file.

if [[ -z "${ROOT_DIR:-}" ]]; then
  echo "ERROR: ROOT_DIR must be set before sourcing runtime_lifecycle.sh" >&2
  exit 1
fi

readonly RAGWELD_COMPOSE_PROJECT="ragweld"
RAGWELD_RUNTIME_DIR="${RAGWELD_RUNTIME_DIR:-${ROOT_DIR}/.ragweld-runtime}"
RAGWELD_LIFECYCLE_LOCK="${RAGWELD_RUNTIME_DIR}/lifecycle.lock"
RAGWELD_LOCK_HELD=0
umask 077
mkdir -p "$RAGWELD_RUNTIME_DIR"

require_process_inspector() {
  command -v lsof >/dev/null 2>&1 || {
    echo "ERROR: lsof is required for safe Ragweld process ownership checks" >&2
    return 2
  }
}

acquire_lifecycle_lock() {
  local owner
  if mkdir "$RAGWELD_LIFECYCLE_LOCK" 2>/dev/null; then
    printf '%s\n' "$$" >"${RAGWELD_LIFECYCLE_LOCK}/owner"
    RAGWELD_LOCK_HELD=1
    return 0
  fi

  owner="$(sed -n '1p' "${RAGWELD_LIFECYCLE_LOCK}/owner" 2>/dev/null || true)"
  if [[ "$owner" =~ ^[0-9]+$ ]] && [[ -n "$(process_cwd "$owner")" ]]; then
    echo "ERROR: another Ragweld lifecycle command is active (pid=${owner})" >&2
    return 1
  fi

  rm -f "${RAGWELD_LIFECYCLE_LOCK}/owner"
  rmdir "$RAGWELD_LIFECYCLE_LOCK" 2>/dev/null || {
    echo "ERROR: stale lifecycle lock could not be removed safely" >&2
    return 1
  }
  mkdir "$RAGWELD_LIFECYCLE_LOCK"
  printf '%s\n' "$$" >"${RAGWELD_LIFECYCLE_LOCK}/owner"
  RAGWELD_LOCK_HELD=1
}

release_lifecycle_lock() {
  local owner
  [[ "$RAGWELD_LOCK_HELD" == "1" ]] || return 0
  owner="$(sed -n '1p' "${RAGWELD_LIFECYCLE_LOCK}/owner" 2>/dev/null || true)"
  if [[ "$owner" == "$$" ]]; then
    rm -f "${RAGWELD_LIFECYCLE_LOCK}/owner"
    rmdir "$RAGWELD_LIFECYCLE_LOCK" 2>/dev/null || true
  fi
  RAGWELD_LOCK_HELD=0
}

runtime_pid_file() {
  printf '%s/%s.pid\n' "$RAGWELD_RUNTIME_DIR" "$1"
}

write_owned_pid() {
  local kind="$1"
  local pid="$2"
  local port="$3"
  local target
  target="$(runtime_pid_file "$kind")"
  printf '%s|%s\n' "$pid" "$port" >"${target}.tmp"
  mv "${target}.tmp" "$target"
}

port_listen_pids() {
  local port="$1"
  require_process_inspector || return $?
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null || true
}

process_cwd() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

owned_pid() {
  local kind="$1"
  local expected_cwd="$2"
  local pid_file record pid port cwd listeners
  require_process_inspector || return $?
  pid_file="$(runtime_pid_file "$kind")"
  [[ -f "$pid_file" ]] || return 1
  record="$(sed -n '1p' "$pid_file" 2>/dev/null || true)"
  pid="${record%%|*}"
  port="${record#*|}"
  if [[ ! "$pid" =~ ^[0-9]+$ || ! "$port" =~ ^[0-9]+$ ]]; then
    rm -f "$pid_file"
    return 1
  fi
  cwd="$(process_cwd "$pid")"
  listeners="$(port_listen_pids "$port")"
  if [[ "$cwd" != "$expected_cwd" ]] || ! printf '%s\n' "$listeners" | grep -qx "$pid"; then
    echo "Refusing to signal unowned ${kind} pid=${pid}; removing stale metadata only." >&2
    rm -f "$pid_file"
    return 1
  fi
  printf '%s\n' "$pid"
}

stop_owned_process() {
  local kind="$1"
  local expected_cwd="$2"
  local pid i
  if pid="$(owned_pid "$kind" "$expected_cwd")"; then
    :
  else
    local status=$?
    [[ "$status" == "1" ]] && return 0
    return "$status"
  fi
  echo "Stopping Ragweld ${kind} pid=${pid}"
  if ! kill -TERM "$pid" >/dev/null 2>&1; then
    echo "ERROR: unable to signal owned Ragweld ${kind} pid=${pid}; ownership metadata was preserved." >&2
    return 2
  fi
  i=0
  while [[ "$(process_cwd "$pid")" == "$expected_cwd" && "$i" -lt 50 ]]; do
    sleep 0.1
    i=$((i + 1))
  done
  if [[ "$(process_cwd "$pid")" == "$expected_cwd" ]]; then
    echo "Ragweld ${kind} did not stop after TERM; sending KILL to validated pid=${pid}" >&2
    if ! kill -KILL "$pid" >/dev/null 2>&1; then
      echo "ERROR: unable to force-stop owned Ragweld ${kind} pid=${pid}; ownership metadata was preserved." >&2
      return 2
    fi
  fi
  rm -f "$(runtime_pid_file "$kind")"
}

stop_owned_process_exact() {
  local kind="$1"
  local expected_cwd="$2"
  local expected_pid="$3"
  local pid_file record recorded_pid cwd i
  pid_file="$(runtime_pid_file "$kind")"
  record="$(sed -n '1p' "$pid_file" 2>/dev/null || true)"
  recorded_pid="${record%%|*}"
  [[ "$recorded_pid" == "$expected_pid" ]] || return 0
  cwd="$(process_cwd "$expected_pid")"
  [[ -n "$cwd" ]] || { rm -f "$pid_file"; return 0; }
  if [[ "$cwd" != "$expected_cwd" ]]; then
    echo "Refusing to signal unowned ${kind} pid=${expected_pid}; removing stale metadata only." >&2
    rm -f "$pid_file"
    return 0
  fi
  echo "Stopping Ragweld ${kind} pid=${expected_pid}"
  if ! kill -TERM "$expected_pid" >/dev/null 2>&1; then
    echo "ERROR: unable to signal owned Ragweld ${kind} pid=${expected_pid}; ownership metadata was preserved." >&2
    return 2
  fi
  i=0
  while [[ "$(process_cwd "$expected_pid")" == "$expected_cwd" && "$i" -lt 50 ]]; do
    sleep 0.1
    i=$((i + 1))
  done
  if [[ "$(process_cwd "$expected_pid")" == "$expected_cwd" ]]; then
    echo "Ragweld ${kind} did not stop after TERM; sending KILL to validated pid=${expected_pid}" >&2
    if ! kill -KILL "$expected_pid" >/dev/null 2>&1; then
      echo "ERROR: unable to force-stop owned Ragweld ${kind} pid=${expected_pid}; ownership metadata was preserved." >&2
      return 2
    fi
  fi
  rm -f "$pid_file"
}

ragweld_repo_process_pids() {
  local pid cwd
  require_process_inspector || return $?
  while IFS= read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    cwd="$(process_cwd "$pid")"
    if [[ "$cwd" == "$ROOT_DIR" || "$cwd" == "$ROOT_DIR/web" ]]; then
      printf '%s\n' "$pid"
    fi
  done < <(lsof -nP -iTCP -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | sort -u)
}

owned_host_records_released() {
  local expected_backend_pid="$1"
  local expected_frontend_pid="$2"
  local backend_record frontend_record
  backend_record="$(sed -n '1p' "$(runtime_pid_file backend)" 2>/dev/null || true)"
  frontend_record="$(sed -n '1p' "$(runtime_pid_file frontend)" 2>/dev/null || true)"
  if [[ -n "$expected_backend_pid" && "${backend_record%%|*}" == "$expected_backend_pid" ]]; then
    return 1
  fi
  if [[ -n "$expected_frontend_pid" && "${frontend_record%%|*}" == "$expected_frontend_pid" ]]; then
    return 1
  fi
  return 0
}

validate_reset_docker_scope() {
  local container_ids volume_names id labels service volume
  if ! container_ids="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker ps -aq \
    --filter "label=com.docker.compose.project=${RAGWELD_COMPOSE_PROJECT}")"; then
    echo "ERROR: unable to enumerate Ragweld project containers; refusing reset" >&2
    return 1
  fi
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    labels="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker inspect --format \
      '{{ index .Config.Labels "com.docker.compose.project" }}|{{ index .Config.Labels "io.ragweld.managed" }}|{{ index .Config.Labels "com.docker.compose.service" }}' \
      "$id")"
    service="${labels##*|}"
    case "$service" in
      postgres|postgres-exporter|neo4j|grafana|prometheus|loki|promtail|api|tempo|alloy|litellm|vllm) ;;
      *) echo "ERROR: refusing reset with unexpected Ragweld container service: ${service:-unknown}" >&2; return 1 ;;
    esac
    [[ "$labels" == "ragweld|true|${service}" ]] || {
      echo "ERROR: refusing reset of container outside the exact Ragweld ownership boundary" >&2
      return 1
    }
  done <<<"$container_ids"

  if ! volume_names="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker volume ls \
    --filter "label=com.docker.compose.project=${RAGWELD_COMPOSE_PROJECT}" \
    --format '{{.Name}}')"; then
    echo "ERROR: unable to enumerate Ragweld project volumes; refusing reset" >&2
    return 1
  fi
  while IFS= read -r volume; do
    [[ -n "$volume" ]] || continue
    case "$volume" in
      ragweld_postgres_data|ragweld_neo4j_data|ragweld_neo4j_logs|ragweld_grafana_data|ragweld_prometheus_data|ragweld_loki_data|ragweld_tempo_data|ragweld_hf_cache) ;;
      *) echo "ERROR: refusing reset with unexpected Ragweld project volume: ${volume}" >&2; return 1 ;;
    esac
  done <<<"$volume_names"
}

local_docker_ready() {
  env -u DOCKER_HOST -u DOCKER_CONTEXT docker info >/dev/null 2>&1
}

require_local_docker_context() {
  local endpoint
  endpoint="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
  case "$endpoint" in
    unix://*|npipe://*) ;;
    *)
      echo "ERROR: refusing Docker control through non-local endpoint: ${endpoint:-unknown}" >&2
      return 1
      ;;
  esac
}

ragweld_compose() {
  env -u DOCKER_HOST -u DOCKER_CONTEXT docker compose \
    --project-name "$RAGWELD_COMPOSE_PROJECT" \
    -f "$ROOT_DIR/docker-compose.yml" \
    -f "$ROOT_DIR/infra/docker-compose.observability.yml" \
    "$@"
}
