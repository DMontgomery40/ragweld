"""Reranker triplet mining from real retrieval signal.

Two sources, one validated output file (`training.tribrid_triplets_path`,
JSONL rows of :class:`server.training.triplet_rows.TripletRow`):

- feedback events on the query log (thumbs-up / high star rating / click)
  correlated with the query event they rate, and
- persisted eval runs, where every `EvalResult` is a real retrieval trace for a
  real question: the labelled `expected_paths` are positives and the
  highest-ranked retrieved paths that are *not* expected are hard negatives.

Guards: placeholder queries are rejected (`server.evaluation.query_guard`),
positives are written as the canonical retrieved path that matched the label
(so the trainer can materialize them), and a candidate negative whose text
contains the entry's expected answer is skipped — a duplicate email that also
answers the question must not be taught as irrelevant. No negatives are
invented from directory layout.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, overload

from pydantic import ValidationError

from server.evaluation.path_match import path_matches
from server.evaluation.query_guard import is_real_query
from server.evaluation.text_tokens import normalize_text, phrase_in
from server.models.tribrid_config_model import EvalResult
from server.training.triplet_rows import (
    TripletRow,
    load_triplet_rows,
    recover_parked_replacement,
    triplets_lock,
    write_triplet_rows,
)

FEEDBACK_SOURCE = "feedback"
POSITIVE_FEEDBACK_SIGNALS = frozenset({"thumbsup", "star4", "star5", "click"})
_MIN_ANSWER_CHARS_FOR_LEAK_CHECK = 2

NegativeTextLoader = Callable[[str], str | None]


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


def _event_in_scope(obj: dict[str, Any], corpus_id: str | None) -> bool:
    if not corpus_id:
        return True
    cid = corpus_id.strip()
    obj_corpus_id = obj.get("corpus_id")
    if isinstance(obj_corpus_id, str) and obj_corpus_id.strip() == cid:
        return True
    obj_corpus_ids = obj.get("corpus_ids")
    return isinstance(obj_corpus_ids, list) and any(isinstance(x, str) and x.strip() == cid for x in obj_corpus_ids)


def _row(query: str, positive: str, negative: str, source: str) -> TripletRow | None:
    try:
        return TripletRow(query=query, positive=positive, negative=negative, source=source)
    except ValidationError:
        return None


def _mine_feedback_triplets(
    *,
    log_path: Path,
    corpus_id: str | None,
) -> tuple[list[TripletRow], dict[str, int]]:
    queries: dict[str, _QueryEvent] = {}
    feedback_events: list[_FeedbackEvent] = []

    for obj in _iter_jsonl(log_path):
        kind = str(obj.get("kind") or obj.get("type") or "").strip().lower()
        if kind in {"chat", "search", "query"}:
            if not _event_in_scope(obj, corpus_id):
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

    rows: list[TripletRow] = []
    feedback_with_event = 0
    rejected_placeholder = 0
    for fb in feedback_events:
        if not fb.event_id or not fb.signal:
            continue
        feedback_with_event += 1
        if fb.signal.strip().lower() not in POSITIVE_FEEDBACK_SIGNALS:
            continue
        q = queries.get(fb.event_id)
        if q is None:
            continue
        if not is_real_query(q.query):
            rejected_placeholder += 1
            continue
        positive = fb.doc_id if (fb.signal == "click" and fb.doc_id) else (q.top_paths[0] if q.top_paths else None)
        if not positive:
            continue
        negative = next((p for p in q.top_paths if p != positive), None)
        if not negative:
            continue
        row = _row(q.query, positive, negative, FEEDBACK_SOURCE)
        if row is not None:
            rows.append(row)

    return rows, {
        "query_events": len(queries),
        "feedback_events": len(feedback_events),
        "feedback_with_event_id": feedback_with_event,
        "feedback_rejected_placeholder": rejected_placeholder,
    }


def answer_appears_in(answer: str, document_text: str) -> bool:
    """Whole-token phrase containment in any script: `EJM` matches `... to EJM.` but not `ejmx`."""
    return phrase_in(answer, document_text)


def corpus_text_loader(corpus_root: Path) -> NegativeTextLoader:
    """Read a corpus-relative document for the answer-leak check.

    Returns None when the document is unreadable, outside the root, not valid UTF-8 or
    binary (NUL bytes): a lossy decode would make a document "verified" answer-free when
    nobody could read it, so such candidates are rejected as unverifiable instead.
    """
    root = corpus_root.resolve()

    def _load(doc_id: str) -> str | None:
        candidate = Path(str(doc_id or "").strip())
        if not str(candidate) or candidate.is_absolute():
            return None
        try:
            resolved = (root / candidate).resolve()
            resolved.relative_to(root)
            raw = resolved.read_bytes()
        except (OSError, ValueError):
            return None
        if b"\x00" in raw:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None

    return _load


def _canonical_positive(label: str, retrieved: list[str]) -> str:
    """The retrieved path that matches the label, so training can materialize the file; else the label."""
    for candidate in retrieved:
        if path_matches(label, candidate):
            return candidate
    return label


@overload
def mine_triplets_from_eval_results(
    results: Iterable[EvalResult],
    *,
    negative_ratio: int,
    max_triplets: int | None = ...,
    source: str = ...,
    corpus_root: Path | None = ...,
    negative_text: NegativeTextLoader | None = ...,
    with_stats: Literal[True],
) -> tuple[list[dict[str, str]], dict[str, int]]: ...


@overload
def mine_triplets_from_eval_results(
    results: Iterable[EvalResult],
    *,
    negative_ratio: int,
    max_triplets: int | None = ...,
    source: str = ...,
    corpus_root: Path | None = ...,
    negative_text: NegativeTextLoader | None = ...,
    with_stats: Literal[False] = ...,
) -> list[dict[str, str]]: ...


def mine_triplets_from_eval_results(
    results: Iterable[EvalResult],
    *,
    negative_ratio: int,
    max_triplets: int | None = None,
    source: str = "eval_run",
    corpus_root: Path | None = None,
    negative_text: NegativeTextLoader | None = None,
    with_stats: bool = False,
) -> list[dict[str, str]] | tuple[list[dict[str, str]], dict[str, int]]:
    """Mine (query, expected path, hard negative) rows from per-entry eval results.

    Negatives are taken in retrieval rank order, skipping anything that matches an
    expected path (boundary-aware suffix rule shared with the eval scorer) and, when
    the result carries its own ``expected_answer`` and a document loader is available,
    anything whose text contains that answer. The answer is read only from the result
    (the trace's own provenance), never from the current dataset; results without an
    answer are mined without the leak check and counted. At most ``negative_ratio``
    negatives per entry; rows are deduplicated on (query, positive, negative).
    """
    per_entry = max(1, int(negative_ratio))
    loader = negative_text or (corpus_text_loader(corpus_root) if corpus_root is not None else None)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    stats = {
        "entries": 0,
        "entries_rejected_placeholder": 0,
        "entries_without_positive": 0,
        "entries_without_negative": 0,
        "entries_without_answer_provenance": 0,
        "negatives_rejected_answer_leak": 0,
        "negatives_rejected_unverifiable": 0,
        "rows_rejected_invalid": 0,
    }

    def _finish() -> list[dict[str, str]] | tuple[list[dict[str, str]], dict[str, int]]:
        return (rows, stats) if with_stats else rows

    for result in results:
        stats["entries"] += 1
        query = str(result.question or "").strip()
        if not is_real_query(query):
            stats["entries_rejected_placeholder"] += 1
            continue
        retrieved = [str(raw or "").strip() for raw in (result.retrieved_paths or []) if str(raw or "").strip()]
        labels: list[str] = []
        for raw in result.expected_paths or []:
            label = str(raw or "").strip()
            if label and label not in labels:
                labels.append(label)
        if not labels:
            stats["entries_without_positive"] += 1
            continue
        positives: list[str] = []
        for label in labels:
            canonical = _canonical_positive(label, retrieved)
            if canonical not in positives:
                positives.append(canonical)

        # The answer travels with the trace (EvalResult.expected_answer); nothing else is consulted.
        answer = str(result.expected_answer or "").strip()
        if not answer:
            stats["entries_without_answer_provenance"] += 1
        check_leak = loader is not None and len(normalize_text(answer)) >= _MIN_ANSWER_CHARS_FOR_LEAK_CHECK

        negatives: list[str] = []
        for candidate in retrieved:
            if candidate in negatives or any(path_matches(label, candidate) for label in labels):
                continue
            if check_leak:
                text = loader(candidate) if loader is not None else None
                if text is None:
                    # An unreadable candidate cannot be proven irrelevant; it is not a training label.
                    stats["negatives_rejected_unverifiable"] += 1
                    continue
                if answer_appears_in(answer, text):
                    stats["negatives_rejected_answer_leak"] += 1
                    continue
            negatives.append(candidate)
            if len(negatives) >= per_entry:
                break
        if not negatives:
            stats["entries_without_negative"] += 1
            continue

        for positive in positives:
            for negative in negatives:
                key = (query, positive, negative)
                if key in seen:
                    continue
                seen.add(key)
                row = _row(query, positive, negative, source)
                if row is None:
                    stats["rows_rejected_invalid"] += 1
                    continue
                rows.append(row.model_dump(exclude_none=True))
                if max_triplets is not None and len(rows) >= max_triplets:
                    return _finish()
    return _finish()


def mine_triplets(
    *,
    log_path: Path,
    triplets_path: Path,
    mine_mode: Literal["replace", "append"] = "replace",
    corpus_id: str | None = None,
    eval_results: Iterable[EvalResult] | None = None,
    eval_run_id: str | None = None,
    negative_ratio: int = 5,
    max_triplets: int | None = None,
    preserve_existing_on_empty: bool = False,
    corpus_root: Path | None = None,
) -> dict[str, Any]:
    """Mine feedback-log and eval-run triplets into ``triplets_path`` and report written counts per source."""
    feedback_rows, feedback_stats = _mine_feedback_triplets(log_path=log_path, corpus_id=corpus_id)
    eval_source = f"eval_run:{eval_run_id}" if eval_run_id else "eval_run"
    eval_rows: list[TripletRow] = []
    eval_stats: dict[str, int] = {}
    if eval_results is not None:
        mined, eval_stats = mine_triplets_from_eval_results(
            list(eval_results),
            negative_ratio=negative_ratio,
            source=eval_source,
            corpus_root=corpus_root,
            with_stats=True,
        )
        eval_rows = [TripletRow.model_validate(row) for row in mined]

    candidates = [*feedback_rows, *eval_rows]
    with triplets_lock(triplets_path):
        # Read, dedupe and rewrite under one exclusive lock so concurrent miners
        # (threads or processes) cannot drop each other's rows. A publish that crashed
        # mid-transaction is repaired first so mining never reads a half-published state.
        recover_parked_replacement(triplets_path)
        existing = load_triplet_rows(triplets_path) if mine_mode == "append" else []
        seen: set[tuple[str, str, str]] = {row.key() for row in existing}
        written: list[TripletRow] = []
        written_by_source = {"feedback": 0, "eval_run": 0}
        skipped_existing = 0
        for row in candidates:
            key = row.key()
            if key in seen:
                skipped_existing += 1
                continue
            seen.add(key)
            written.append(row)
            written_by_source["feedback" if row.source == FEEDBACK_SOURCE else "eval_run"] += 1
            if max_triplets is not None and len(written) >= max_triplets:
                break

        preserved_existing = False
        if mine_mode == "append":
            write_triplet_rows(triplets_path, [*existing, *written])
            total = len(existing) + len(written)
        else:
            # A reset (preserve disabled) must not read the file it is about to discard:
            # that is the operator's way out of a corrupt artifact.
            current = load_triplet_rows(triplets_path) if preserve_existing_on_empty else []
            if preserve_existing_on_empty and current and not written:
                preserved_existing = True
                total = len(current)
            else:
                write_triplet_rows(triplets_path, written)
                total = len(written)

    return {
        "ok": True,
        **feedback_stats,
        "eval_run_id": eval_run_id,
        "eval_results": int(eval_stats.get("entries", 0)) if eval_results is not None else None,
        "triplets_rejected_placeholder": int(feedback_stats.get("feedback_rejected_placeholder", 0))
        + int(eval_stats.get("entries_rejected_placeholder", 0)),
        "negatives_rejected_answer_leak": int(eval_stats.get("negatives_rejected_answer_leak", 0)),
        "negatives_rejected_unverifiable": int(eval_stats.get("negatives_rejected_unverifiable", 0)),
        "entries_without_answer_provenance": int(eval_stats.get("entries_without_answer_provenance", 0)),
        "triplets_from_feedback_candidates": len(feedback_rows),
        "triplets_from_eval_run_candidates": len(eval_rows),
        "triplets_from_feedback": written_by_source["feedback"],
        "triplets_from_eval_run": written_by_source["eval_run"],
        "triplets_skipped_existing": skipped_existing,
        "triplets_mined": len(written),
        "triplets_total": total,
        "triplets_path": str(triplets_path),
        "preserved_existing": preserved_existing,
    }
