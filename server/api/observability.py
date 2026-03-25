from __future__ import annotations

from fastapi import APIRouter, Query

from server.models.tribrid_config_model import ObservabilityStatusResponse, TriBridConfig
from server.observability.status import build_observability_status
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/status", response_model=ObservabilityStatusResponse)
async def observability_status(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ObservabilityStatusResponse:
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    try:
        cfg = await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError:
        cfg = await load_scoped_config(repo_id=None)
    return await build_observability_status(cfg)
