#!/usr/bin/env bash
# Register the Learning Agent workflow + launch plan into the Compose-owned
# Flyte control plane (service `flyte` in docker-compose.yml).
#
# Usage: scripts/flyte_register_learning_agent.sh
# Env:   FLYTECTL_CONFIG (default infra/flyte/flytectl.yaml)
#        FLYTE_PROJECT / FLYTE_DOMAIN (default ragweld / development)
#        FLYTE_WORKFLOW_VERSION (default: content hash of the workflow module)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG="${FLYTECTL_CONFIG:-$ROOT_DIR/infra/flyte/flytectl.yaml}"
PROJECT="${FLYTE_PROJECT:-ragweld}"
DOMAIN="${FLYTE_DOMAIN:-development}"
WORKFLOW_DIR="$ROOT_DIR/infra/flyte/workflows"
WORKFLOW_FILE="$WORKFLOW_DIR/learning_agent.py"
VERSION="${FLYTE_WORKFLOW_VERSION:-$(shasum -a 256 "$WORKFLOW_FILE" | cut -c1-12)}"

FLYTECTL="${FLYTECTL_BIN:-}"
if [[ -z "$FLYTECTL" ]]; then
  if command -v flytectl >/dev/null 2>&1; then
    FLYTECTL="flytectl"
  elif [[ -x "$HOME/.local/bin/flytectl" ]]; then
    FLYTECTL="$HOME/.local/bin/flytectl"
  else
    echo "ERROR: flytectl is not installed (https://docs.flyte.org/en/latest/flytectl/overview.html)." >&2
    exit 1
  fi
fi

ADMIN_URL="$(python3 - "$CONFIG" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r"^\s*endpoint:\s*(\S+)", text, re.M)
endpoint = match.group(1) if match else "127.0.0.1:30080"
endpoint = endpoint.replace("dns:///", "")
print(endpoint if endpoint.startswith("http") else f"http://{endpoint}")
PY
)"

if ! curl -fsS -m 5 "$ADMIN_URL/healthcheck" >/dev/null 2>&1; then
  echo "ERROR: Flyte admin is not reachable at $ADMIN_URL. Start it with: docker compose --project-name ragweld -f docker-compose.yml up -d --wait flyte" >&2
  exit 1
fi

docker_ns_ready() {
  # Best effort: when the Compose-owned sandbox is local we can see its namespaces.
  local container
  container="$(docker ps --filter "label=io.ragweld.managed=true" --filter "label=com.docker.compose.service=flyte" --format '{{.Names}}' 2>/dev/null | head -n1 || true)"
  if [[ -z "$container" ]]; then
    return 0
  fi
  docker exec "$container" kubectl get namespace "$1" >/dev/null 2>&1
}

echo "[flyte] admin=$ADMIN_URL project=$PROJECT domain=$DOMAIN version=$VERSION"

if ! "$FLYTECTL" --config "$CONFIG" get project "$PROJECT" -o json 2>/dev/null | grep -q "\"id\": *\"$PROJECT\""; then
  echo "[flyte] creating project $PROJECT"
  "$FLYTECTL" --config "$CONFIG" create project --id "$PROJECT" --name "$PROJECT" \
    --description "Ragweld Learning Agent orchestration"
fi

# flyteadmin materializes the per-project/domain Kubernetes namespace
# asynchronously (cluster resource sync). Executions launched before it exists
# fail with "namespaces ... not found", so wait for the first domain we use.
for _ in $(seq 1 60); do
  if "$FLYTECTL" --config "$CONFIG" get execution -p "$PROJECT" -d "$DOMAIN" -o json >/dev/null 2>&1 \
     && curl -fsS -m 5 "$ADMIN_URL/api/v1/projects" | grep -q "\"id\": *\"$PROJECT\"" \
     && docker_ns_ready "$PROJECT-$DOMAIN"; then
    break
  fi
  sleep 2
done

# Project root for fast registration is the workflow directory (no __init__.py
# chain above it), so only that directory is packaged and the module name is
# `learning_agent`.
cd "$WORKFLOW_DIR"
uv run --project "$ROOT_DIR" --extra flyte pyflyte --config "$CONFIG" register \
  --project "$PROJECT" --domain "$DOMAIN" --version "$VERSION" \
  --activate-launchplans \
  learning_agent.py

echo "[flyte] registered learning-agent-train version $VERSION in $PROJECT/$DOMAIN"
"$FLYTECTL" --config "$CONFIG" get launchplan -p "$PROJECT" -d "$DOMAIN" learning-agent-train --latest
