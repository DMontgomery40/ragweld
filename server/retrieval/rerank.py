from __future__ import annotations

import asyncio
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import RerankingConfig, TrainingConfig
from server.observability.metrics import (
    RERANKER_CANDIDATES_TOTAL,
    RERANKER_ERRORS_TOTAL,
    RERANKER_LATENCY_SECONDS,
    RERANKER_REQUESTS_TOTAL,
    RERANKER_SKIPPED_TOTAL,
)
from server.retrieval.mlx_qwen3 import get_mlx_qwen3_reranker, mlx_is_available
from server.reranker.artifacts import has_transformers_weights, resolve_project_path

_CrossEncoderKey = tuple[str, bool, str]
_cross_encoder_cache: dict[_CrossEncoderKey, Any] = {}
_cross_encoder_lock = asyncio.Lock()

def clear_cross_encoder_cache_for_model(model_id: str) -> None:
    """Best-effort cache invalidation for local Transformers CrossEncoder models.

    Used after atomic promotion so the next inference/scoring call reloads weights.
    """
    target = str(model_id or "").strip()
    if not target:
        return

    target_resolved: Path | None = None
    try:
        target_resolved = resolve_project_path(target).resolve()
    except Exception:
        target_resolved = None

    # Best-effort: do not block on the async lock here. This is safe because callers
    # use this only after a promotion event; worst case we clear slightly late.
    to_del: list[_CrossEncoderKey] = []
    for key in list(_cross_encoder_cache.keys()):
        mid = str(key[0] or "")
        if mid == target:
            to_del.append(key)
            continue
        if target_resolved is not None:
            try:
                if resolve_project_path(mid).resolve() == target_resolved:
                    to_del.append(key)
            except Exception:
                continue

    for key in to_del:
        try:
            _cross_encoder_cache.pop(key, None)
        except Exception:
            continue


