from contextlib import suppress

import httpx
from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from server.config import load_config
from server.chat.gateway_runtime import (
    resolve_litellm_api_key,
    resolve_litellm_base_url,
    resolve_vllm_base_url,
)
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import (
    CorpusScope,
    HealthServiceStatus,
    HealthStatus,
    ReadinessDependencyStatus,
    ReadinessStatus,
    TriBridConfig,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["health"])

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()


async def _disconnect_neo4j_quietly(neo4j: Neo4jClient) -> None:
    with suppress(Exception):
        await neo4j.disconnect()


async def _probe_neo4j_readiness(
    neo4j: Neo4jClient,
    *,
    db_name: str,
    status: ReadinessDependencyStatus,
) -> bool:
    try:
        await neo4j.connect()
        info = await neo4j.ping()
        status.ok = True
        status.info = info
        try:
            exists = await neo4j.database_exists(db_name)
            status.database_exists = bool(exists)
            if not exists:
                status.ok = False
                status.error = "Resolved Neo4j database does not exist."
                status.operator_hint = "Create the resolved graph database or correct the corpus database mapping."
                return False
        except Exception:
            status.ok = False
            status.error = "Neo4j database readiness could not be verified."
            status.operator_hint = "Verify Neo4j database permissions and the resolved corpus database."
            return False
        return True
    finally:
        await _disconnect_neo4j_quietly(neo4j)


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    # Keep this endpoint fast and dependency-free: do not connect to Postgres/Neo4j here.
    return HealthStatus(
        ok=True,
        status="healthy",
        services={
            "api": HealthServiceStatus(status="up"),
            "postgres": HealthServiceStatus(status="unknown"),
            "neo4j": HealthServiceStatus(status="unknown"),
        },
    )


@router.get("/ready", response_model=ReadinessStatus)
async def readiness_check(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> ReadinessStatus | JSONResponse:
    """Readiness probe.

    Returns dependency status for Postgres, Neo4j, LiteLLM, and vLLM.
    If a corpus is specified via query params (repo_id/corpus_id), checks the
    configured Neo4j database for that corpus as well.
    """
    corpus_id = scope.resolved_repo_id

    cfg: TriBridConfig
    corpus_error: str | None = None
    if corpus_id:
        try:
            cfg = await load_scoped_config(repo_id=corpus_id)
        except CorpusNotFoundError as e:
            # Readiness should never 500 just because a caller passed an unknown corpus_id.
            # Fall back to global config so we can still report dependency health.
            corpus_error = str(e)
            cfg = load_config()
        except Exception:
            # Keep /ready robust: report failure but do not crash.
            corpus_error = "Scoped corpus config is unavailable."
            cfg = load_config()
    else:
        cfg = load_config()

    postgres = ReadinessDependencyStatus()
    neo4j_status = ReadinessDependencyStatus(database=cfg.graph_storage.resolve_database(corpus_id))
    litellm_status = ReadinessDependencyStatus()
    vllm_status = ReadinessDependencyStatus()
    ready = not bool(corpus_error)

    # Postgres
    try:
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        postgres.ok = True
        await pg.disconnect()
    except Exception:
        ready = False
        postgres.error = "PostgreSQL control store is unavailable."
        postgres.operator_hint = "Verify the scoped Ragweld Postgres service and DSN, then retry readiness."

    # Neo4j
    try:
        db_name = cfg.graph_storage.resolve_database(corpus_id)
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=db_name,
        )
        if not await _probe_neo4j_readiness(neo4j, db_name=db_name, status=neo4j_status):
            ready = False
    except Exception:
        ready = False
        neo4j_status.ok = False
        neo4j_status.error = "Neo4j graph store is unavailable."
        neo4j_status.operator_hint = "Verify the scoped Ragweld Neo4j service and credentials, then retry readiness."

    # Generation gateway
    try:
        litellm_url = resolve_litellm_base_url(configured_url=cfg.chat.litellm.base_url)
        litellm_key = resolve_litellm_api_key()
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(
                f"{litellm_url}/models",
                headers={"Authorization": f"Bearer {litellm_key}"},
            )
            response.raise_for_status()
        litellm_status.ok = True
        litellm_status.info = {"status": "authenticated and reachable"}
    except Exception:
        ready = False
        litellm_status.error = "LiteLLM generation gateway is unavailable."
        litellm_status.operator_hint = "Start the managed LiteLLM service and verify its client key."

    # Local serving backend: readiness requires the served identity, not just a
    # listener — the alias must front chat.vllm.default_model at the catalog
    # ragweld-local context window.
    serving_mismatch: str | None = None
    try:
        from server.gateway_catalog import LOCAL_GATEWAY_ALIAS, gateway_rows_snapshot
        from server.observability.status import vllm_serving_mismatch

        vllm_url = resolve_vllm_base_url(configured_url=cfg.chat.vllm.base_url)
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{vllm_url}/models")
            response.raise_for_status()
            payload = response.json()
        local_row = gateway_rows_snapshot().get(LOCAL_GATEWAY_ALIAS)
        serving_mismatch = vllm_serving_mismatch(
            payload,
            expected_model=cfg.chat.vllm.default_model,
            expected_context=local_row.context if local_row is not None else None,
        )
        if serving_mismatch is not None:
            raise RuntimeError(serving_mismatch)
        vllm_status.ok = True
        vllm_status.info = {"status": "reachable"}
    except Exception:
        ready = False
        if serving_mismatch is not None:
            vllm_status.error = f"vLLM model serving mismatch: {serving_mismatch}."
            vllm_status.operator_hint = "Restart the host local-model server on the configured model (./start.sh) or fix chat.vllm.default_model / the catalog ragweld-local row."
        else:
            vllm_status.error = "vLLM model serving is unavailable."
            vllm_status.operator_hint = "Start the host local-model server (./start.sh, or its vllm-metal serve command) and wait for model loading to complete."

    status = ReadinessStatus(
        ready=ready,
        corpus_id=corpus_id,
        corpus_error=corpus_error,
        dependencies={
            "postgres": postgres,
            "neo4j": neo4j_status,
            "litellm": litellm_status,
            "vllm": vllm_status,
        },
    )
    if ready:
        return status
    return JSONResponse(status_code=503, content=status.model_dump(mode="json"))
