from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from server.training.triplet_rows import (
    load_triplet_rows,
    recover_parked_replacement,
    triplets_lock,
)


@dataclass(frozen=True)
class Triplet:
    query: str
    positive: str
    negative: str


@dataclass(frozen=True)
class MaterializedTriplet:
    query: str
    positive_text: str
    negative_text: str


def load_triplets(path: Path, *, limit: int | None = None) -> list[Triplet]:
    """Load the validated triplets artifact (a corrupt row raises; nothing is skipped silently).

    A publish that crashed mid-transaction is repaired first, under the artifact lock, so training
    never reads a half-published state."""
    with triplets_lock(path):
        recover_parked_replacement(path)
        rows = load_triplet_rows(path)
    out: list[Triplet] = []
    for row in rows:
        out.append(Triplet(query=row.query, positive=row.positive, negative=row.negative))
        if limit is not None and limit > 0 and len(out) >= limit:
            break
    return out


def _resolve_doc_path(*, corpus_root: Path, doc_id: str) -> Path | None:
    p = Path(str(doc_id or "").strip())
    if not str(p):
        return None

    # Security: triplets must only reference corpus-relative paths. Absolute paths and
    # path traversal (.. segments) are rejected so training cannot read arbitrary files.
    if p.is_absolute():
        return None

    try:
        root = corpus_root.resolve()
        resolved = (corpus_root / p).resolve()
    except Exception:
        return None

    try:
        resolved.relative_to(root)
    except Exception:
        return None
    return resolved


def _read_text(path: Path, *, max_chars: int) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if max_chars <= 0:
        return ""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars]


def materialize_triplets(
    triplets: list[Triplet],
    *,
    corpus_root: Path,
    snippet_chars: int,
    max_triplets: int | None = None,
) -> tuple[list[MaterializedTriplet], dict[str, int]]:
    """Load file contents for (positive, negative) doc_ids and return materialized triplets.

    Returns (materialized_triplets, stats) where stats includes counts of skipped items.
    """
    out: list[MaterializedTriplet] = []
    missing_pos = 0
    missing_neg = 0
    empty_pos = 0
    empty_neg = 0

    for t in triplets:
        pos_path = _resolve_doc_path(corpus_root=corpus_root, doc_id=t.positive)
        neg_path = _resolve_doc_path(corpus_root=corpus_root, doc_id=t.negative)

        if pos_path is None:
            missing_pos += 1
            continue
        if neg_path is None:
            missing_neg += 1
            continue

        if not pos_path.exists():
            missing_pos += 1
            continue
        if not neg_path.exists():
            missing_neg += 1
            continue

        pos_text = _read_text(pos_path, max_chars=snippet_chars).strip()
        neg_text = _read_text(neg_path, max_chars=snippet_chars).strip()
        if not pos_text:
            empty_pos += 1
            continue
        if not neg_text:
            empty_neg += 1
            continue

        out.append(MaterializedTriplet(query=t.query, positive_text=pos_text, negative_text=neg_text))
        if max_triplets is not None and max_triplets > 0 and len(out) >= max_triplets:
            break

    return out, {
        "triplets_in": len(triplets),
        "triplets_out": len(out),
        "missing_positive": missing_pos,
        "missing_negative": missing_neg,
        "empty_positive": empty_pos,
        "empty_negative": empty_neg,
    }


def _pair_metrics_from_scores(pos_scores: list[float], neg_scores: list[float]) -> dict[str, float]:
    if not pos_scores or not neg_scores or len(pos_scores) != len(neg_scores):
        return {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}

    rr_vals: list[float] = []
    ndcg_vals: list[float] = []
    ap_vals: list[float] = []

    for ps, ns in zip(pos_scores, neg_scores, strict=True):
        rank: float
        if ps > ns:
            rank = 1.0
        elif ps < ns:
            rank = 2.0
        else:
            # Stable tie handling (midpoint)
            rank = 1.5

        rr = 1.0 / float(rank)
        rr_vals.append(rr)
        ap_vals.append(rr)

        # One relevant item => nDCG depends only on the rank.
        # rank=1 => 1.0; rank=2 => 1/log2(3); rank=1.5 => linear interpolation.
        if rank == 1:
            ndcg = 1.0
        elif rank == 2:
            ndcg = 1.0 / math.log2(3.0)
        else:
            ndcg = (1.0 + (1.0 / math.log2(3.0))) / 2.0
        ndcg_vals.append(float(ndcg))

    return {
        "mrr": float(sum(rr_vals) / len(rr_vals)),
        "ndcg": float(sum(ndcg_vals) / len(ndcg_vals)),
        "map": float(sum(ap_vals) / len(ap_vals)),
    }