def resolve_reranker_device() -> str:
    """Resolve the best available device for local/learning CrossEncoder inference.

    Priority:
    - CUDA (NVIDIA GPUs)
    - MPS (Apple Silicon GPU via Metal)
    - CPU
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"

        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and callable(getattr(mps_backend, "is_available", None)):
            if bool(mps_backend.is_available()):
                return "mps"
    except Exception:
        pass

    return "cpu"


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


def _mlx_platform_supported() -> bool:
    return platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}


def resolve_learning_backend(training_config: TrainingConfig | None, *, artifact_path: str | None = None) -> str:
    del artifact_path  # kept for API compatibility
    requested = "auto"
    try:
        if training_config is not None:
            requested = str(training_config.learning_reranker_backend or "auto").strip().lower()
    except Exception:
        requested = "auto"

    if requested in {"transformers", "hf"}:
        return "transformers"
    if requested in {"mlx_qwen3", "mlx"}:
        if not _mlx_platform_supported():
            raise RuntimeError("learning_reranker_backend=mlx_qwen3 requires macOS arm64")
        if not mlx_is_available():
            raise RuntimeError("learning_reranker_backend=mlx_qwen3 requires MLX deps (install with `uv sync --extra mlx`)")
        return "mlx_qwen3"

    # auto: strict platform gating (only Apple Silicon + MLX deps).
    if _mlx_platform_supported() and mlx_is_available():
        return "mlx_qwen3"
    return "transformers"


async def _get_cross_encoder(model_id: str, *, max_length: int, trust_remote_code: bool) -> Any:
    device = resolve_reranker_device()
    key: _CrossEncoderKey = (model_id, bool(trust_remote_code), device)
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
                device=device,
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


async def score_cross_encoder_pairs(
    *,
    model_id: str,
    query: str,
    snippets: list[str],
    max_length: int,
    batch_size: int,
    trust_remote_code: bool,
) -> list[float]:
    model = await _get_cross_encoder(str(model_id), max_length=int(max_length), trust_remote_code=bool(trust_remote_code))
    return await _predict_cross_encoder(
        model,
        query=str(query),
        snippets=list(snippets),
        batch_size=int(batch_size),
    )


@dataclass(frozen=True)
class RerankResult:
    chunks: list[ChunkMatch]
    ok: bool
    applied: bool
    candidates_reranked: int = 0
    skipped_reason: str | None = None
    error: str | None = None


@dataclass
class RerankerRuntimeState:
    """Best-effort in-process observability for reranker inference.

    This is intentionally in-memory only (resets on process restart).
    """

    last_attempt_ms: int | None = None
    last_mode: str = "none"
    last_ok: bool = True
    last_applied: bool = False
    last_candidates_reranked: int = 0
    last_skipped_reason: str | None = None
    last_error: str | None = None


_RUNTIME = RerankerRuntimeState()


def get_reranker_runtime() -> RerankerRuntimeState:
    return _RUNTIME


class Reranker:
    def __init__(
        self,
        config: RerankingConfig,
        *,
        training_config: TrainingConfig | None = None,
        trained_model_path: str | None = None,
    ):
        self.config = config
        self.training_config = training_config
        self.trained_model_path = trained_model_path

    async def rerank(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        res = await self.try_rerank(query, chunks)
        return res.chunks

    async def try_rerank(self, query: str, chunks: list[ChunkMatch]) -> RerankResult:
        q = str(query or "").strip()
        mode = str(self.config.reranker_mode or "none").strip().lower()
        if mode == "none":
            _RUNTIME.last_attempt_ms = int(time.time() * 1000)
            _RUNTIME.last_mode = "none"
            _RUNTIME.last_ok = True
            _RUNTIME.last_applied = False
            _RUNTIME.last_candidates_reranked = 0
            _RUNTIME.last_skipped_reason = None
            _RUNTIME.last_error = None
            return RerankResult(chunks=chunks, ok=True, applied=False)

        try:
            _RUNTIME.last_attempt_ms = int(time.time() * 1000)
            _RUNTIME.last_mode = mode
            _RUNTIME.last_error = None

            if not chunks:
                if mode in {"local", "learning", "cloud"}:
                    RERANKER_REQUESTS_TOTAL.labels(mode=mode).inc()
                    RERANKER_SKIPPED_TOTAL.labels(mode=mode, reason="no_candidates").inc()
                _RUNTIME.last_ok = True
                _RUNTIME.last_applied = False
                _RUNTIME.last_candidates_reranked = 0
                _RUNTIME.last_skipped_reason = "no_candidates"
                return RerankResult(chunks=[], ok=True, applied=False, skipped_reason="no_candidates")

            if not q:
                if mode in {"local", "learning", "cloud"}:
                    RERANKER_REQUESTS_TOTAL.labels(mode=mode).inc()
                    RERANKER_SKIPPED_TOTAL.labels(mode=mode, reason="empty_query").inc()
                _RUNTIME.last_ok = True
                _RUNTIME.last_applied = False
                _RUNTIME.last_candidates_reranked = 0
                _RUNTIME.last_skipped_reason = "empty_query"
                return RerankResult(chunks=chunks, ok=True, applied=False, skipped_reason="empty_query")

            if mode == "local":
                RERANKER_REQUESTS_TOTAL.labels(mode=mode).inc()
                model_id = str(self.config.reranker_local_model or "").strip()
                if not model_id:
                    RERANKER_SKIPPED_TOTAL.labels(mode=mode, reason="missing_model").inc()
                    _RUNTIME.last_ok = True
                    _RUNTIME.last_applied = False
                    _RUNTIME.last_candidates_reranked = 0
                    _RUNTIME.last_skipped_reason = "missing_model"
                    return RerankResult(chunks=chunks, ok=True, applied=False, skipped_reason="missing_model")

                with RERANKER_LATENCY_SECONDS.labels(mode=mode).time():
                    out = await self._rerank_local(q, chunks)
                top_n = min(len(chunks), int(self.config.tribrid_reranker_topn))
                if top_n > 0:
                    RERANKER_CANDIDATES_TOTAL.labels(mode=mode).inc(top_n)
                _RUNTIME.last_ok = True
                _RUNTIME.last_applied = True
                _RUNTIME.last_candidates_reranked = int(max(0, top_n))
                _RUNTIME.last_skipped_reason = None
                return RerankResult(chunks=out, ok=True, applied=True, candidates_reranked=int(max(0, top_n)))
            if mode == "learning":
                RERANKER_REQUESTS_TOTAL.labels(mode=mode).inc()
                model_id = str(self.trained_model_path or "").strip()
                if not model_id:
                    RERANKER_SKIPPED_TOTAL.labels(mode=mode, reason="missing_trained_model").inc()
                    _RUNTIME.last_ok = True
                    _RUNTIME.last_applied = False
                    _RUNTIME.last_candidates_reranked = 0
                    _RUNTIME.last_skipped_reason = "missing_trained_model"
                    return RerankResult(
                        chunks=chunks, ok=True, applied=False, skipped_reason="missing_trained_model"
                    )

                backend = resolve_learning_backend(self.training_config, artifact_path=model_id)
                if backend != "mlx_qwen3":
                    resolved = resolve_project_path(model_id)
                    if resolved.exists() and resolved.is_dir() and not has_transformers_weights(resolved):
                        RERANKER_SKIPPED_TOTAL.labels(mode=mode, reason="missing_trained_model").inc()
                        _RUNTIME.last_ok = True
                        _RUNTIME.last_applied = False
                        _RUNTIME.last_candidates_reranked = 0
                        _RUNTIME.last_skipped_reason = "missing_trained_model"
                        return RerankResult(
                            chunks=chunks,
                            ok=True,
                            applied=False,
                            skipped_reason="missing_trained_model",
                        )

                with RERANKER_LATENCY_SECONDS.labels(mode=mode).time():
                    out = await self._rerank_trained(q, chunks)
                top_n = min(len(chunks), int(self.config.tribrid_reranker_topn))
                if top_n > 0:
                    RERANKER_CANDIDATES_TOTAL.labels(mode=mode).inc(top_n)
                _RUNTIME.last_ok = True
                _RUNTIME.last_applied = True
                _RUNTIME.last_candidates_reranked = int(max(0, top_n))
                _RUNTIME.last_skipped_reason = None
                return RerankResult(chunks=out, ok=True, applied=True, candidates_reranked=int(max(0, top_n)))
            if mode == "cloud":
                RERANKER_REQUESTS_TOTAL.labels(mode=mode).inc()
                provider = str(self.config.reranker_cloud_provider or "").strip().lower()
                if provider == "cohere":
                    if not os.getenv("COHERE_API_KEY"):
                        RERANKER_SKIPPED_TOTAL.labels(mode=mode, reason="missing_api_key").inc()
                        _RUNTIME.last_ok = True
                        _RUNTIME.last_applied = False
                        _RUNTIME.last_candidates_reranked = 0
                        _RUNTIME.last_skipped_reason = "missing_api_key"
                        return RerankResult(
                            chunks=chunks, ok=True, applied=False, skipped_reason="missing_api_key"
                        )

                with RERANKER_LATENCY_SECONDS.labels(mode=mode).time():
                    out = await self._rerank_api(q, chunks)
                top_n = min(len(chunks), int(self.config.reranker_cloud_top_n))
                if top_n > 0:
                    RERANKER_CANDIDATES_TOTAL.labels(mode=mode).inc(top_n)
                _RUNTIME.last_ok = True
                _RUNTIME.last_applied = True
                _RUNTIME.last_candidates_reranked = int(max(0, top_n))
                _RUNTIME.last_skipped_reason = None
                return RerankResult(chunks=out, ok=True, applied=True, candidates_reranked=int(max(0, top_n)))

            _RUNTIME.last_ok = True
            _RUNTIME.last_applied = False
            _RUNTIME.last_candidates_reranked = 0
            _RUNTIME.last_skipped_reason = None
            return RerankResult(chunks=chunks, ok=True, applied=False)
        except Exception as e:
            if mode in {"local", "learning", "cloud"}:
                RERANKER_ERRORS_TOTAL.labels(mode=mode).inc()
            _RUNTIME.last_ok = False
            _RUNTIME.last_applied = False
            _RUNTIME.last_candidates_reranked = 0
            _RUNTIME.last_skipped_reason = None
            _RUNTIME.last_error = str(e)
            return RerankResult(chunks=chunks, ok=False, applied=False, error=str(e))

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
        backend = resolve_learning_backend(self.training_config, artifact_path=model_id)
        if backend == "mlx_qwen3":
            return await self._rerank_mlx_qwen3(query, chunks, adapter_dir=model_id)
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
                # The Cohere Python SDK's rerank() signature varies across versions; apply timeout at the asyncio layer.
                resp = client.rerank(query=query, documents=docs, model=model, top_n=top_n)
                results = getattr(resp, "results", None) or []
                scores_by_index: dict[int, float] = {}
                for item in results:
                    try:
                        scores_by_index[int(item.index)] = float(item.relevance_score)
                    except Exception:
                        continue
                return [float(scores_by_index.get(i, 0.0)) for i in range(top_n)]

            raise RuntimeError("Cohere client does not support rerank()")

        raw_scores = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout_s)
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
                    "reranker_backend": "transformers",
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

    async def _rerank_mlx_qwen3(self, query: str, chunks: list[ChunkMatch], *, adapter_dir: str) -> list[ChunkMatch]:
        if not mlx_is_available():
            raise RuntimeError("MLX backend requested but MLX is not available")
        if self.training_config is None:
            raise RuntimeError("MLX backend requested but training_config is missing")

        top_n = min(len(chunks), int(self.config.tribrid_reranker_topn))
        if top_n <= 0:
            return chunks

        snippet_chars = int(self.config.rerank_input_snippet_chars)
        max_length = int(self.config.tribrid_reranker_maxlen)
        batch_size = int(self.config.tribrid_reranker_batch)

        candidates = chunks[:top_n]
        remainder = chunks[top_n:]
        snippets = [_snippet(c.content, max_chars=snippet_chars) for c in candidates]

        from server.retrieval.mlx_qwen3 import read_adapter_config, read_manifest

        adapter_path = resolve_project_path(str(adapter_dir)).resolve()
        manifest = read_manifest(adapter_path) or {}
        manifest_base_model = str(manifest.get("base_model") or "").strip()
        base_model = manifest_base_model or str(self.training_config.learning_reranker_base_model)

        adapter_cfg = read_adapter_config(adapter_path) or {}
        lora_rank = int(adapter_cfg.get("lora_rank") or self.training_config.learning_reranker_lora_rank)
        lora_alpha = float(adapter_cfg.get("lora_alpha") or self.training_config.learning_reranker_lora_alpha)
        lora_dropout = float(adapter_cfg.get("lora_dropout") or self.training_config.learning_reranker_lora_dropout)
        target_modules = adapter_cfg.get("target_modules")
        if not isinstance(target_modules, list) or not target_modules:
            target_modules = list(self.training_config.learning_reranker_lora_target_modules)

        rr = await get_mlx_qwen3_reranker(
            base_model=str(base_model),
            adapter_dir=str(adapter_path),
            lora_rank=int(lora_rank),
            lora_alpha=float(lora_alpha),
            lora_dropout=float(lora_dropout),
            lora_target_modules=[str(x) for x in list(target_modules)],
        )

        raw_scores: list[float] = []
        for i in range(0, len(snippets), max(1, batch_size)):
            batch_snips = snippets[i : i + max(1, batch_size)]
            pairs = [(query, s) for s in batch_snips]
            scores, _, _ = await rr.score_pairs_batched(
                pairs,
                max_length=max_length,
                include_logits=False,
                reload_on_change=bool(self.config.tribrid_reranker_reload_on_change),
                reload_period_sec=int(self.config.tribrid_reranker_reload_period_sec),
                unload_after_sec=int(self.training_config.learning_reranker_unload_after_sec),
            )
            raw_scores.extend(scores)

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
                    "reranker_mode": "learning",
                    "reranker_backend": "mlx_qwen3",
                    "learning_reranker_base_model": str(self.training_config.learning_reranker_base_model),
                    "learning_reranker_adapter_dir": str(adapter_dir),
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

        device = resolve_reranker_device()
        model = CrossEncoder(
            model_id,
            max_length=int(max_length),
            device=device,
            trust_remote_code=bool(trust_remote_code),
        )
        _cross_encoder_cache[(model_id, bool(trust_remote_code), device)] = model

    def reload_model(self) -> None:
        """Clear cached models so the next call reloads (best-effort)."""
        _cross_encoder_cache.clear()
