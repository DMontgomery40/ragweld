from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.models.tribrid_config_model import TriBridConfig

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


async def append_query_log(config: TriBridConfig, *, entry: dict[str, Any]) -> None:
    """Append a single JSONL entry to config.tracing.tribrid_log_path (best-effort)."""
    path = _resolve_path(str(config.tracing.tribrid_log_path or "data/logs/queries.jsonl"))
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
) -> None:
    """Append a feedback JSONL entry to config.tracing.tribrid_log_path (best-effort).

    Notes:
    - "Learning reranker" feedback uses (event_id, signal, doc_id?, note?).
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

    await append_query_log(config, entry=payload)
