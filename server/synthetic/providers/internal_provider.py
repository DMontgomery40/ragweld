from __future__ import annotations

from typing import Any

from server.models.tribrid_config_model import (
    SyntheticArtifactKind,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.synthetic.recipes import generate_recipe_payloads, select_source_chunks


async def run_internal_provider(
    *,
    repo_id: str,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
) -> tuple[dict[SyntheticArtifactKind, Any], SyntheticRunSummary]:
    chunks = await select_source_chunks(repo_id=repo_id, cfg=cfg, request=request)
    return await generate_recipe_payloads(
        recipe=request.recipe,
        cfg=cfg,
        request=request,
        chunks=chunks,
    )
