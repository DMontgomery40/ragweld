"""The "Latest" ML-quality gauges are a view of the persisted runs, not of process memory.

Every test writes real run files where the API writes them and scrapes the real
Prometheus registry through `metrics.render_latest()`. Nothing is patched, and
no test calls the `.set()` path that used to populate these series — which is
the point: a freshly started process must already report the truth.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.models.eval import EvalDoc, EvalMetrics, EvalResult, EvalRun
from server.models.tribrid_config_model import BenchmarkResult, BenchmarkRun, PromptfooRun
from server.observability import metrics
from server.observability.ml_quality import (
    _BENCHMARK_RUNS_DIR,
    _EVAL_RUNS_DIR,
    _PROMPTFOO_RUNS_DIR,
    latest_quality_values,
)

_GAUGES = (
    "tribrid_eval_last_top1_accuracy",
    "tribrid_eval_last_topk_accuracy",
    "tribrid_promptfoo_last_pass_ratio",
    "tribrid_benchmark_last_avg_latency_ms",
)


def _scrape() -> dict[str, float]:
    """Every ML-quality sample the real registry currently exposes."""

    body, _content_type = metrics.render_latest()
    samples: dict[str, float] = {}
    for line in body.decode("utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, _, value = line.partition(" ")
        if name in _GAUGES:
            samples[name] = float(value)
    return samples


@contextmanager
def _no_persisted_runs(backup_root: Path) -> Iterator[None]:
    """Move every persisted run aside for the duration of the block, then restore it."""

    moved: list[tuple[Path, Path]] = []
    for index, directory in enumerate((_EVAL_RUNS_DIR, _BENCHMARK_RUNS_DIR)):
        if directory.is_dir():
            stash = backup_root / f"stash_{index}"
            shutil.move(str(directory), str(stash))
            moved.append((directory, stash))
    try:
        yield
    finally:
        for directory, stash in moved:
            if directory.exists():
                shutil.rmtree(directory)
            shutil.move(str(stash), str(directory))


def _eval_run(corpus_id: str, *, top1: float, topk: float) -> EvalRun:
    return EvalRun(
        run_id=f"{corpus_id}__20260830_101010",
        repo_id=corpus_id,
        dataset_id="default",
        config_snapshot={},
        config={},
        total=2,
        top1_hits=2,
        topk_hits=2,
        top1_accuracy=top1,
        topk_accuracy=topk,
        duration_secs=4.0,
        metrics=EvalMetrics(
            mrr=1.0,
            recall_at_5=1.0,
            recall_at_10=1.0,
            recall_at_20=1.0,
            precision_at_5=0.4,
            ndcg_at_10=1.0,
            latency_p50_ms=100.0,
            latency_p95_ms=120.0,
        ),
        results=[
            EvalResult(
                entry_id="q1",
                question="Question 1",
                retrieved_paths=["src/a.py"],
                expected_paths=["src/a.py"],
                top_paths=["src/a.py"],
                top1_path=["src/a.py"],
                top1_hit=True,
                topk_hit=True,
                reciprocal_rank=1.0,
                recall=1.0,
                latency_ms=100.0,
                duration_secs=0.1,
                docs=[EvalDoc(file_path="src/a.py", start_line=1, score=0.9, source="vector")],
                debug={},
            )
        ],
        started_at=datetime(2026, 8, 30, 10, 10, 10, tzinfo=UTC),
        completed_at=datetime(2026, 8, 30, 10, 15, 10, tzinfo=UTC),
    )


def _promptfoo_run(corpus_id: str, *, passed: int, total: int) -> PromptfooRun:
    return PromptfooRun(
        run_id=f"{corpus_id}__promptfoo",
        repo_id=corpus_id,
        provider_alias="litellm:quality-review",
        grader_alias="litellm:quality-review",
        promptfoo_version="0.0.0-test",
        total=total,
        passed=passed,
        failed=total - passed,
        skipped_entries=0,
        started_at=datetime(2026, 8, 30, 10, 20, 0, tzinfo=UTC),
        completed_at=datetime(2026, 8, 30, 10, 25, 0, tzinfo=UTC),
    )


def _benchmark_run(corpus_id: str, *, latencies: list[float]) -> BenchmarkRun:
    return BenchmarkRun(
        run_id=f"{corpus_id}__benchmark",
        repo_id=corpus_id,
        prompt="ping",
        models=[f"litellm:model-{index}" for index, _ in enumerate(latencies)],
        started_at_ms=1_788_000_000_000,
        ended_at_ms=1_788_000_001_000,
        results=[
            BenchmarkResult(
                model=f"litellm:model-{index}",
                response="ok",
                latency_ms=value,
                breakdown_ms={"generate": value},
            )
            for index, value in enumerate(latencies)
        ],
    )


@pytest.fixture
def persisted_runs(tmp_path: Path) -> Iterator[str]:
    """Write one of each run kind, exactly where the API writes them."""

    corpus_id = f"pytest_quality_{uuid.uuid4().hex[:8]}"
    _EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _PROMPTFOO_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _BENCHMARK_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    eval_path = _EVAL_RUNS_DIR / f"{corpus_id}__20260830_101010.json"
    promptfoo_path = _PROMPTFOO_RUNS_DIR / f"{corpus_id}__promptfoo.json"
    benchmark_path = _BENCHMARK_RUNS_DIR / f"{corpus_id}__benchmark.json"
    eval_path.write_text(
        _eval_run(corpus_id, top1=1.0, topk=1.0).model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    promptfoo_path.write_text(
        _promptfoo_run(corpus_id, passed=6, total=6).model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    benchmark_path.write_text(
        _benchmark_run(corpus_id, latencies=[100.0, 300.0]).model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    try:
        yield corpus_id
    finally:
        for path in (eval_path, promptfoo_path, benchmark_path):
            path.unlink(missing_ok=True)


def test_the_latest_gauges_report_the_persisted_run_without_any_run_completing(persisted_runs: str) -> None:
    """The drive's defect: the product scored 100.0% and 6/6 while the dashboard read 0%.

    This process never ran an eval, so on the old process-local gauges these
    series read 0.0 — a green zero — for runs that are on disk right now.
    """

    samples = _scrape()

    assert samples["tribrid_eval_last_top1_accuracy"] == 1.0
    assert samples["tribrid_eval_last_topk_accuracy"] == 1.0
    assert samples["tribrid_promptfoo_last_pass_ratio"] == 1.0
    assert samples["tribrid_benchmark_last_avg_latency_ms"] == 200.0


def test_a_persisted_zero_is_still_reported_as_zero(tmp_path: Path) -> None:
    """A real 0% run must still export 0 — absence is reserved for "no run".

    Without this, "render the reset state as no data" could be satisfied by
    hiding genuine quality collapses.
    """

    corpus_id = f"pytest_quality_{uuid.uuid4().hex[:8]}"
    with _no_persisted_runs(tmp_path):
        _EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (_EVAL_RUNS_DIR / f"{corpus_id}__20260830_101010.json").write_text(
            _eval_run(corpus_id, top1=0.0, topk=0.0).model_dump_json(by_alias=True, indent=2), encoding="utf-8"
        )
        samples = _scrape()

    assert samples["tribrid_eval_last_top1_accuracy"] == 0.0
    assert samples["tribrid_eval_last_topk_accuracy"] == 0.0


def test_no_persisted_run_exports_no_series_at_all(tmp_path: Path) -> None:
    """With nothing persisted the gauges must be absent, so Grafana renders "No data".

    A gauge that is always exported can only say 0, which is what made a
    restarted API read as a total quality collapse in green.
    """

    with _no_persisted_runs(tmp_path):
        samples = _scrape()
        values = latest_quality_values()

    assert samples == {}
    assert values.eval_top1_accuracy is None
    assert values.eval_topk_accuracy is None
    assert values.promptfoo_pass_ratio is None
    assert values.benchmark_average_latency_ms is None


def test_the_newest_persisted_run_wins(tmp_path: Path) -> None:
    """"Latest" means most recently persisted, not alphabetically last."""

    older = f"zzz_older_{uuid.uuid4().hex[:8]}"
    newer = f"aaa_newer_{uuid.uuid4().hex[:8]}"
    with _no_persisted_runs(tmp_path):
        _EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        older_path = _EVAL_RUNS_DIR / f"{older}__20260830_101010.json"
        newer_path = _EVAL_RUNS_DIR / f"{newer}__20260830_101010.json"
        older_path.write_text(
            _eval_run(older, top1=0.25, topk=0.25).model_dump_json(by_alias=True, indent=2), encoding="utf-8"
        )
        newer_path.write_text(
            _eval_run(newer, top1=0.75, topk=0.75).model_dump_json(by_alias=True, indent=2), encoding="utf-8"
        )
        import os

        os.utime(older_path, (1_700_000_000, 1_700_000_000))
        samples = _scrape()

    assert samples["tribrid_eval_last_top1_accuracy"] == 0.75
