"""The "Latest" ML-quality gauges are a view of the persisted runs, not of process memory.

Every test writes real run files and scrapes a real Prometheus registry through
the real collector. Nothing is patched, and no test calls the `.set()` path that
used to populate these series — which is the point: a freshly started process
must already report the truth.

The tests own their run directories rather than moving the operator's aside:
`LatestMLQualityCollector` takes the three directories, so an "empty tree" case
is an empty `tmp_path`, not `shutil.move` of `data/eval_runs` with a `finally`
that a SIGKILL can skip.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from server.models.eval import EvalDoc, EvalMetrics, EvalResult, EvalRun
from server.models.tribrid_config_model import BenchmarkResult, BenchmarkRun, PromptfooRun
from server.observability.metrics import LatestMLQualityCollector
from server.observability.ml_quality import configured_benchmark_runs_dir, latest_quality_values

_GAUGES = (
    "tribrid_eval_last_top1_accuracy",
    "tribrid_eval_last_topk_accuracy",
    "tribrid_promptfoo_last_pass_ratio",
    "tribrid_benchmark_last_avg_latency_ms",
)


def _scrape(root: Path) -> dict[str, float]:
    """Every ML-quality sample the real collector exposes over `root`'s tree."""

    registry = CollectorRegistry()
    registry.register(
        LatestMLQualityCollector(
            eval_dir=root / "eval_runs",
            promptfoo_dir=root / "eval_runs" / "promptfoo",
            benchmark_dir=root / "benchmarks",
        )
    )
    samples: dict[str, float] = {}
    for line in generate_latest(registry).decode("utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, _, value = line.partition(" ")
        if name in _GAUGES:
            samples[name] = float(value)
    return samples


def _write_eval(root: Path, run: EvalRun) -> Path:
    directory = root / "eval_runs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.run_id}.json"
    path.write_text(run.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    return path


def _write_promptfoo(root: Path, run: PromptfooRun) -> Path:
    directory = root / "eval_runs" / "promptfoo"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.run_id}.json"
    path.write_text(run.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    return path


def _write_benchmark(root: Path, run: BenchmarkRun) -> Path:
    directory = root / "benchmarks"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.run_id}.json"
    path.write_text(run.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    return path


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


def test_the_latest_gauges_report_the_persisted_run_without_any_run_completing(tmp_path: Path) -> None:
    """The drive's defect: the product scored 100.0% and 6/6 while the dashboard read 0%.

    This process never ran an eval, so on the old process-local gauges these
    series read 0.0 — a green zero — for runs that are on disk right now.
    """

    corpus_id = f"pytest_quality_{uuid.uuid4().hex[:8]}"
    _write_eval(tmp_path, _eval_run(corpus_id, top1=1.0, topk=1.0))
    _write_promptfoo(tmp_path, _promptfoo_run(corpus_id, passed=6, total=6))
    _write_benchmark(tmp_path, _benchmark_run(corpus_id, latencies=[100.0, 300.0]))

    samples = _scrape(tmp_path)

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
    _write_eval(tmp_path, _eval_run(corpus_id, top1=0.0, topk=0.0))

    samples = _scrape(tmp_path)

    assert samples["tribrid_eval_last_top1_accuracy"] == 0.0
    assert samples["tribrid_eval_last_topk_accuracy"] == 0.0


def test_no_persisted_run_exports_no_series_at_all(tmp_path: Path) -> None:
    """With nothing persisted the gauges must be absent, so Grafana renders "No data".

    A gauge that is always exported can only say 0, which is what made a
    restarted API read as a total quality collapse in green.
    """

    samples = _scrape(tmp_path)
    values = latest_quality_values(
        eval_dir=tmp_path / "eval_runs",
        promptfoo_dir=tmp_path / "eval_runs" / "promptfoo",
        benchmark_dir=tmp_path / "benchmarks",
    )

    assert samples == {}
    assert values.eval_top1_accuracy is None
    assert values.eval_topk_accuracy is None
    assert values.promptfoo_pass_ratio is None
    assert values.benchmark_average_latency_ms is None


def test_the_newest_persisted_run_wins(tmp_path: Path) -> None:
    """"Latest" means most recently persisted, not alphabetically last."""

    older = f"zzz_older_{uuid.uuid4().hex[:8]}"
    newer = f"aaa_newer_{uuid.uuid4().hex[:8]}"
    older_path = _write_eval(tmp_path, _eval_run(older, top1=0.25, topk=0.25))
    _write_eval(tmp_path, _eval_run(newer, top1=0.75, topk=0.75))
    os.utime(older_path, (1_700_000_000, 1_700_000_000))

    assert _scrape(tmp_path)["tribrid_eval_last_top1_accuracy"] == 0.75


def test_a_rewritten_run_is_re_read_rather_than_served_from_the_cache(tmp_path: Path) -> None:
    """The scrape-time cache is keyed on the file, so a new run must not be stale.

    The collector runs on the event loop on every scrape; caching the parse is
    what keeps that cheap, and this is the hole it could have opened.
    """

    corpus_id = f"pytest_quality_{uuid.uuid4().hex[:8]}"
    first = _write_eval(tmp_path, _eval_run(corpus_id, top1=0.10, topk=0.10))
    assert _scrape(tmp_path)["tribrid_eval_last_top1_accuracy"] == 0.10

    first.write_text(
        _eval_run(corpus_id, top1=0.90, topk=0.90).model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    os.utime(first, (1_800_000_000, 1_800_000_000))

    assert _scrape(tmp_path)["tribrid_eval_last_top1_accuracy"] == 0.90


def test_the_benchmark_directory_follows_the_configured_results_path() -> None:
    """`server/api/benchmark.py` writes to chat.benchmark.results_path.

    Reading a hardcoded `data/benchmarks` would give an operator who moves it a
    permanent "Latest Benchmark Avg Latency — No data" with nothing on screen
    saying why: a quieter version of the defect M-17 was filed for.
    """

    from server.config import load_config

    configured = str(load_config().chat.benchmark.results_path)
    resolved = configured_benchmark_runs_dir()

    assert resolved.is_absolute()
    assert resolved == (Path(configured) if Path(configured).is_absolute() else Path(__file__).resolve().parents[2] / configured)


def test_the_collector_is_registered_in_the_default_registry() -> None:
    """The tests above use their own registry; production uses the default one.

    Without this, deleting `REGISTRY.register(...)` would leave every test above
    green while the dashboard went back to permanent "No data".
    """

    from prometheus_client import REGISTRY

    registered = [
        collector
        for collector in REGISTRY._collector_to_names  # noqa: SLF001 - the only way to ask
        if isinstance(collector, LatestMLQualityCollector)
    ]
    assert len(registered) == 1


def test_every_persisted_benchmark_run_on_this_host_validates_unpatched() -> None:
    """The reader validates the writer's own output, with no defaults filled in.

    `latest_quality_values` used to `setdefault` prompt/models/corpus_id before
    validating — the lossy-payload-guessing smell CLAUDE.md bans, and it guessed
    `models` from the results rather than reading it. Every run this host has
    written validates without them.
    """

    directory = configured_benchmark_runs_dir()
    runs = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not runs:
        pytest.skip("this host has persisted no benchmark runs to validate against")
    for path in runs:
        BenchmarkRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
