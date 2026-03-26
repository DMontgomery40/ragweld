from __future__ import annotations

from typing import Any

from server.models.tribrid_config_model import (
    SyntheticArtifactKind,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.synthetic.recipes import (
    generate_recipe_payloads,
    load_materialized_corpus_eval_adapter,
    recipe_can_skip_source_chunks_for_manifest,
    select_source_chunks,
)


async def run_internal_provider(
    *,
    repo_id: str,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
) -> tuple[dict[SyntheticArtifactKind, Any], SyntheticRunSummary]:
    materialized_manifest = await load_materialized_corpus_eval_adapter(
        repo_id=repo_id,
        cfg=cfg,
        request=request,
    )
    if materialized_manifest is not None and recipe_can_skip_source_chunks_for_manifest(request.recipe):
        chunks = []
    else:
        chunks = await select_source_chunks(repo_id=repo_id, cfg=cfg, request=request)
    return await generate_recipe_payloads(
        repo_id=repo_id,
        recipe=request.recipe,
        cfg=cfg,
        request=request,
        chunks=chunks,
        materialized_manifest=materialized_manifest,
    )
