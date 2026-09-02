from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from server.models.tribrid_config_model import RuntimeCapabilitiesResponse
from server.runtime_capabilities import build_runtime_capabilities_response_for_config
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(prefix="/api/runtime-capabilities", tags=["runtime-capabilities"])


@router.get("", response_model=RuntimeCapabilitiesResponse)
async def get_runtime_capabilities(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope runtime config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> RuntimeCapabilitiesResponse:
    """Return the executable runtime capability matrix for selection and docs surfaces."""
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    try:
        cfg = await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError:
        cfg = await load_scoped_config(repo_id=None)
    # The training-lane resolution probes the MLX runtime in a child process on first
    # use (cached afterwards); keep that off the event loop.
    return await asyncio.to_thread(build_runtime_capabilities_response_for_config, cfg)
