from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.api.dataset import _dataset_path_for_corpus, _load_dataset
from server.config import load_config
from server.evaluation.path_match import path_matches
from server.lineage import current_bundle, ensure_current_bundle, list_bundles, load_bundle
from server.models.eval import EvalRun
from server.models.tribrid_config_model import (
    BenchmarkBreakdownDelta,
    BenchmarkObservabilitySummaryResponse,
    BenchmarkRun,
    EvalObservabilitySummaryResponse,
    LineageBundle,
    LineageRef,
    ObservabilityMetricDelta,
    PromptfooRun,
    PromptObservabilitySummaryResponse,
    TriBridConfig,
)

_ROOT = Path(__file__).resolve().parents[2]
_EVAL_RUNS_DIR = _ROOT / "data" / "eval_runs"
# `server/api/eval.py` persists Promptfoo runs beside the eval runs; that one is
# an invariant of the on-disk layout. The benchmark directory is NOT: its writer
# reads `chat.benchmark.results_path`, so the reader has to as well or an
# operator who moves it gets a permanent "No data" with nothing saying why.
_PROMPTFOO_RUNS_DIR = _EVAL_RUNS_DIR / "promptfoo"


@dataclass(frozen=True)
class LatestQualityValues:
    """The most recently persisted ML-quality numbers, or None where no run exists.

    `None` means "no run has ever been persisted", which is a different fact
    from "the last run scored zero" — the Prometheus collector encodes the
    difference by not exporting the series at all.
    """

    eval_top1_accuracy: float | None = None
    eval_topk_accuracy: float | None = None
    promptfoo_pass_ratio: float | None = None
    benchmark_average_latency_ms: float | None = None


def configured_benchmark_runs_dir() -> Path:
    """Where `server/api/benchmark.py` is currently writing benchmark runs."""

    try:
        config = load_config()
        configured = str(getattr(config.chat.benchmark, "results_path", "") or "")
    except Exception:
        configured = ""
    return _benchmark_results_dir(configured or "data/benchmarks/")


def _newest_file(directory: Path) -> Path | None:
    """The most recently written `*.json` directly inside `directory`."""

    if not directory.is_dir():
        return None
    files = [path for path in directory.glob("*.json") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


# Parsed newest-run values, keyed by the file's identity. The collector runs on
# the event loop on every Prometheus scrape, so a run that has not been
# rewritten is not re-parsed; a new or rewritten file changes the key and is.
_PARSE_CACHE: dict[str, tuple[tuple[str, float, int], Any]] = {}


def _parse_newest(kind: str, directory: Path, parse: Callable[[Path], Any]) -> Any:
    path = _newest_file(directory)
    if path is None:
        _PARSE_CACHE.pop(kind, None)
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime, stat.st_size)
    cached = _PARSE_CACHE.get(kind)
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        value = parse(path)
    except Exception:
        # A file that does not validate has no usable number in it; absence is
        # the honest answer and the caller renders "No data".
        return None
    _PARSE_CACHE[kind] = (key, value)
    return value


def latest_quality_values(
    *,
    eval_dir: Path | None = None,
    promptfoo_dir: Path | None = None,
    benchmark_dir: Path | None = None,
) -> LatestQualityValues:
    """Read the newest persisted eval / Promptfoo / benchmark run off disk.

    Called at Prometheus scrape time, so the dashboard's "Latest" gauges are a
    view of the persisted runs rather than of process memory. Restarting the
    API therefore cannot zero them.

    The directories are parameters so a test can own an empty tree instead of
    borrowing (and moving) the operator's real one.
    """

    run = _parse_newest(
        "eval",
        eval_dir if eval_dir is not None else _EVAL_RUNS_DIR,
        lambda path: EvalRun.model_validate(json.loads(path.read_text(encoding="utf-8"))),
    )
    eval_top1 = float(run.top1_accuracy) if run is not None else None
    eval_topk = float(run.topk_accuracy) if run is not None else None

    promptfoo = _parse_newest(
        "promptfoo",
        promptfoo_dir if promptfoo_dir is not None else _PROMPTFOO_RUNS_DIR,
        lambda path: PromptfooRun.model_validate_json(path.read_text(encoding="utf-8")),
    )
    promptfoo_ratio = (
        float(promptfoo.passed) / float(promptfoo.total)
        if promptfoo is not None and promptfoo.total
        else None
    )

    benchmark = _parse_newest(
        "benchmark",
        benchmark_dir if benchmark_dir is not None else configured_benchmark_runs_dir(),
        lambda path: BenchmarkRun.model_validate(json.loads(path.read_text(encoding="utf-8"))),
    )
    benchmark_latency: float | None = None
    if benchmark is not None:
        latencies = [float(item.latency_ms) for item in (benchmark.results or []) if item.latency_ms is not None]
        if latencies:
            benchmark_latency = sum(latencies) / len(latencies)

    return LatestQualityValues(
        eval_top1_accuracy=eval_top1,
        eval_topk_accuracy=eval_topk,
        promptfoo_pass_ratio=promptfoo_ratio,
        benchmark_average_latency_ms=benchmark_latency,
    )


