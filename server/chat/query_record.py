"""The per-exchange query/source record the reranker's triplet mining correlates with feedback.

One writer for the chat lane (non-stream and stream): the record is part of the exchange's
commit, written together with the messages and the generation cache, never ahead of them.
"""

from __future__ import annotations

from server.models.tribrid_config_model import TriBridConfig
from server.services.rag import FusionProtocol


async def append_chat_query_record(
    *,
    config: TriBridConfig,
    fusion: FusionProtocol,
    event_id: str,
    conversation_id: str,
    corpus_ids: list[str],
    query: str,
    top_paths: list[str],
) -> None:
    """Best-effort query log append for triplet mining correlation."""
    if not getattr(config.tracing, "tracing_enabled", True):
        return

    from server.observability.query_log import append_query_log

    fusion_debug = getattr(fusion, "last_debug", None) or {}
    rag_debug = fusion_debug.get("chat_rag_fusion") if isinstance(fusion_debug, dict) else None
    if not isinstance(rag_debug, dict):
        rag_debug = fusion_debug if isinstance(fusion_debug, dict) else {}

    await append_query_log(
        config,
        entry={
            "event_id": event_id,
            "kind": "chat",
            "conversation_id": conversation_id,
            "corpus_ids": corpus_ids,
            "query": query,
            "reranker_mode": str(rag_debug.get("rerank_mode") or str(config.reranking.reranker_mode or "")),
            "rerank_ok": bool(rag_debug.get("rerank_ok", True)),
            "rerank_applied": bool(rag_debug.get("rerank_applied", False)),
            "rerank_skipped_reason": rag_debug.get("rerank_skipped_reason"),
            "rerank_error": rag_debug.get("rerank_error"),
            "rerank_candidates_reranked": int(rag_debug.get("rerank_candidates_reranked") or 0),
            "top_paths": list(top_paths[:5]),
        },
    )

