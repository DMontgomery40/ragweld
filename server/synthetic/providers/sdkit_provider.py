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
from server.synthetic.recipes import generate_recipe_payloads, select_source_chunks
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
        recipe=request.recipe,
        cfg=cfg,
        request=request,
        chunks=chunks,
    )
    report = str(artifacts.get("report_md") or "")
    artifacts["report_md"] = (
        f"{report}\nSDKit staging directory: {staged}\n"
        "Provider mode: synthetic_data_kit (local deterministic parse for v1 artifacts).\n"
    )
    return artifacts, summary