def _path_matches(expected: str, actual: str) -> bool:
    return path_matches(expected, actual)


def _metric_delta(current_value: float | None, previous_value: float | None) -> ObservabilityMetricDelta:
    if current_value is None:
        return ObservabilityMetricDelta(current_value=None, previous_value=previous_value)
    if previous_value is None:
        return ObservabilityMetricDelta(current_value=current_value, previous_value=None)
    absolute = current_value - previous_value
    percent = None
    if abs(previous_value) > 1e-12:
        percent = (absolute / previous_value) * 100.0
    return ObservabilityMetricDelta(
        current_value=current_value,
        previous_value=previous_value,
        absolute_delta=absolute,
        percent_delta=percent,
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = int(math.ceil(max(0.0, min(1.0, fraction)) * (len(ordered) - 1)))
    return float(ordered[index])


def _datetime_from_ms(value: int | None) -> datetime | None:
    if value is None or value <= 0:
        return None
    return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _load_eval_runs(repo_id: str | None, *, limit: int = 2) -> list[EvalRun]:
    _EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs: list[EvalRun] = []
    for path in sorted(_EVAL_RUNS_DIR.glob("*.json"), reverse=True):
        if repo_id and not path.stem.startswith(f"{repo_id}__"):
            continue
        try:
            run = EvalRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        runs.append(run)
        if len(runs) >= limit:
            break
    return runs


def _benchmark_results_dir(path_str: str) -> Path:
    # Read-only: this resolves where benchmark runs are read from at scrape time.
    # It must not create the directory -- a Prometheus scrape (a read) creating
    # `data/benchmarks/` is a write-on-read side effect. The writer
    # (server/api/benchmark.py) creates it; a missing dir here simply reads as
    # "no runs yet" because the callers glob it and tolerate absence.
    path = Path(str(path_str or "data/benchmarks/"))
    if not path.is_absolute():
        path = _ROOT / path
    return path


def _load_benchmark_runs(config: TriBridConfig, repo_id: str | None, *, limit: int = 2) -> list[BenchmarkRun]:
    root = _benchmark_results_dir(str(getattr(config.chat.benchmark, "results_path", "data/benchmarks/") or "data/benchmarks/"))
    runs: list[BenchmarkRun] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            raw.setdefault("prompt", "")
            raw.setdefault("models", [str(item.get("model") or "") for item in raw.get("results", []) if isinstance(item, dict)])
            raw.setdefault("corpus_id", raw.get("repo_id"))
            raw.setdefault("input_bundle_id", None)
            raw.setdefault("bundle_id", None)
            raw.setdefault("lineage_ref", None)
            run = BenchmarkRun.model_validate(raw)
        except Exception:
            continue
        if repo_id and str(run.repo_id or "").strip() != str(repo_id).strip():
            continue
        runs.append(run)
        if len(runs) >= limit:
            break
    return runs


def _bundle_prompt_set(repo_id: str | None, bundle_id: str | None) -> LineageRef | None:
    if not repo_id or not bundle_id:
        return None
    try:
        bundle = load_bundle(repo_id=repo_id, bundle_id=bundle_id)
    except Exception:
        return None
    return bundle.prompt_set


def _current_bundle(repo_id: str, config: TriBridConfig) -> LineageBundle | None:
    bundle = current_bundle(repo_id)
    if bundle is not None:
        return bundle
    try:
        dataset = _load_dataset(corpus_id=repo_id)
        return ensure_current_bundle(
            repo_id=repo_id,
            cfg=config,
            dataset_rows=[row.model_dump(mode="json", by_alias=True) for row in dataset],
            dataset_path=str(_dataset_path_for_corpus(repo_id)),
        )
    except Exception:
        return None


def _map_at_k(run: EvalRun, k: int = 5) -> float | None:
    if not run.results:
        return None
    average_precisions: list[float] = []
    for result in run.results:
        expected = list(result.expected_paths or [])
        if not expected:
            average_precisions.append(0.0)
            continue
        hits = 0
        score = 0.0
        for index, candidate in enumerate(list(result.retrieved_paths or [])[:k], start=1):
            if any(_path_matches(exp, candidate) for exp in expected):
                hits += 1
                score += hits / float(index)
        average_precisions.append(score / float(min(len(expected), k)))
    return _mean(average_precisions)


def build_eval_observability_summary(config: TriBridConfig, repo_id: str | None) -> EvalObservabilitySummaryResponse:
    if not repo_id:
        return EvalObservabilitySummaryResponse(ok=True, repo_id=None, operator_hint="Select a corpus to evaluate regressions.")

    runs = _load_eval_runs(repo_id, limit=2)
    latest = runs[0] if runs else None
    previous = runs[1] if len(runs) > 1 else None
    if latest is None:
        return EvalObservabilitySummaryResponse(
            ok=True,
            repo_id=repo_id,
            operator_hint="No eval runs recorded for this corpus yet. Run Eval Analysis to establish a baseline.",
        )

    improved = 0
    regressed = 0
    stable = 0
    if previous is not None:
        previous_by_entry = {str(item.entry_id): item for item in previous.results}
        for latest_result in latest.results:
            prev = previous_by_entry.get(str(latest_result.entry_id))
            if prev is None:
                continue
            latest_rr = float(latest_result.reciprocal_rank or 0.0)
            previous_rr = float(prev.reciprocal_rank or 0.0)
            if latest_rr > previous_rr + 1e-9:
                improved += 1
            elif latest_rr + 1e-9 < previous_rr:
                regressed += 1
            else:
                stable += 1

    freshness_minutes = None
    if latest.completed_at is not None:
        freshness_minutes = max(0.0, (datetime.now(UTC) - latest.completed_at).total_seconds() / 60.0)

    latest_prompt_set = _bundle_prompt_set(repo_id, latest.bundle_id)
    previous_prompt_set = _bundle_prompt_set(repo_id, previous.bundle_id if previous is not None else None)

    hint = "Latest eval run is fresh."
    if previous is None:
        hint = "Only one eval run is present. Run a second eval to unlock regression comparison."
    elif regressed > improved or (latest.top1_accuracy < previous.top1_accuracy):
        hint = "Eval quality regressed. Open Eval Analysis and inspect the changed questions and prompt/config lineage."
    elif freshness_minutes is not None and freshness_minutes > 24 * 60:
        hint = "Eval baseline is stale. Re-run Eval Analysis before trusting the current prompt/config state."

    return EvalObservabilitySummaryResponse(
        ok=True,
        repo_id=repo_id,
        latest_run_id=latest.run_id,
        previous_run_id=previous.run_id if previous is not None else None,
        latest_completed_at=latest.completed_at,
        freshness_minutes=freshness_minutes,
        total_questions=int(latest.total or len(latest.results)),
        ai_comparison_ready=previous is not None,
        top1_accuracy=_metric_delta(float(latest.top1_accuracy), float(previous.top1_accuracy) if previous is not None else None),
        topk_accuracy=_metric_delta(float(latest.topk_accuracy), float(previous.topk_accuracy) if previous is not None else None),
        mrr=_metric_delta(float(latest.metrics.mrr), float(previous.metrics.mrr) if previous is not None else None),
        ndcg_at_10=_metric_delta(
            float(latest.metrics.ndcg_at_10),
            float(previous.metrics.ndcg_at_10) if previous is not None else None,
        ),
        map_at_5=_metric_delta(
            _map_at_k(latest, 5),
            _map_at_k(previous, 5) if previous is not None else None,
        ),
        recall_at_5=_metric_delta(
            float(latest.metrics.recall_at_5),
            float(previous.metrics.recall_at_5) if previous is not None else None,
        ),
        recall_at_10=_metric_delta(
            float(latest.metrics.recall_at_10),
            float(previous.metrics.recall_at_10) if previous is not None else None,
        ),
        improved_count=improved,
        regressed_count=regressed,
        stable_count=stable,
        latest_bundle_id=latest.bundle_id,
        latest_prompt_set_ref=latest_prompt_set,
        previous_prompt_set_ref=previous_prompt_set,
        operator_hint=hint,
    )


def _average_breakdown(run: BenchmarkRun) -> dict[str, float]:
    aggregates: dict[str, list[float]] = {}
    for result in run.results:
        for phase, value in (result.breakdown_ms or {}).items():
            if value is None:
                continue
            aggregates.setdefault(str(phase), []).append(float(value))
    return {phase: float(sum(values) / len(values)) for phase, values in aggregates.items() if values}


def _benchmark_success_rate(run: BenchmarkRun) -> float | None:
    total = len(run.results)
    if total <= 0:
        return None
    successes = sum(1 for item in run.results if not str(item.error or "").strip())
    return float(successes) / float(total)


def build_benchmark_observability_summary(
    config: TriBridConfig,
    repo_id: str | None,
) -> BenchmarkObservabilitySummaryResponse:
    runs = _load_benchmark_runs(config, repo_id, limit=2)
    latest = runs[0] if runs else None
    previous = runs[1] if len(runs) > 1 else None
    if latest is None:
        return BenchmarkObservabilitySummaryResponse(
            ok=True,
            repo_id=repo_id,
            operator_hint="No benchmark runs recorded yet. Use Benchmark to compare models and establish a runtime baseline.",
        )

    latest_latencies = [float(item.latency_ms) for item in latest.results if item.latency_ms is not None]
    previous_latencies = [float(item.latency_ms) for item in previous.results if item.latency_ms is not None] if previous else []
    latest_lengths = [float(len(str(item.response or ""))) for item in latest.results]
    previous_lengths = [float(len(str(item.response or ""))) for item in previous.results] if previous else []

    latest_breakdown = _average_breakdown(latest)
    previous_breakdown = _average_breakdown(previous) if previous is not None else {}
    phases = sorted(set(latest_breakdown) | set(previous_breakdown))
    breakdown_deltas = [
        BenchmarkBreakdownDelta(
            phase=phase,
            current_ms=latest_breakdown.get(phase),
            previous_ms=previous_breakdown.get(phase),
            delta_ms=(
                (latest_breakdown.get(phase) or 0.0) - (previous_breakdown.get(phase) or 0.0)
                if phase in latest_breakdown and phase in previous_breakdown
                else None
            ),
        )
        for phase in phases
    ]

    latest_prompt_set = _bundle_prompt_set(repo_id, latest.bundle_id)
    previous_prompt_set = _bundle_prompt_set(repo_id, previous.bundle_id if previous is not None else None)

    hint = "Latest benchmark run is available for drilldown."
    if previous is None:
        hint = "Only one benchmark run is present. Run another comparison to unlock delta tracking."
    elif any(float(item.delta_ms or 0.0) > 250.0 for item in breakdown_deltas):
        hint = "Benchmark latency regressed. Compare the latest run in Benchmark and inspect the changed provider/model route."
    elif sum(1 for item in latest.results if str(item.error or "").strip()) > 0:
        hint = "Benchmark run recorded model errors. Open Benchmark to inspect failing providers."

    return BenchmarkObservabilitySummaryResponse(
        ok=True,
        repo_id=repo_id,
        latest_run_id=latest.run_id,
        previous_run_id=previous.run_id if previous is not None else None,
        latest_started_at=_datetime_from_ms(int(latest.started_at_ms or 0)),
        latest_model_count=len(latest.results),
        latest_error_count=sum(1 for item in latest.results if str(item.error or "").strip()),
        previous_error_count=sum(1 for item in previous.results if str(item.error or "").strip()) if previous is not None else 0,
        provider_routes=[str(item) for item in latest.models if str(item).strip()],
        average_latency_ms=_metric_delta(_mean(latest_latencies), _mean(previous_latencies)),
        p95_latency_ms=_metric_delta(_percentile(latest_latencies, 0.95), _percentile(previous_latencies, 0.95)),
        response_length_mean=_metric_delta(_mean(latest_lengths), _mean(previous_lengths)),
        success_rate=_metric_delta(_benchmark_success_rate(latest), _benchmark_success_rate(previous) if previous is not None else None),
        breakdown_deltas=breakdown_deltas,
        latest_bundle_id=latest.bundle_id,
        latest_prompt_set_ref=latest_prompt_set,
        previous_prompt_set_ref=previous_prompt_set,
        operator_hint=hint,
    )


def build_prompt_observability_summary(
    config: TriBridConfig,
    repo_id: str | None,
) -> PromptObservabilitySummaryResponse:
    if not repo_id:
        return PromptObservabilitySummaryResponse(
            ok=True,
            repo_id=None,
            operator_hint="Select a corpus to correlate prompt changes with eval and benchmark runs.",
        )

    current = _current_bundle(repo_id, config)
    bundles = list_bundles(repo_id=repo_id, limit=10)
    unique_prompt_sets: list[LineageRef] = []
    for bundle in bundles:
        prompt_set = bundle.prompt_set
        if prompt_set is None:
            continue
        if any(existing.version_id == prompt_set.version_id for existing in unique_prompt_sets):
            continue
        unique_prompt_sets.append(prompt_set)
    previous_prompt_set = unique_prompt_sets[1] if len(unique_prompt_sets) > 1 else None

    eval_summary = build_eval_observability_summary(config, repo_id)
    benchmark_summary = build_benchmark_observability_summary(config, repo_id)

    current_prompt_set = current.prompt_set if current is not None else None
    changed_since_latest_eval = bool(
        current_prompt_set
        and eval_summary.latest_prompt_set_ref
        and current_prompt_set.version_id != eval_summary.latest_prompt_set_ref.version_id
    )
    changed_since_latest_benchmark = bool(
        current_prompt_set
        and benchmark_summary.latest_prompt_set_ref
        and current_prompt_set.version_id != benchmark_summary.latest_prompt_set_ref.version_id
    )
    eval_regression_suspected = bool(
        changed_since_latest_eval
        and (
            int(eval_summary.regressed_count or 0) > int(eval_summary.improved_count or 0)
            or float(eval_summary.top1_accuracy.absolute_delta or 0.0) < 0.0
        )
    )
    benchmark_regression_suspected = bool(
        changed_since_latest_benchmark
        and (
            float(benchmark_summary.average_latency_ms.absolute_delta or 0.0) > 0.0
            or int(benchmark_summary.latest_error_count or 0) > int(benchmark_summary.previous_error_count or 0)
        )
    )
    pending_verification = changed_since_latest_eval or changed_since_latest_benchmark

    hint = "Prompt set is aligned with the latest eval and benchmark evidence."
    if pending_verification:
        hint = "Prompt set changed since the latest eval/benchmark evidence. Re-run both before trusting the current stack."
    if eval_regression_suspected or benchmark_regression_suspected:
        hint = "Prompt change appears correlated with downstream regression. Open System Prompts, Eval Analysis, and Benchmark together."

    return PromptObservabilitySummaryResponse(
        ok=True,
        repo_id=repo_id,
        current_prompt_set_ref=current_prompt_set,
        previous_prompt_set_ref=previous_prompt_set,
        latest_eval_run_id=eval_summary.latest_run_id,
        latest_eval_prompt_set_ref=eval_summary.latest_prompt_set_ref,
        latest_benchmark_run_id=benchmark_summary.latest_run_id,
        latest_benchmark_prompt_set_ref=benchmark_summary.latest_prompt_set_ref,
        changed_since_latest_eval=changed_since_latest_eval,
        changed_since_latest_benchmark=changed_since_latest_benchmark,
        eval_regression_suspected=eval_regression_suspected,
        benchmark_regression_suspected=benchmark_regression_suspected,
        pending_verification=pending_verification,
        recent_prompt_set_count=len(unique_prompt_sets),
        operator_hint=hint,
    )
