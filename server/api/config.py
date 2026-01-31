from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from server.models.tribrid_config_model import CorpusScope, TriBridConfig
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
