from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import RerankingConfig

_CrossEncoderKey = tuple[str, bool]
_cross_encoder_cache: dict[_CrossEncoderKey, Any] = {}
_cross_encoder_lock = asyncio.Lock()


def _stable_chunk_key(chunk: ChunkMatch) -> str:
    meta = chunk.metadata or {}
    corpus_id = ""
    try:
        corpus_id = str(meta.get("corpus_id") or "").strip()
    except Exception:
        corpus_id = ""
    if corpus_id:
        return f"{corpus_id}::{chunk.chunk_id}"
    return str(chunk.chunk_id)


def _snippet(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    s = str(text or "")
    if len(s) <= max_chars:
        return s
    return s[:max_chars]


def _minmax_norm(vals: list[float]) -> list[float]:
    if not vals:
        return []
    mn = min(vals)
    mx = max(vals)
    span = mx - mn
    if span <= 1e-12:
        return [0.0 for _ in vals]
    return [(v - mn) / span for v in vals]


async def _get_cross_encoder(model_id: str, *, max_length: int, trust_remote_code: bool) -> Any:
    key: _CrossEncoderKey = (model_id, bool(trust_remote_code))
    async with _cross_encoder_lock:
        cached = _cross_encoder_cache.get(key)
        if cached is not None:
            try:
                if hasattr(cached, "max_length"):
                    cached.max_length = int(max_length)
            except Exception:
                pass
            return cached

        def _load() -> Any:
            from sentence_transformers import CrossEncoder

            return CrossEncoder(
                model_id,
                max_length=int(max_length),
                device="cpu",
                trust_remote_code=bool(trust_remote_code),
            )

        model = await asyncio.to_thread(_load)
        _cross_encoder_cache[key] = model
        return model


async def _predict_cross_encoder(
    model: Any,
    *,
    query: str,
    snippets: list[str],
    batch_size: int,
) -> list[float]:
    pairs = [(query, s) for s in snippets]

    def _run() -> list[float]:
        preds = model.predict(
            pairs,
            batch_size=int(batch_size),
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        try:
            return [float(x) for x in list(preds)]
        except Exception:
            return [float(x) for x in preds]

    return await asyncio.to_thread(_run)


@dataclass(frozen=True)
class RerankResult:
    chunks: list[ChunkMatch]
    ok: bool
    error: str | None = None


class Reranker:
    def __init__(self, config: RerankingConfig, *, trained_model_path: str | None = None):
        self.config = config
        self.trained_model_path = trained_model_path

    async def rerank(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        res = await self.try_rerank(query, chunks)
        return res.chunks

    async def try_rerank(self, query: str, chunks: list[ChunkMatch]) -> RerankResult:
        if not chunks:
            return RerankResult(chunks=[], ok=True)

        q = str(query or "").strip()
        if not q:
            return RerankResult(chunks=chunks, ok=True)

        mode = str(self.config.reranker_mode or "none").strip().lower()
        if mode == "none":
            return RerankResult(chunks=chunks, ok=True)

        try:
            if mode == "local":
                out = await self._rerank_local(q, chunks)
                return RerankResult(chunks=out, ok=True)
            if mode == "learning":
                out = await self._rerank_trained(q, chunks)
                return RerankResult(chunks=out, ok=True)
            if mode == "cloud":
                out = await self._rerank_api(q, chunks)
                return RerankResult(chunks=out, ok=True)
            return RerankResult(chunks=chunks, ok=True)
        except Exception as e:
            return RerankResult(chunks=chunks, ok=False, error=str(e))

    async def _rerank_local(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        model_id = str(self.config.reranker_local_model or "").strip()
        if not model_id:
            return chunks
        return await self._rerank_cross_encoder(
            query,
            chunks,
            model_id=model_id,
            top_n=int(self.config.tribrid_reranker_topn),
            mode="local",
        )

    async def _rerank_trained(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        model_id = str(self.trained_model_path or "").strip()
        if not model_id:
            return chunks
        return await self._rerank_cross_encoder(
            query,
            chunks,
            model_id=model_id,
            top_n=int(self.config.tribrid_reranker_topn),
            mode="learning",
        )

    async def _rerank_api(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        provider = str(self.config.reranker_cloud_provider or "").strip().lower()
        if provider in {"cohere"}:
            return await self._rerank_cohere(query, chunks)
        raise ValueError(f"Unsupported cloud reranker provider: {provider}")

    async def _rerank_cohere(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        api_key = os.getenv("COHERE_API_KEY")
        if not api_key:
            return chunks

        provider = str(self.config.reranker_cloud_provider or "").strip()
        top_n = min(len(chunks), int(self.config.reranker_cloud_top_n))
        if top_n <= 0:
            return chunks

        snippet_chars = int(self.config.rerank_input_snippet_chars)
        candidates = chunks[:top_n]
        remainder = chunks[top_n:]
        docs = [_snippet(c.content, max_chars=snippet_chars) for c in candidates]

        model = str(self.config.reranker_cloud_model or "").strip() or None
        timeout_s = float(self.config.reranker_timeout)

        def _run() -> list[float]:
            import cohere

            client = cohere.Client(api_key)

            if hasattr(client, "rerank"):
                resp = client.rerank(query=query, documents=docs, model=model, top_n=top_n, timeout=timeout_s)
                results = getattr(resp, "results", None) or []
                scores_by_index: dict[int, float] = {}
                for item in results:
                    try:
                        scores_by_index[int(item.index)] = float(item.relevance_score)
                    except Exception:
                        continue
                return [float(scores_by_index.get(i, 0.0)) for i in range(top_n)]

            raise RuntimeError("Cohere client does not support rerank()")

        raw_scores = await asyncio.to_thread(_run)
        rerank_norm = _minmax_norm(raw_scores)
        orig_raw = [float(c.score) for c in candidates]
        orig_norm = _minmax_norm(orig_raw)
        alpha = float(self.config.tribrid_reranker_alpha)
        blended = [((1.0 - alpha) * o) + (alpha * r) for o, r in zip(orig_norm, rerank_norm, strict=False)]

        updated: list[ChunkMatch] = []
        for c, s_raw, s_norm, f_raw, f_norm, s in zip(
            candidates, raw_scores, rerank_norm, orig_raw, orig_norm, blended, strict=False
        ):
            meta = dict(c.metadata or {})
            meta.update(
                {
                    "reranker_mode": "cloud",
                    "reranker_cloud_provider": provider,
                    "reranker_model": str(self.config.reranker_cloud_model or "").strip(),
                    "reranker_score_raw": float(s_raw),
                    "reranker_score": float(s_norm),
                    "fusion_score_raw": float(f_raw),
                    "fusion_score": float(f_norm),
                }
            )
            updated.append(c.model_copy(update={"score": float(s), "metadata": meta}))

        updated.sort(key=lambda c: (-float(c.score), _stable_chunk_key(c)))
        return [*updated, *remainder]

    async def _rerank_cross_encoder(
        self,
        query: str,
        chunks: list[ChunkMatch],
        *,
        model_id: str,
        top_n: int,
        mode: str,
    ) -> list[ChunkMatch]:
        top_n = min(len(chunks), int(top_n))
        if top_n <= 0:
            return chunks

        snippet_chars = int(self.config.rerank_input_snippet_chars)
        max_length = int(self.config.tribrid_reranker_maxlen)
        batch_size = int(self.config.tribrid_reranker_batch)
        trust_remote_code = bool(self.config.transformers_trust_remote_code)

        candidates = chunks[:top_n]
        remainder = chunks[top_n:]

        snippets = [_snippet(c.content, max_chars=snippet_chars) for c in candidates]
        model = await _get_cross_encoder(model_id, max_length=max_length, trust_remote_code=trust_remote_code)
        raw_scores = await _predict_cross_encoder(
            model,
            query=query,
            snippets=snippets,
            batch_size=batch_size,
        )

        rerank_norm = _minmax_norm(raw_scores)
        orig_raw = [float(c.score) for c in candidates]
        orig_norm = _minmax_norm(orig_raw)

        alpha = float(self.config.tribrid_reranker_alpha)
        blended = [((1.0 - alpha) * o) + (alpha * r) for o, r in zip(orig_norm, rerank_norm, strict=False)]

        updated: list[ChunkMatch] = []
        for c, s_raw, s_norm, f_raw, f_norm, s in zip(
            candidates, raw_scores, rerank_norm, orig_raw, orig_norm, blended, strict=False
        ):
            meta = dict(c.metadata or {})
            meta.update(
                {
                    "reranker_mode": mode,
                    "reranker_model": str(model_id),
                    "reranker_score_raw": float(s_raw),
                    "reranker_score": float(s_norm),
                    "fusion_score_raw": float(f_raw),
                    "fusion_score": float(f_norm),
                }
            )
            updated.append(c.model_copy(update={"score": float(s), "metadata": meta}))

        updated.sort(key=lambda c: (-float(c.score), _stable_chunk_key(c)))
        return [*updated, *remainder]

    def load_model(self) -> None:
        """Eagerly load the configured local/learning model (best-effort)."""
        mode = str(self.config.reranker_mode or "none").strip().lower()
        if mode == "local":
            model_id = str(self.config.reranker_local_model or "").strip()
        elif mode == "learning":
            model_id = str(self.trained_model_path or "").strip()
        else:
            return

        if not model_id:
            return

        max_length = int(self.config.tribrid_reranker_maxlen)
        trust_remote_code = bool(self.config.transformers_trust_remote_code)

        from sentence_transformers import CrossEncoder

        model = CrossEncoder(
            model_id,
            max_length=int(max_length),
            device="cpu",
            trust_remote_code=bool(trust_remote_code),
        )
        _cross_encoder_cache[(model_id, bool(trust_remote_code))] = model

    def reload_model(self) -> None:
        """Clear cached models so the next call reloads (best-effort)."""
        _cross_encoder_cache.clear()
