from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from server.dependency_errors import DependencyUnavailableError
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FeedbackSurface, TriBridConfig

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Chunk-level candidates kept per query record, and the text snapshot per candidate.
QUERY_RECORD_CANDIDATES = 10
QUERY_RECORD_SNIPPET_CHARS = 500
# How far back (bytes from the end of the log) a feedback request looks for its event's record.
QUERY_RECORD_LOOKBACK_BYTES = 16 * 1024 * 1024


class QueryRecordCandidate(BaseModel):
    """One retrieved chunk as a query record stores it (JSONL persistence boundary)."""

    rank: int = Field(ge=1, description="1-based position in the fused result the caller used")
    chunk_id: str
    file_path: str
    corpus_id: str | None = None
    start_line: int
    end_line: int
    page_start: int | None = None
    page_end: int | None = None
    score: float
    source: str = Field(description="Retrieval leg that found the chunk (vector, sparse, graph)")
    text: str = Field(max_length=QUERY_RECORD_SNIPPET_CHARS, description="Leading text of the chunk")


def query_record_candidates(
    matches: Sequence[ChunkMatch], *, limit: int = QUERY_RECORD_CANDIDATES
) -> list[dict[str, Any]]:
    """The top `limit` matches as chunk-level query-record candidates (in rank order)."""
    out: list[dict[str, Any]] = []
    for rank, match in enumerate(list(matches)[: max(0, int(limit))], start=1):
        provenance = match.provenance
        corpus_id = (match.metadata or {}).get("corpus_id")
        out.append(
            QueryRecordCandidate(
                rank=rank,
                chunk_id=str(match.chunk_id),
                file_path=str(match.file_path),
                corpus_id=str(corpus_id) if isinstance(corpus_id, str) and corpus_id else None,
                start_line=int(match.start_line),
                end_line=int(match.end_line),
                page_start=provenance.page_start if provenance is not None else None,
                page_end=provenance.page_end if provenance is not None else None,
                score=float(match.score),
                source=str(match.source),
                text=str(match.content or "")[:QUERY_RECORD_SNIPPET_CHARS],
            ).model_dump(mode="json")
        )
    return out


def _resolve_path(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(s: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(s) <= max_chars:
        return s
    return s[:max_chars]


def _query_log_path(config: TriBridConfig) -> Path:
    return _resolve_path(str(config.tracing.tribrid_log_path or "data/logs/queries.jsonl"))


def _scan_for_query_record(path: Path, event_id: str, *, max_bytes: int) -> dict[str, Any] | None:
    """Newest chat/search record for `event_id` in the last `max_bytes` of the log (blocking)."""
    try:
        size = path.stat().st_size
        start = max(0, size - int(max_bytes))
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read()
    except OSError:
        return None  # no readable log: the event's record is unknown, not a failure
    lines = data.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]  # the first line may be cut mid-record
    needle = event_id.encode("utf-8")
    for raw in reversed(lines):
        if needle not in raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if (
            isinstance(obj, dict)
            and obj.get("event_id") == event_id
            and str(obj.get("kind") or "") in {"chat", "search"}
        ):
            return obj
    return None


async def find_query_record(
    config: TriBridConfig, event_id: str, *, max_bytes: int = QUERY_RECORD_LOOKBACK_BYTES
) -> dict[str, Any] | None:
    """The newest chat/search query record written for `event_id`, or None (off the event loop)."""
    if not event_id:
        return None
    return await asyncio.to_thread(
        _scan_for_query_record, _query_log_path(config), event_id, max_bytes=max_bytes
    )


async def append_query_log(config: TriBridConfig, *, entry: dict[str, Any]) -> None:
    """Append a single JSONL entry to config.tracing.tribrid_log_path (best-effort)."""
    path = _query_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(entry)
    payload.setdefault("ts", _now_iso())
    if "query" in payload and isinstance(payload["query"], str):
        payload["query"] = _truncate(payload["query"], max_chars=2000)

    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _write() -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    await asyncio.to_thread(_write)


async def append_feedback_log(
    config: TriBridConfig,
    *,
    event_id: str | None,
    signal: str | None,
    doc_id: str | None = None,
    note: str | None = None,
    rating: int | None = None,
    comment: str | None = None,
    timestamp: str | None = None,
    context: str | None = None,
    chunk_ids: Sequence[str] = (),
    surface: FeedbackSurface | None = None,
) -> None:
    """Append a feedback JSONL entry to config.tracing.tribrid_log_path.

    Notes:
    - Event feedback uses (event_id, signal, doc_id?, note?, chunk_ids?, surface), for
      every signal of either polarity.
    - UI/meta feedback is accepted via (rating, comment?, timestamp?, context?).
    """
    payload: dict[str, Any] = {
        "type": "feedback",
        "kind": "feedback",
        "ts": _now_iso(),
    }
    if event_id:
        payload["event_id"] = str(event_id)
    if signal:
        payload["signal"] = str(signal)
    if doc_id:
        payload["doc_id"] = str(doc_id)
    if note:
        payload["note"] = _truncate(str(note), max_chars=4000)
    if rating is not None:
        payload["rating"] = int(rating)
    if comment:
        payload["comment"] = _truncate(str(comment), max_chars=4000)
    if timestamp:
        payload["timestamp"] = str(timestamp)
    if context:
        payload["context"] = str(context)
    if chunk_ids:
        payload["chunk_ids"] = [str(chunk_id) for chunk_id in chunk_ids]
    if surface:
        payload["surface"] = str(surface)

    try:
        await append_query_log(config, entry=payload)
    except OSError as exc:
        raise DependencyUnavailableError("feedback_log", "Feedback log append") from exc
