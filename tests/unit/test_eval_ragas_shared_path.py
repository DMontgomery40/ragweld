"""The POST eval route and the SSE stream route must share one Ragas path.

Regression for the 2026-08-24 Phase B finding: with ``ragas_enabled: true``,
the UI's SSE eval run silently persisted ``metrics.ragas == {}`` and no
generated answers because ``/api/eval/run/stream`` had its own metrics
assembly with no Ragas leg, while ``POST /api/eval/run`` did full
generation + judging. Both routes must call the same shared helpers so the
flag means the same thing everywhere; a second divergence should fail here.
"""

from __future__ import annotations

import ast
from pathlib import Path

EVAL_SOURCE = Path(__file__).resolve().parents[2] / "server" / "api" / "eval.py"

SHARED_HELPERS = (
    "_resolve_ragas_answer_route",
    "_generate_ragas_answer",
)


def _function_node(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found in server/api/eval.py")


def _referenced_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def test_both_eval_routes_use_the_shared_ragas_helpers() -> None:
    tree = ast.parse(EVAL_SOURCE.read_text(encoding="utf-8"))

    post_core = _referenced_names(_function_node(tree, "evaluate_dataset_entries"))
    stream_route = _referenced_names(_function_node(tree, "eval_run_stream"))

    for helper in SHARED_HELPERS:
        assert helper in post_core, f"POST eval core no longer calls {helper}"
        assert helper in stream_route, f"SSE eval stream no longer calls {helper}"

    # Scoring and score attachment converge on ONE implementation each:
    # `score_samples` does the judging and `_attach_ragas_scores` does the
    # per-entry assignment + means, on both routes (the POST path reaches
    # them through `_apply_ragas_scores`; the SSE path scores per sample for
    # stream progress but must attach through the same function).
    apply_helper = _referenced_names(_function_node(tree, "_apply_ragas_scores"))
    assert "score_samples" in apply_helper
    assert "_attach_ragas_scores" in apply_helper
    assert "_apply_ragas_scores" in post_core
    assert "score_samples" in stream_route
    assert "_attach_ragas_scores" in stream_route


def _calls_named(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == name
    ]


def test_stream_route_carries_ragas_into_the_persisted_metrics() -> None:
    tree = ast.parse(EVAL_SOURCE.read_text(encoding="utf-8"))
    stream = _function_node(tree, "eval_run_stream")
    post_core = _function_node(tree, "evaluate_dataset_entries")

    # Both routes build their EvalMetrics through the one shared builder, fed the ragas means.
    for route_name, route in (("eval_run_stream", stream), ("evaluate_dataset_entries", post_core)):
        builder_calls = _calls_named(route, "_run_metrics")
        assert builder_calls, f"{route_name} no longer builds metrics through _run_metrics"
        assert _calls_named(route, "EvalMetrics") == [], f"{route_name} assembles EvalMetrics on its own"
        for call in builder_calls:
            assert len(call.args) == 3, f"{route_name} dropped an argument (headline, latencies, ragas)"

    metric_calls = _calls_named(_function_node(tree, "_run_metrics"), "EvalMetrics")
    assert len(metric_calls) == 1
    keywords = {kw.arg for kw in metric_calls[0].keywords}
    assert {"ragas", "map_at_5", "mrr"} <= keywords, "shared EvalMetrics builder dropped a metric"


def test_every_eval_path_scores_through_the_one_chunk_level_scorer() -> None:
    """POST /eval/run, the SSE stream and /eval/test share one scorer and one aggregator
    (server/evaluation/scoring.py); a second, file-level copy must fail here."""
    source = EVAL_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for route_name in ("evaluate_dataset_entries", "eval_run_stream", "test_eval_entry"):
        assert _calls_named(_function_node(tree, route_name), "_score_entry"), f"{route_name} bypasses _score_entry"
    for route_name in ("evaluate_dataset_entries", "eval_run_stream"):
        assert _calls_named(_function_node(tree, route_name), "aggregate_entry_scores"), route_name
    assert _calls_named(_function_node(tree, "_score_entry"), "score_entry")
    assert "path_matches" not in _referenced_names(tree), "file-level path matching is back in server/api/eval.py"
