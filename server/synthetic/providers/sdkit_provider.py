from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
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
from server.synthetic.storage import run_dir


def _stage_sdkit_inputs(*, run_id: str, chunks: list[Any]) -> Path:
    base = run_dir(run_id) / "sdkit_input"
    base.mkdir(parents=True, exist_ok=True)
    for ch in chunks:
        chunk_id = str(getattr(ch, "chunk_id", "chunk"))
        file_path = str(getattr(ch, "file_path", ""))
        content = str(getattr(ch, "content", ""))
        p = base / f"{chunk_id}.txt"
        body = f"FILE_PATH: {file_path}\n\n{content}\n"
        p.write_text(body, encoding="utf-8")
    return base


async def run_sdkit_provider(
    *,
    run_id: str,
    repo_id: str,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
) -> tuple[dict[SyntheticArtifactKind, Any], SyntheticRunSummary]:
    materialized_manifest = await load_materialized_corpus_eval_adapter(
        repo_id=repo_id,
        cfg=cfg,
        request=request,
    )
    manifest_only_mode = materialized_manifest is not None and recipe_can_skip_source_chunks_for_manifest(request.recipe)

    staged: Path | None = None
    if manifest_only_mode:
        chunks = []
    else:
        binary = shutil.which("synthetic-data-kit")
        if not binary:
            raise RuntimeError(
                "synthetic_data_kit provider is unavailable: install `synthetic-data-kit` and ensure it is on PATH."
            )

        chunks = await select_source_chunks(repo_id=repo_id, cfg=cfg, request=request)
        staged = _stage_sdkit_inputs(run_id=run_id, chunks=chunks)

        try:
            subprocess.run(
                [binary, "--help"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            raise RuntimeError(
                f"synthetic_data_kit provider failed to start. stderr={stderr[:400]}"
            ) from e

    artifacts, summary = await generate_recipe_payloads(
        repo_id=repo_id,
        recipe=request.recipe,
        cfg=cfg,
        request=request,
        chunks=chunks,
        materialized_manifest=materialized_manifest,
    )
    report = str(artifacts.get("report_md") or "")
    if manifest_only_mode:
        artifacts["report_md"] = (
            f"{report}\n"
            "Provider mode: synthetic_data_kit compatibility adapter (materialized corpus manifest).\n"
        )
    else:
        artifacts["report_md"] = (
            f"{report}\nSDKit staging directory: {staged}\n"
            "Provider mode: synthetic_data_kit (local deterministic parse for v1 artifacts).\n"
        )
    return artifacts, summary
