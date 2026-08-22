#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then
  echo "ERROR: COMPOSE_PROJECT_NAME cannot override the disposable integration project." >&2
  exit 2
fi
readonly COMPOSE_PROJECT_NAME="ragweld-integration-${RANDOM}-$$"
POSTGRES_PASSWORD="ragweld-integration"
NEO4J_PASSWORD="ragweld-integration"
INTEGRATION_RUNTIME_DIR=""

compose() {
  env \
    POSTGRES_IMAGE="pgvector/pgvector:pg16" \
    POSTGRES_DB="tribrid_rag" \
    POSTGRES_USER="postgres" \
    POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    POSTGRES_PORT=0 \
    NEO4J_IMAGE="neo4j:5.26.20-community" \
    NEO4J_USER="neo4j" \
    NEO4J_PASSWORD="$NEO4J_PASSWORD" \
    NEO4J_HTTP_PORT=0 \
    NEO4J_BOLT_PORT=0 \
    QDRANT_PORT=0 \
    QDRANT_GRPC_PORT=0 \
    NEO4J_HEAP_INIT=256M \
    NEO4J_HEAP_MAX=512M \
    NEO4J_PAGECACHE=256M \
    docker compose --project-name "$COMPOSE_PROJECT_NAME" -f docker-compose.yml "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "${INTEGRATION_RUNTIME_DIR:-}" && -d "$INTEGRATION_RUNTIME_DIR" ]]; then
    rm -f "$INTEGRATION_RUNTIME_DIR/tribrid_config.json"
    rmdir "$INTEGRATION_RUNTIME_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

command -v docker >/dev/null 2>&1 || {
  echo "ERROR: Docker CLI is unavailable." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "ERROR: Docker Compose plugin is unavailable." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "ERROR: The selected host-owned Docker runtime is unavailable. Start/select it, then retry." >&2
  exit 1
}

echo "[integration] project=${COMPOSE_PROJECT_NAME} starting disposable PostgreSQL, Neo4j, and Qdrant"
compose up -d --wait --wait-timeout 120 postgres neo4j qdrant

postgres_binding="$(compose port postgres 5432)"
neo4j_binding="$(compose port neo4j 7687)"
qdrant_binding="$(compose port qdrant 6333)"
postgres_port="${postgres_binding##*:}"
neo4j_port="${neo4j_binding##*:}"
qdrant_port="${qdrant_binding##*:}"

export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT="$postgres_port"
export POSTGRES_DB="tribrid_rag"
export POSTGRES_USER="postgres"
export POSTGRES_PASSWORD
export POSTGRES_DSN="postgresql://postgres:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/tribrid_rag"
export NEO4J_URI="bolt://127.0.0.1:${neo4j_port}"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD
export QDRANT_URL="http://127.0.0.1:${qdrant_port}"
export RAGWELD_LOAD_DOTENV=0
export RAGWELD_STRICT_INTEGRATION=1

INTEGRATION_RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ragweld-integration-config.XXXXXX")"
export RAGWELD_INTEGRATION_RUNTIME_DIR="$INTEGRATION_RUNTIME_DIR"
export RAGWELD_CONFIG_PATH="$INTEGRATION_RUNTIME_DIR/tribrid_config.json"
export RAGWELD_SOURCE_CONFIG_PATH="$ROOT_DIR/tribrid_config.json"

UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/ragweld-uv-cache}" \
uv run --no-sync python - <<'PY'
import json
import os
from pathlib import Path

source = Path(os.environ["RAGWELD_SOURCE_CONFIG_PATH"])
target = Path(os.environ["RAGWELD_CONFIG_PATH"])
payload = json.loads(source.read_text(encoding="utf-8"))
payload["indexing"]["postgres_url"] = os.environ["POSTGRES_DSN"]
payload["graph_storage"]["neo4j_uri"] = os.environ["NEO4J_URI"]
payload.setdefault("qdrant", {})["url"] = os.environ["QDRANT_URL"]
target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
target.chmod(0o600)
PY

UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/ragweld-uv-cache}" \
uv run --no-sync python - <<'PY'
import asyncio
import os

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient


async def main() -> None:
    postgres = PostgresClient(os.environ["POSTGRES_DSN"])
    neo4j = Neo4jClient(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USER"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        await postgres.connect()
        await neo4j.connect()
        await neo4j.ping()
        await neo4j.ensure_schema()
    finally:
        await neo4j.disconnect()
        await PostgresClient.close_shared_pools()


asyncio.run(main())
PY

echo "[integration] schemas ready; running strict live-service tests"
UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/ragweld-uv-cache}" \
uv run --no-sync pytest -q -m "requires_postgres or requires_neo4j or requires_qdrant" "$@"
