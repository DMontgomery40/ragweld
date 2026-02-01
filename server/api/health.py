from typing import Any

from fastapi import APIRouter, Depends
from starlette.responses import Response

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import CorpusScope, TriBridConfig
from server.observability.metrics import render_latest
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "services": {
            "api": {"status": "up"},
            "postgres": {"status": "unknown"},  # Not connected yet
            "neo4j": {"status": "unknown"},     # Not connected yet
        }
    }


@router.get("/ready")
async def readiness_check(scope: CorpusScope = Depends()) -> dict[str, Any]:
    """Readiness probe.

    Returns dependency status for Postgres + Neo4j.
    If a corpus is specified via query params (repo_id/corpus_id), checks the
    configured Neo4j database for that corpus as well.
    """
    corpus_id = scope.resolved_repo_id

    cfg: TriBridConfig
    if corpus_id:
        cfg = await load_scoped_config(repo_id=corpus_id)
    else:
        cfg = load_config()

    out: dict[str, Any] = {
        "ready": True,
        "corpus_id": corpus_id,
        "dependencies": {
            "postgres": {"ok": False, "error": None},
            "neo4j": {"ok": False, "error": None, "database": cfg.graph_storage.resolve_database(corpus_id)},
        },
    }

    # Postgres
    try:
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        out["dependencies"]["postgres"]["ok"] = True
        await pg.disconnect()
    except Exception as e:
        out["ready"] = False
        out["dependencies"]["postgres"]["error"] = str(e)

    # Neo4j
    try:
        db_name = cfg.graph_storage.resolve_database(corpus_id)
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.neo4j_password,
            database=db_name,
        )
        await neo4j.connect()
        info = await neo4j.ping()
        out["dependencies"]["neo4j"]["ok"] = True
        out["dependencies"]["neo4j"]["info"] = info
        # Database existence check (multi-db aware). For Community, this should still work.
        try:
            exists = await neo4j.database_exists(db_name)
            out["dependencies"]["neo4j"]["database_exists"] = bool(exists)
        except Exception as e:
            out["dependencies"]["neo4j"]["database_exists"] = None
            out["dependencies"]["neo4j"]["database_error"] = str(e)
        await neo4j.disconnect()
    except Exception as e:
        out["ready"] = False
        out["dependencies"]["neo4j"]["error"] = str(e)

    return out


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    # Backward-compatible alias for Prometheus scrape.
    # Prefer scraping /metrics (no /api prefix).
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
