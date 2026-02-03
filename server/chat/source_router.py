"""Helpers for resolving the active chat sources.

Recall is represented by the corpus id ``recall_default``.
"""

from __future__ import annotations

from server.models.chat_config import ActiveSources


def resolve_sources(sources: ActiveSources) -> list[str]:
    """Resolve and normalize the active corpus ids for chat."""

    resolved: list[str] = []
    seen: set[str] = set()

    for corpus_id in sources.corpus_ids:
        cid = (corpus_id or "").strip()
        if not cid:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        resolved.append(cid)

    return resolved

