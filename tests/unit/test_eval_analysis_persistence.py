"""The costed AI comparison analysis is persisted per run and served from disk,
so re-opening a run never re-charges the gateway (M-73).

Zero mocks: the real persistence helpers and the real route functions are driven
against a tmp runs dir. The load/serve/delete paths contain no gateway call, so
reaching them to completion with nothing configured *is* the "no second gateway
call" proof.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from server.api import eval as eval_api
from server.models.tribrid_config_model import (
    EvalAnalysisArtifact,
    EvalMetrics,
    EvalRun,
)

MARKDOWN = (
    "The **most important** next experiment tunes `RERANKER_MODEL`.\n\n"
    "| Metric | Before | After |\n| --- | --- | --- |\n| top-k | 0.62 | 0.78 |\n"
)


def _artifact(run_id: str, compare_run_id: str) -> EvalAnalysisArtifact:
    return EvalAnalysisArtifact(
        run_id=run_id,
        compare_run_id=compare_run_id,
        analysis=MARKDOWN,
        model_used="openai.gpt-5.6-terra",
        created_at=datetime.now(UTC),
    )


def _redirect_runs_dir(tmp_path: Path):
    """Point the module's runs + analysis dirs at a tmp dir; return a restore fn."""
    runs_dir = tmp_path / "eval_runs"
    runs_dir.mkdir()
    orig_runs, orig_analysis = eval_api._RUNS_DIR, eval_api._ANALYSIS_DIR
    eval_api._RUNS_DIR = runs_dir
    eval_api._ANALYSIS_DIR = runs_dir / "analysis"

    def restore() -> None:
        eval_api._RUNS_DIR = orig_runs
        eval_api._ANALYSIS_DIR = orig_analysis

    return runs_dir, restore


def test_analysis_round_trips_through_disk(tmp_path: Path) -> None:
    _, restore = _redirect_runs_dir(tmp_path)
    try:
        eval_api._save_analysis(_artifact("corpus__20260830120005", "corpus__20260830120000"))
        loaded = eval_api._load_analysis("corpus__20260830120005")
        assert loaded is not None
        assert loaded.analysis == MARKDOWN
        assert loaded.compare_run_id == "corpus__20260830120000"
        assert loaded.model_used == "openai.gpt-5.6-terra"
    finally:
        restore()


@pytest.mark.asyncio
async def test_get_endpoint_serves_the_cached_analysis_without_a_gateway(tmp_path: Path) -> None:
    _, restore = _redirect_runs_dir(tmp_path)
    try:
        eval_api._save_analysis(_artifact("corpus__20260830120005", "corpus__20260830120000"))
        # The reload path the frontend calls. No gateway is configured; it returns
        # the same markdown, proving load never regenerates.
        result = await eval_api.get_eval_analysis(
            "corpus__20260830120005", compare_run_id="corpus__20260830120000"
        )
        assert result.analysis == MARKDOWN
        assert result.model_used == "openai.gpt-5.6-terra"
    finally:
        restore()


@pytest.mark.asyncio
async def test_get_endpoint_404s_on_a_different_baseline(tmp_path: Path) -> None:
    _, restore = _redirect_runs_dir(tmp_path)
    try:
        eval_api._save_analysis(_artifact("corpus__20260830120005", "corpus__20260830120000"))
        with pytest.raises(HTTPException) as exc:
            await eval_api.get_eval_analysis(
                "corpus__20260830120005", compare_run_id="corpus__someOtherBaseline"
            )
        assert exc.value.status_code == 404
    finally:
        restore()


@pytest.mark.asyncio
async def test_get_endpoint_404s_when_nothing_cached(tmp_path: Path) -> None:
    _, restore = _redirect_runs_dir(tmp_path)
    try:
        with pytest.raises(HTTPException) as exc:
            await eval_api.get_eval_analysis("corpus__missing", compare_run_id=None)
        assert exc.value.status_code == 404
    finally:
        restore()


@pytest.mark.asyncio
async def test_deleting_a_run_drops_its_cached_analysis(tmp_path: Path) -> None:
    runs_dir, restore = _redirect_runs_dir(tmp_path)
    try:
        run_id = "corpus__20260830120005"
        run = EvalRun(
            run_id=run_id,
            repo_id="corpus",
            dataset_id="default",
            config_snapshot={},
            config={},
            metrics=EvalMetrics(
                mrr=1.0,
                recall_at_5=1.0,
                recall_at_10=1.0,
                recall_at_20=1.0,
                precision_at_5=1.0,
                ndcg_at_10=1.0,
                latency_p50_ms=1.0,
                latency_p95_ms=1.0,
            ),
            results=[],
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        eval_api._save_run(run)
        eval_api._save_analysis(_artifact(run_id, "corpus__20260830120000"))
        assert eval_api._load_analysis(run_id) is not None

        deleted = await eval_api.delete_eval_run(run_id)
        assert deleted["ok"] is True
        assert eval_api._load_analysis(run_id) is None
    finally:
        restore()
