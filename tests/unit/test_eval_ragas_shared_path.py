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


def test_stream_route_carries_ragas_into_the_persisted_metrics() -> None:
    tree = ast.parse(EVAL_SOURCE.read_text(encoding="utf-8"))
    stream = _function_node(tree, "eval_run_stream")

    metric_calls = [
        node
        for node in ast.walk(stream)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EvalMetrics"
    ]
    assert metric_calls, "eval_run_stream no longer constructs EvalMetrics"
    for call in metric_calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "ragas" in keywords, "stream route EvalMetrics dropped the ragas means"
