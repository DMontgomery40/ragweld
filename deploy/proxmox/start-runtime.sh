#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly ROOT_DIR
readonly ETC_ROOT="${RAGWELD_ETC_ROOT:-/etc/ragweld}"
readonly EXPECTED_UID="$(id -u)"
readonly EXPECTED_GID="$(id -g)"
readonly RAGWELD_SKIP_TUNNEL="${RAGWELD_SKIP_TUNNEL:-0}"
readonly COMPOSE_FILES=(
  "docker-compose.yml"
  "infra/docker-compose.observability.yml"
  "deploy/proxmox/docker-compose.yml"
)
readonly PRODUCTION_SERVICES=(
  "postgres"
  "neo4j"
  "qdrant"
  "mlflow"
  "litellm"
  "postgres-exporter"
  "prometheus"
  "grafana"
  "loki"
  "promtail"
  "tempo"
  "alloy"
  "mimir"
  "pyroscope"
  "alertmanager"
  "langfuse"
  "langfuse-worker"
  "langfuse-postgres"
  "langfuse-clickhouse"
  "langfuse-redis"
  "langfuse-minio"
  "flyte"
  "authelia"
  "caddy"
)
readonly REQUIRED_SECRET_FILES=(
  "tribrid_config.json"
  "runtime.env"
  "litellm.env"
  "langfuse.env"
  "langfuse-oidc-client-secret"
  "authelia/session-secret"
  "authelia/storage-encryption-key"
  "authelia/oidc-hmac-secret"
  "authelia/langfuse-client-secret-digest"
  "authelia/users_database.yml"
  "authelia/oidc-rsa.pem"
)
readonly REQUIRED_TUNNEL_FILES=(
  "cloudflared/config.yml"
  "cloudflared/credentials.json"
)

die() {
  echo "ERROR: $*" >&2
  exit 1
}

stat_mode() {
  local path="$1"
  if stat -f '%Lp' "$path" >/dev/null 2>&1; then
    stat -f '%Lp' "$path"
  else
    stat -c '%a' "$path"
  fi
}

stat_owner() {
  local path="$1"
  if stat -f '%u:%g' "$path" >/dev/null 2>&1; then
    stat -f '%u:%g' "$path"
  else
    stat -c '%u:%g' "$path"
  fi
}

require_private_dir() {
  local path="$1"
  local label="$2"
  [[ -d "$path" ]] || die "$label is missing: $path"
  [[ ! -L "$path" ]] || die "$label must be a directory, not a symlink: $path"
  [[ "$(stat_owner "$path")" == "${EXPECTED_UID}:${EXPECTED_GID}" ]] || die "$label must be owned by uid:gid ${EXPECTED_UID}:${EXPECTED_GID}: $path"
  [[ "$(stat_mode "$path")" == "700" ]] || die "$label must have mode 0700: $path"
}

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -f "$path" ]] || die "$label is missing: $path"
  [[ ! -L "$path" ]] || die "$label must be a regular file, not a symlink: $path"
  [[ "$(stat_owner "$path")" == "${EXPECTED_UID}:${EXPECTED_GID}" ]] || die "$label must be owned by uid:gid ${EXPECTED_UID}:${EXPECTED_GID}: $path"
  [[ "$(stat_mode "$path")" == "600" ]] || die "$label must have mode 0600: $path"
}

require_repo_file() {
  local path="$1"
  local label="$2"
  [[ -f "$path" ]] || die "$label is missing: $path"
  [[ ! -L "$path" ]] || die "$label must be a regular file, not a symlink: $path"
}

require_repo_executable() {
  local path="$1"
  local label="$2"
  [[ -x "$path" ]] || die "$label is missing or not executable: $path"
  [[ ! -L "$path" ]] || die "$label must be a real executable, not a symlink: $path"
}

ensure_repo_symlink() {
  local repo_path="$1"
  local expected_target="$2"
  local actual_target
  if [[ -e "$repo_path" || -L "$repo_path" ]]; then
    [[ -L "$repo_path" ]] || die "$repo_path must be absent or an exact symlink to $expected_target"
    actual_target="$(python3 - "$repo_path" "$expected_target" <<'PY'
from pathlib import Path
import sys

actual = Path(sys.argv[1]).resolve(strict=True)
expected = Path(sys.argv[2]).resolve(strict=True)
print(actual == expected)
PY
)"
    [[ "$actual_target" == "True" ]] || die "$repo_path must be an exact symlink to $expected_target"
    return 0
  fi
  ln -s "$expected_target" "$repo_path"
}

