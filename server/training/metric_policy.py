from __future__ import annotations

import math
from typing import Any

from server.models.training_eval import CorpusEvalProfile, LabelKind, MetricKey


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    p = min(max(p, 0.0), 1.0)
    idx = int(math.ceil(p * (len(xs) - 1)))
    return float(xs[idx])


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(int(v))
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except Exception:
        return None


def _metric_label(metric: MetricKey, k: int) -> str:
    if metric == "mrr":
        return f"MRR@{k}"
    if metric == "ndcg":
        return f"nDCG@{k}"
    return "MAP"


def infer_corpus_eval_profile(repo_id: str, eval_rows: list[dict[str, Any]], default_k: int) -> CorpusEvalProfile:
    """
    Deterministic policy. DO NOT use randomness.

    eval_rows canonical shape (what this function expects):
      {
        "query_id": str,
        "relevance": dict[str, int|float]   # doc_id -> label (0/1 or graded 0..n)
      }

    Output:
      CorpusEvalProfile with:
        - avg_relevant_per_query
        - p95_relevant_per_query
        - label_kind
        - recommended_metric
        - recommended_k (== default_k unless default_k invalid)
        - rationale (short, UI-safe)
    """
    # Implementation requirements (no drift):
    # 1) relevant_per_query = count(label > 0) per row
    # 2) label_kind:
    #    - "graded" if any label is not in {0,1} OR any non-integer float
    #    - else "binary" if any labels exist and all are 0/1
    #    - else "unknown"
    # 3) metric selection heuristic:
    #    - if label_kind == "graded" -> "ndcg"
    #    - else if p95_relevant_per_query <= 1.0 OR avg_relevant_per_query < 1.2 -> "mrr"
    #    - else -> "ndcg"
    # 4) rationale must embed computed avg/p95 and chosen metric + k.

    k = int(default_k)
    if k < 1:
        k = 1
    if k > 200:
        k = 200

    relevant_per_query: list[float] = []

    any_labels = False
    graded = False

    for row in eval_rows or []:
        rel = row.get("relevance") or {}
        if not isinstance(rel, dict):
            rel = {}

        # 1) relevant_per_query = count(label > 0) per row
        cnt = 0
        for _, label in rel.items():
            f = _coerce_float(label)
            if f is None:
                continue
            if f > 0:
                cnt += 1
        relevant_per_query.append(float(cnt))

        # 2) label_kind detection
        for _, label in rel.items():
            f = _coerce_float(label)
            if f is None:
                # Treat non-numeric labels as graded/unknown input; choose graded to be conservative.
                any_labels = True
                graded = True
                break
            any_labels = True
            if not float(f).is_integer():
                graded = True
                break
            ival = int(f)
            if ival not in (0, 1):
                graded = True
                break
        if graded:
            break

    avg = float(sum(relevant_per_query) / len(relevant_per_query)) if relevant_per_query else 0.0
    p95 = float(_percentile(relevant_per_query, 0.95))

    if graded:
        label_kind: LabelKind = "graded"
    elif any_labels:
        label_kind = "binary"
    else:
        label_kind = "unknown"

    # 3) metric selection heuristic
    if label_kind == "graded":
        metric: MetricKey = "ndcg"
    elif p95 <= 1.0 or avg < 1.2:
        metric = "mrr"
    else:
        metric = "ndcg"

    # 4) rationale includes avg/p95 and chosen metric + k
    metric_str = _metric_label(metric, k)
    if label_kind == "graded":
        rationale = (
            f"Relevance labels are graded (avg={avg:.2f}, p95={p95:.1f}), so {metric_str} is the headline."
        )
    elif p95 <= 1.0 or avg < 1.2:
        rationale = (
            f"Most queries have ~1 relevant doc (avg={avg:.2f}, p95={p95:.1f}), so {metric_str} is the headline."
        )
    else:
        rationale = (
            f"Many queries have multiple relevant docs (avg={avg:.2f}, p95={p95:.1f}), so {metric_str} is the headline."
        )

    return CorpusEvalProfile(
        repo_id=repo_id,
        label_kind=label_kind,
        avg_relevant_per_query=avg,
        p95_relevant_per_query=p95,
        recommended_metric=metric,
        recommended_k=k,
        rationale=rationale,
    )

