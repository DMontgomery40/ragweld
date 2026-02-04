from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal


@dataclass(frozen=True)
class _QueryEvent:
    event_id: str
    query: str
    top_paths: tuple[str, ...]


@dataclass(frozen=True)
class _FeedbackEvent:
    event_id: str | None
    signal: str | None
    doc_id: str | None


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    def _gen() -> Iterable[dict[str, Any]]:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                ln = line.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    yield obj
    return _gen()


def mine_triplets_from_query_log(
    *,
    log_path: Path,
    triplets_path: Path,
    mine_mode: Literal["replace", "append"] = "replace",
    max_triplets: int | None = None,
    corpus_id: str | None = None,
) -> dict[str, Any]:
    """Mine (query, positive, negative) triplets from the JSONL query/feedback log.

    This is a minimal, deterministic miner intended to bootstrap learning-reranker data.
    It relies on:
    - query events (kind in {"chat","search"}) providing: event_id, query, top_paths
    - feedback events (kind/type == "feedback") providing: event_id, signal, optional doc_id
    """
    queries: dict[str, _QueryEvent] = {}
    feedback_events: list[_FeedbackEvent] = []

    for obj in _iter_jsonl(log_path):
        kind = str(obj.get("kind") or obj.get("type") or "").strip().lower()
        if kind in {"chat", "search", "query"}:
            if corpus_id:
                cid = str(corpus_id).strip()
                obj_corpus_id = obj.get("corpus_id")
                obj_corpus_ids = obj.get("corpus_ids")
                ok_scope = False
                if isinstance(obj_corpus_id, str) and obj_corpus_id.strip() == cid:
                    ok_scope = True
                elif isinstance(obj_corpus_ids, list) and any(
                    isinstance(x, str) and x.strip() == cid for x in obj_corpus_ids
                ):
                    ok_scope = True
                if not ok_scope:
                    continue

            event_id = obj.get("event_id")
            query = obj.get("query") or obj.get("query_raw")
            top_paths = obj.get("top_paths")
            if not isinstance(event_id, str) or not isinstance(query, str):
                continue
            if not isinstance(top_paths, list) or not all(isinstance(p, str) for p in top_paths):
                top_paths = []
            queries[event_id] = _QueryEvent(event_id=event_id, query=query, top_paths=tuple(top_paths))
            continue

        if kind == "feedback":
            feedback_events.append(
                _FeedbackEvent(
                    event_id=obj.get("event_id") if isinstance(obj.get("event_id"), str) else None,
                    signal=obj.get("signal") if isinstance(obj.get("signal"), str) else None,
                    doc_id=obj.get("doc_id") if isinstance(obj.get("doc_id"), str) else None,
                )
            )

    positive_signals = {"thumbsup", "star4", "star5", "click"}

    triplets: list[dict[str, str]] = []
    used: set[tuple[str, str, str]] = set()

    def _maybe_add_triplet(query: str, positive: str, negative: str) -> None:
        if not query or not positive or not negative:
            return
        key = (query, positive, negative)
        if key in used:
            return
        used.add(key)
        triplets.append({"query": query, "positive": positive, "negative": negative})

    feedback_with_event = 0
    mined_from_feedback = 0

    for fb in feedback_events:
        if not fb.event_id or not fb.signal:
            continue
        feedback_with_event += 1
        if fb.signal.strip().lower() not in positive_signals:
            continue
        q = queries.get(fb.event_id)
        if q is None:
            continue

        positive: str | None = None
        if fb.signal == "click" and fb.doc_id:
            positive = fb.doc_id
        else:
            positive = q.top_paths[0] if q.top_paths else None

        if not positive:
            continue

        negative: str | None = None
        for p in q.top_paths:
            if p != positive:
                negative = p
                break
        if not negative:
            continue

        _maybe_add_triplet(q.query, positive, negative)
        mined_from_feedback += 1
        if max_triplets is not None and len(triplets) >= max_triplets:
            break

    triplets_path.parent.mkdir(parents=True, exist_ok=True)
    if mine_mode == "replace":
        triplets_path.write_text("", encoding="utf-8")

    with triplets_path.open("a", encoding="utf-8") as out:
        for t in triplets:
            out.write(json.dumps(t, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "query_events": len(queries),
        "feedback_events": len(feedback_events),
        "feedback_with_event_id": feedback_with_event,
        "triplets_mined": len(triplets),
        "triplets_path": str(triplets_path),
        "mined_from_feedback_events": mined_from_feedback,
    }
