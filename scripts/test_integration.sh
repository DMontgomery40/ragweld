#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ragweld-integration-$$}"
POSTGRES_PASSWORD="ragweld-integration"
NEO4J_PASSWORD="ragweld-integration"

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
    NEO4J_HEAP_INIT=256M \
    NEO4J_HEAP_MAX=512M \
    NEO4J_PAGECACHE=256M \
    docker compose --project-name "$COMPOSE_PROJECT_NAME" -f docker-compose.yml "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
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

echo "[integration] project=${COMPOSE_PROJECT_NAME} starting disposable PostgreSQL and Neo4j"
compose up -d --wait --wait-timeout 120 postgres neo4j

postgres_binding="$(compose port postgres 5432)"
neo4j_binding="$(compose port neo4j 7687)"
postgres_port="${postgres_binding##*:}"
neo4j_port="${neo4j_binding##*:}"

export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT="$postgres_port"
export POSTGRES_DB="tribrid_rag"
export POSTGRES_USER="postgres"
export POSTGRES_PASSWORD
export POSTGRES_DSN="postgresql://postgres:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/tribrid_rag"
export NEO4J_URI="bolt://127.0.0.1:${neo4j_port}"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD
export RAGWELD_LOAD_DOTENV=0
export RAGWELD_STRICT_INTEGRATION=1

UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/ragweld-uv-cache}" \
UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/private/tmp/ragweld-uv-env}" \
uv run python - <<'PY'
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
UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/ragweld-uv-cache}" \
UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/private/tmp/ragweld-uv-env}" \
uv run pytest -q -m "(requires_postgres or requires_neo4j) and not requires_pg_search" "$@"
