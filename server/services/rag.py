"""Shared retrieval protocol and chat-debug response construction."""

import re
from typing import Any, Literal, Protocol

from server.models.chat_config import RecallPlan
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import (
    ChatDebugInfo,
    ChatProviderInfo,
    FusionConfig,
    RerankDebugInfo,
    TriBridConfig,
)
from server.retrieval.cache import CacheMode


class FusionProtocol(Protocol):
    """Protocol for fusion retrieval service."""

    async def search(
        self,
        corpus_ids: list[str],
        query: str,
        config: FusionConfig,
        *,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
        cache_mode: CacheMode = "default",
        cache_namespace: str = "search",
    ) -> list[ChunkMatch]:
        ...

def build_chat_debug_info(
    *,
    config: TriBridConfig,
    fusion: Any,
    include_vector: bool,
    include_sparse: bool,
    include_graph: bool,
    top_k: int | None,
    sources: list[ChunkMatch],
    recall_plan: RecallPlan | None = None,
    provider: ChatProviderInfo | None = None,
) -> ChatDebugInfo:
    """Build ChatDebugInfo from fusion debug + config."""
    fusion_debug: dict[str, Any] = getattr(fusion, "last_debug", None) or {}

    scores = [float(s.score) for s in sources if s.score is not None]
    top1 = scores[0] if scores else None
    top5 = scores[:5]
    avg5 = (sum(top5) / len(top5)) if top5 else None

    method = str(getattr(config.fusion, "method", "") or "").strip().lower()
    fusion_method: str | None = method if method in {"rrf", "weighted"} else None

    # Determine which legs actually contributed (requested + enabled + non-empty)
    vector_ok = bool(include_vector) and bool(fusion_debug.get("fusion_vector_enabled")) and int(
        fusion_debug.get("fusion_vector_results") or 0
    ) > 0
    sparse_ok = bool(include_sparse) and bool(fusion_debug.get("fusion_sparse_enabled")) and int(
        fusion_debug.get("fusion_sparse_results") or 0
    ) > 0
    graph_ok = bool(include_graph) and bool(fusion_debug.get("fusion_graph_enabled")) and int(
        fusion_debug.get("fusion_graph_hydrated_chunks") or 0
    ) > 0
    legs_used = int(vector_ok) + int(sparse_ok) + int(graph_ok)

    confidence: float | None = None
    if top1 is not None and fusion_method == "rrf":
        k = int(getattr(config.fusion, "rrf_k", 60) or 60)
        denom = float(legs_used) / float(k + 1) if legs_used > 0 else 0.0
        if denom > 0.0:
            confidence = max(0.0, min(1.0, float(top1) / denom))
    elif top1 is not None and fusion_method == "weighted":
        confidence = max(0.0, min(1.0, float(top1)))

    # Cast fusion_method to the expected Literal type
    typed_fusion_method: Literal["rrf", "weighted"] | None = None
    if fusion_method == "rrf":
        typed_fusion_method = "rrf"
    elif fusion_method == "weighted":
        typed_fusion_method = "weighted"

    # Safely extract int values from fusion_debug
    def _safe_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    # Best-effort reranker status (prefer non-Recall/RAG retrieval when available).
    rerank: RerankDebugInfo | None = None
    try:
        rag_debug: dict[str, Any] = {}
        if isinstance(fusion_debug, dict):
            candidate = fusion_debug.get("chat_rag_fusion")
            if isinstance(candidate, dict):
                rag_debug = candidate
            else:
                rag_debug = fusion_debug

        if isinstance(rag_debug, dict) and (
            "rerank_mode" in rag_debug
            or "rerank_enabled" in rag_debug
            or "rerank_ok" in rag_debug
            or "rerank_error" in rag_debug
            or "rerank_skipped_reason" in rag_debug
        ):
            enabled = bool(rag_debug.get("rerank_enabled"))
            mode = str(rag_debug.get("rerank_mode") or "none")
            ok = bool(rag_debug.get("rerank_ok", True))
            applied = bool(rag_debug.get("rerank_applied", False))

            skipped_reason_raw = rag_debug.get("rerank_skipped_reason")
            skipped_reason: str | None
            if isinstance(skipped_reason_raw, str):
                skipped_reason = skipped_reason_raw.strip() or None
            else:
                skipped_reason = None

            error_raw = rag_debug.get("rerank_error")
            error: str | None
            if isinstance(error_raw, str):
                error = error_raw.strip() or None
            else:
                error = None

            candidates_reranked = _safe_int(rag_debug.get("rerank_candidates_reranked")) or 0
            candidates_reranked = int(max(0, candidates_reranked))

            config_corpus_raw = rag_debug.get("rerank_config_corpus_id")
            config_corpus_id: str | None
            if isinstance(config_corpus_raw, str):
                config_corpus_id = config_corpus_raw.strip() or None
            else:
                config_corpus_id = None

            # Summarize error for user-facing UI (when available).
            error_message: str | None = None
            debug_trace_id: str | None = None
            if error:
                # Common in Cohere errors: "x-debug-trace-id': '...'"
                m = re.search(r"x-debug-trace-id['\"]?:\\s*['\"]([0-9a-fA-F]+)['\"]", error)
                if m:
                    debug_trace_id = str(m.group(1))

                # Common in provider bodies: "message": "..."
                m = re.search(r"\"message\"\\s*:\\s*\"([^\"]+)\"", error)
                if m:
                    error_message = str(m.group(1)).strip() or None
                else:
                    # Python dict repr: 'message': "..."
                    m = re.search(r"'message'\\s*:\\s*\"([^\"]+)\"", error)
                    if m:
                        error_message = str(m.group(1)).strip() or None

                if not error_message:
                    error_message = error if len(error) <= 240 else f"{error[:240]}…"

            rerank = RerankDebugInfo(
                enabled=bool(enabled),
                mode=mode,
                ok=bool(ok),
                applied=bool(applied),
                candidates_reranked=candidates_reranked,
                skipped_reason=skipped_reason,
                error=error,
                error_message=error_message,
                debug_trace_id=debug_trace_id,
                config_corpus_id=config_corpus_id,
            )
    except Exception:
        rerank = None

    return ChatDebugInfo(
        confidence=confidence,
        provider=provider,
        recall_plan=recall_plan,
        include_vector=bool(include_vector),
        include_sparse=bool(include_sparse),
        include_graph=bool(include_graph),
        vector_enabled=(bool(fusion_debug.get("fusion_vector_enabled")) if "fusion_vector_enabled" in fusion_debug else None),
        sparse_enabled=(bool(fusion_debug.get("fusion_sparse_enabled")) if "fusion_sparse_enabled" in fusion_debug else None),
        graph_enabled=(bool(fusion_debug.get("fusion_graph_enabled")) if "fusion_graph_enabled" in fusion_debug else None),
        fusion_method=typed_fusion_method,
        rrf_k=(int(getattr(config.fusion, "rrf_k", 60)) if typed_fusion_method == "rrf" else None),
        vector_weight=(float(getattr(config.fusion, "vector_weight", 0.0)) if typed_fusion_method == "weighted" else None),
        sparse_weight=(float(getattr(config.fusion, "sparse_weight", 0.0)) if typed_fusion_method == "weighted" else None),
        graph_weight=(float(getattr(config.fusion, "graph_weight", 0.0)) if typed_fusion_method == "weighted" else None),
        normalize_scores=(bool(getattr(config.fusion, "normalize_scores", False)) if typed_fusion_method == "weighted" else None),
        final_k_used=int(top_k or config.retrieval.final_k),
        vector_results=_safe_int(fusion_debug.get("fusion_vector_results")) if "fusion_vector_results" in fusion_debug else None,
        sparse_results=_safe_int(fusion_debug.get("fusion_sparse_results")) if "fusion_sparse_results" in fusion_debug else None,
        graph_qdrant_seed_chunks=_safe_int(fusion_debug.get("fusion_graph_qdrant_seed_chunks")) if "fusion_graph_qdrant_seed_chunks" in fusion_debug else None,
        graph_resolved_entities=_safe_int(fusion_debug.get("fusion_graph_resolved_entities")) if "fusion_graph_resolved_entities" in fusion_debug else None,
        graph_relationship_expansion_hits=_safe_int(fusion_debug.get("fusion_graph_relationship_expansion_hits")) if "fusion_graph_relationship_expansion_hits" in fusion_debug else None,
        graph_community_expansion_hits=_safe_int(fusion_debug.get("fusion_graph_community_expansion_hits")) if "fusion_graph_community_expansion_hits" in fusion_debug else None,
        graph_hydrated_chunks=_safe_int(fusion_debug.get("fusion_graph_hydrated_chunks")) if "fusion_graph_hydrated_chunks" in fusion_debug else None,
        final_results=len(sources),
        top1_score=(float(top1) if top1 is not None else None),
        avg5_score=(float(avg5) if avg5 is not None else None),
        conf_top1_thresh=float(config.retrieval.conf_top1),
        conf_avg5_thresh=float(config.retrieval.conf_avg5),
        rerank=rerank,
        fusion_debug=fusion_debug,
    )