require_compose() {
  command -v docker >/dev/null 2>&1 || die "docker CLI is required"
  docker compose version >/dev/null 2>&1 || die "docker compose plugin is required"
}

require_process_inspector() {
  command -v lsof >/dev/null 2>&1 || die "lsof is required before starting the Proxmox runtime"
  lsof -v >/dev/null 2>&1 || die "lsof is installed but not executable; fix it before starting the Proxmox runtime"
}

read_rendered_flyte_callback_host() {
  "$ROOT_DIR/.venv/bin/python" -c '
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from server.models.tribrid_config_model import TriBridConfig

payload = TriBridConfig.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
url = str(payload.training.ragweld_agent_flyte_callback_base_url or "").strip()
if not url:
    raise SystemExit("training.ragweld_agent_flyte_callback_base_url is empty in the rendered config")
host = urlsplit(url).hostname or ""
if not host:
    raise SystemExit("training.ragweld_agent_flyte_callback_base_url is not a valid URL")
print(host)
' "$1"
}

require_bridge_gateway_matches_rendered_callback() {
  local callback_host bridge_gateway
  callback_host="$(read_rendered_flyte_callback_host "$ETC_ROOT/tribrid_config.json")" \
    || die "Unable to validate rendered config and read training.ragweld_agent_flyte_callback_base_url from $ETC_ROOT/tribrid_config.json"
  bridge_gateway="$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null | tr -d '[:space:]')"
  [[ -n "$bridge_gateway" ]] || die "docker bridge gateway could not be resolved; verify the default bridge before starting the Proxmox runtime"
  [[ "$callback_host" == "$bridge_gateway" ]] || die "training.ragweld_agent_flyte_callback_base_url host (${callback_host}) must match the docker bridge gateway (${bridge_gateway})"
}

source_private_env_file() {
  local path="$1"
  set -a
  # shellcheck disable=SC1090
  source "$path"
  set +a
}

main() {
  local file_path
  local compose_args
  local services=("${PRODUCTION_SERVICES[@]}")

  cd "$ROOT_DIR"

  require_private_dir "$ETC_ROOT" "Ragweld secret root"
  require_private_dir "$ETC_ROOT/authelia" "Authelia secret directory"
  require_private_dir "$ETC_ROOT/authelia/state" "Authelia state directory"

  for file_path in "${REQUIRED_SECRET_FILES[@]}"; do
    require_private_file "$ETC_ROOT/$file_path" "Required secret file"
  done

  if [[ "$RAGWELD_SKIP_TUNNEL" == "1" ]]; then
    :
  else
    require_private_dir "$ETC_ROOT/cloudflared" "Cloudflared secret directory"
    for file_path in "${REQUIRED_TUNNEL_FILES[@]}"; do
      require_private_file "$ETC_ROOT/$file_path" "Required tunnel file"
    done
    services+=("cloudflared")
  fi

  require_repo_file "$ROOT_DIR/web/dist/index.html" "Built frontend entrypoint"
  require_repo_executable "$ROOT_DIR/.venv/bin/uvicorn" "Virtualenv uvicorn"
  require_repo_executable "$ROOT_DIR/start.sh" "Host runtime launcher"
  require_compose
  require_process_inspector
  require_bridge_gateway_matches_rendered_callback

  ensure_repo_symlink "$ROOT_DIR/.env" "$ETC_ROOT/runtime.env"
  ensure_repo_symlink "$ROOT_DIR/infra/litellm.env" "$ETC_ROOT/litellm.env"
  ensure_repo_symlink "$ROOT_DIR/infra/langfuse.env" "$ETC_ROOT/langfuse.env"

  source_private_env_file "$ETC_ROOT/runtime.env"
  source_private_env_file "$ETC_ROOT/langfuse.env"
  IFS= read -r LANGFUSE_OIDC_CLIENT_SECRET < "$ETC_ROOT/langfuse-oidc-client-secret"
  export LANGFUSE_OIDC_CLIENT_SECRET
  export RAGWELD_CONFIG_PATH="$ETC_ROOT/tribrid_config.json"

  compose_args=(docker compose --project-name ragweld)
  for file_path in "${COMPOSE_FILES[@]}"; do
    compose_args+=(-f "$file_path")
  done
  "${compose_args[@]}" run --rm --no-deps authelia \
    authelia validate-config --config /config/configuration.yml
  compose_args+=(up -d --wait)
  compose_args+=("${services[@]}")
  "${compose_args[@]}"

  exec ./start.sh --no-docker --no-local-model --no-frontend
}

main "$@"
