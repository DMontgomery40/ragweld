from __future__ import annotations

import os
import importlib.util
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from server.config import load_config as load_global_config
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import CorpusScope, MCPHTTPTransportStatus, MCPStatusResponse, TriBridConfig
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import get_config as load_scoped_config
from server.services.config_store import reset_config as reset_scoped_config
from server.services.config_store import save_config as save_scoped_config

router = APIRouter(tags=["config"])

@router.get("/config", response_model=TriBridConfig)
async def get_config(scope: CorpusScope = Depends()) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        return await load_scoped_config(repo_id=repo_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/config", response_model=TriBridConfig)
async def update_config(
    config: TriBridConfig,
    scope: CorpusScope = Depends(),
) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        return await save_scoped_config(config, repo_id=repo_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/config/{section}", response_model=TriBridConfig)
async def update_config_section(
    section: str,
    updates: dict[str, Any],
    scope: CorpusScope = Depends(),
) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        config = await load_scoped_config(repo_id=repo_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Only allow patching known top-level sections
    if section not in TriBridConfig.model_fields:
        raise HTTPException(status_code=404, detail=f"Unknown config section: {section}")

    # Build a new config dict with patched section and re-validate (ensures Field constraints apply)
    base = config.model_dump()
    current_section = base.get(section)
    if not isinstance(current_section, dict):
        raise HTTPException(status_code=400, detail=f"Config section '{section}' is not patchable")
    if not isinstance(updates, dict):
        raise HTTPException(status_code=422, detail="PATCH body must be a JSON object")

    merged = {**current_section, **updates}
    base[section] = merged

    try:
        new_config = TriBridConfig.model_validate(base)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        return await save_scoped_config(new_config, repo_id=repo_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/config/reset", response_model=TriBridConfig)
async def reset_config(scope: CorpusScope = Depends()) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        return await reset_scoped_config(repo_id=repo_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/secrets/check")
async def check_secrets(keys: str = Query(..., description="Comma-separated env var names")) -> dict[str, bool]:
    """Return which secret env vars are configured (never returns values)."""
    names = [k.strip() for k in (keys or "").split(",") if k.strip()]
    return {name: bool(os.getenv(name)) for name in names}


@router.get("/mcp/status", response_model=MCPStatusResponse)
async def mcp_status(request: Request) -> MCPStatusResponse:
    """Return status for MCP transports built into TriBridRAG.

    Notes:
    - The stdio transport is typically client-spawned (no always-on daemon).
    - HTTP transports may be added later; this endpoint is forward-compatible.
    """
    details: list[str] = []
    python_stdio_available = False
    python_http: MCPHTTPTransportStatus | None = None

    try:
        python_stdio_available = importlib.util.find_spec("mcp") is not None
    except Exception as e:
        python_stdio_available = False
        details.append(f"Error checking Python MCP package availability: {e}")

    if python_stdio_available:
        details.append("Python stdio MCP transport is available (client-spawned; no daemon).")
    else:
        details.append("Python stdio MCP transport not available (Python package 'mcp' not installed).")

    # Python Streamable HTTP transport is embedded under cfg.mcp.mount_path (same FastAPI app).
    try:
        cfg = load_global_config()
        if cfg.mcp.enabled:
            if python_stdio_available:
                host = request.url.hostname or "127.0.0.1"
                port = request.url.port or (443 if request.url.scheme == "https" else 80)
                # Starlette mounts require a trailing slash for the mount root.
                # Advertise the canonical URL that does not redirect for POST.
                path = str(cfg.mcp.mount_path).rstrip("/") + "/"
                python_http = MCPHTTPTransportStatus(
                    host=str(host),
                    port=int(port),
                    path=path,
                    running=True,
                )
                details.append(
                    f"Python HTTP MCP transport is enabled and mounted at {cfg.mcp.mount_path} "
                    f"(connect to http://{host}:{port}{path})."
                )
            else:
                details.append(
                    "Python HTTP MCP transport is configured as enabled, but the 'mcp' package is not installed."
                )
        else:
            details.append("Python HTTP MCP transport is disabled (config.mcp.enabled=false).")
    except Exception as e:
        details.append(f"Error resolving MCP HTTP status: {e}")

    return MCPStatusResponse(
        python_http=python_http,
        node_http=None,
        python_stdio_available=python_stdio_available,
        details=details,
    )


@router.get("/mcp/rag_search")
async def mcp_rag_search(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    force_local: bool = Query(False, description="Legacy flag (ignored)"),
    scope: CorpusScope = Depends(),
) -> dict[str, Any]:
    """Legacy debug endpoint: run tri-brid search and return compact results.

    Notes:
    - This endpoint exists for UI/debug tooling migrated from the legacy JS modules.
    - It returns HTTP 200 with an `error` field on failure (so callers can display the message).
    """
    _ = force_local  # ignored (legacy param)
    repo_id = scope.resolved_repo_id
    if not repo_id:
        return {"results": [], "error": "Missing corpus_id/repo_id (pass ?repo=... or ?corpus_id=...)"}
    if not q.strip():
        return {"results": [], "error": "Query must not be empty"}

    try:
        # Validate corpus exists (avoid implicitly creating new corpora/configs).
        global_cfg = load_global_config()
        pg = PostgresClient(global_cfg.indexing.postgres_url)
        await pg.connect()
        corpus = await pg.get_corpus(repo_id)
        if corpus is None:
            return {"results": [], "error": f"Corpus not found: {repo_id}"}

        cfg = await load_scoped_config(repo_id=repo_id)
        fusion = TriBridFusion(vector=None, sparse=None, graph=None)
        matches = await fusion.search(
            repo_id,
            q,
            cfg.fusion,
            include_vector=True,
            include_sparse=True,
            include_graph=True,
            top_k=int(top_k),
        )

        return {
            "results": [
                {
                    "file_path": m.file_path,
                    "start_line": int(m.start_line),
                    "end_line": int(m.end_line),
                    "rerank_score": float(m.score),
                }
                for m in matches
            ]
        }
    except Exception as e:
        return {"results": [], "error": str(e)}
