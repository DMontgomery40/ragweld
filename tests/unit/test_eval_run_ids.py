"""Eval run ids are a validated boundary: a query/path value can never escape data/eval_runs."""

from __future__ import annotations

import pytest

from server.api.eval import _run_path, validate_eval_run_id


@pytest.mark.parametrize("run_id", ["epstein-files-1__20260823_025351", "aurora_acceptance__20260821_220932", "r1"])
def test_valid_run_ids_resolve_inside_the_runs_dir(run_id: str) -> None:
    assert validate_eval_run_id(run_id) == run_id
    assert _run_path(run_id).name == f"{run_id}.json"


@pytest.mark.parametrize("run_id", ["../../tribrid_config", "a/b", "..", "", " ", "run id", ".hidden", "a" * 300])
def test_traversal_and_malformed_run_ids_are_rejected(run_id: str) -> None:
    with pytest.raises(ValueError):
        validate_eval_run_id(run_id)
    with pytest.raises(ValueError):
        _run_path(run_id)


def test_latest_run_for_repo_uses_completed_at_and_surfaces_corruption(tmp_path: Path) -> None:
    import json
    import os
    from datetime import UTC, datetime, timedelta

    from server.api import eval as eval_api
    from server.models.tribrid_config_model import EvalMetrics, EvalRun

    runs_dir = tmp_path / "eval_runs"
    runs_dir.mkdir()
    original = eval_api._RUNS_DIR
    eval_api._RUNS_DIR = runs_dir
    try:
        def _write(run_id: str, completed: datetime) -> None:
            run = EvalRun(
                run_id=run_id, repo_id="corpus-a", dataset_id="default", config_snapshot={}, config={}, total=0,
                top1_hits=0, topk_hits=0, top1_accuracy=0.0, topk_accuracy=0.0, duration_secs=0.0, use_multi=False,
                final_k=5, metrics=EvalMetrics(mrr=0, recall_at_5=0, recall_at_10=0, recall_at_20=0, precision_at_5=0,
                ndcg_at_10=0, latency_p50_ms=0, latency_p95_ms=0), results=[], started_at=completed, completed_at=completed,
            )
            (runs_dir / f"{run_id}.json").write_text(json.dumps(run.model_dump(mode="json")), encoding="utf-8")

        now = datetime.now(UTC)
        _write("corpus-a__old", now - timedelta(days=2))
        _write("corpus-a__new", now - timedelta(days=1))
        # touching the old file must not make it "latest"
        os.utime(runs_dir / "corpus-a__old.json", None)
        assert eval_api.latest_run_for_repo("corpus-a").run_id == "corpus-a__new"

        (runs_dir / "corpus-a__broken.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            eval_api.latest_run_for_repo("corpus-a")
    finally:
        eval_api._RUNS_DIR = original
