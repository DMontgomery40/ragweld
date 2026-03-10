from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import platform
import re
import time
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from server.indexing.tokenizer import TextTokenizer
from server.models.index import Chunk
from server.models.tribrid_config_model import EmbeddingConfig, TokenizationConfig

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{1,63}")
logger = logging.getLogger(__name__)
_MLX_FALLBACK_WARNED: set[tuple[str, str]] = set()


class Embedder:
    """Deterministic local embedder (placeholder).

    This repo is moving toward provider-backed embeddings (OpenAI/Voyage/local),
    but the backend currently needs a deterministic embedding implementation for
    tests and local dev without external dependencies.
    """

    def __init__(self, config: EmbeddingConfig, tokenization: TokenizationConfig | None = None):
        self.config = config
        self.tokenization = tokenization or TokenizationConfig()
        self._tokenizer = TextTokenizer(self.tokenization)
        # Deterministic embeddings must match the configured dimensionality so that
        # Postgres pgvector storage and stats are consistent across the system.
        self.dim = max(32, int(getattr(config, "embedding_dim", 256) or 256))
        self._cache_enabled = bool(int(getattr(config, "embedding_cache_enabled", 0) or 0) == 1)
        self._cache_lookup_batch: Callable[[list[str]], Awaitable[dict[str, list[float]]]] | None = None
        self._cache_upsert_batch: Callable[[dict[str, tuple[str, list[float]]]], Awaitable[int | None]] | None = None

    def configure_cache_backend(
        self,
        *,
        lookup_batch: Callable[[list[str]], Awaitable[dict[str, list[float]]]],
        upsert_batch: Callable[[dict[str, tuple[str, list[float]]]], Awaitable[int | None]],
    ) -> None:
        self._cache_lookup_batch = lookup_batch
        self._cache_upsert_batch = upsert_batch

    def clear_cache_backend(self) -> None:
        self._cache_lookup_batch = None
        self._cache_upsert_batch = None

    def _prepare_text(self, text: str) -> str:
        t = str(text or "")
        prefix = str(getattr(self.config, "embed_text_prefix", "") or "")
        suffix = str(getattr(self.config, "embed_text_suffix", "") or "")
        combined = f"{prefix}{t}{suffix}"

        max_tok = int(getattr(self.config, "embedding_max_tokens", 0) or 0)
        hard = int(getattr(self.tokenization, "max_tokens_per_chunk_hard", 0) or 0)
        if max_tok <= 0 and hard <= 0:
            return combined
        limit = min([x for x in (max_tok, hard) if x > 0], default=max_tok or hard or 0)
        if limit <= 0:
            return combined
        mode = str(getattr(self.config, "input_truncation", "truncate_end") or "truncate_end")
        return self._tokenizer.truncate_by_tokens(combined, limit, mode=mode)

    def _embed_sync(self, text: str) -> list[float]:
        tokens = _TOKEN_RE.findall((text or "").lower())
        vec = [0.0] * self.dim
        for tok in tokens:
            h = hashlib.md5(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def embed(self, text: str) -> list[float]:
        t = self._prepare_text(text)
        backend = str(getattr(self.config, "embedding_backend", "deterministic") or "deterministic").strip().lower()
        if backend != "provider":
            return await asyncio.to_thread(self._embed_sync, t)

        provider = str(getattr(self.config, "embedding_type", "") or "").strip().lower()
        if provider == "openai":
            return (await self.embed_batch([t]))[0]
        if provider == "mlx":
            return (await self.embed_batch([t]))[0]
        if provider in {"local", "huggingface"}:
            return (await self.embed_batch([t]))[0]
        raise RuntimeError(f"Unsupported embedding provider: {provider}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        prepared = [self._prepare_text(t) for t in (texts or [])]
        if not prepared:
            return []

        lookup_batch = self._cache_lookup_batch
        upsert_batch = self._cache_upsert_batch
        if not (self._cache_enabled and lookup_batch is not None and upsert_batch is not None):
            return await self._embed_batch_uncached(prepared)

        input_hashes = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in prepared]
        unique_hashes = list(dict.fromkeys(input_hashes))
        try:
            cache_hits = await lookup_batch(unique_hashes)
        except Exception:
            cache_hits = {}

        missing_by_hash: dict[str, str] = {}
        for h, txt in zip(input_hashes, prepared, strict=True):
            if h not in cache_hits:
                missing_by_hash[h] = txt

        newly_embedded: dict[str, list[float]] = {}
        if missing_by_hash:
            miss_hashes = list(missing_by_hash.keys())
            miss_texts = [missing_by_hash[h] for h in miss_hashes]
            miss_vecs = await self._embed_batch_uncached(miss_texts)
            for h, vec in zip(miss_hashes, miss_vecs, strict=True):
                newly_embedded[h] = [float(x) for x in vec]
            try:
                await upsert_batch(
                    {h: (missing_by_hash[h], newly_embedded[h]) for h in miss_hashes if h in newly_embedded}
                )
            except Exception:
                pass

        out: list[list[float]] = []
        for h in input_hashes:
            cached = cache_hits.get(h)
            if cached is not None:
                out.append([float(x) for x in cached])
                continue
            fresh = newly_embedded.get(h)
            if fresh is not None:
                out.append([float(x) for x in fresh])
                continue
            # Defensive fallback (should be unreachable): compute from original text for this hash.
            fallback_text = next((t for hh, t in zip(input_hashes, prepared, strict=True) if hh == h), "")
            out.append((await self._embed_batch_uncached([fallback_text]))[0])
        return out

    async def _embed_batch_uncached(self, prepared: list[str]) -> list[list[float]]:
        backend = str(getattr(self.config, "embedding_backend", "deterministic") or "deterministic").strip().lower()
        if backend != "provider":
            return await asyncio.to_thread(lambda: [self._embed_sync(t) for t in prepared])

        provider = str(getattr(self.config, "embedding_type", "") or "").strip().lower()
        if provider == "openai":
            return await self._embed_openai(prepared)
        if provider == "mlx":
            try:
                return await self._embed_mlx_embeddings(prepared)
            except Exception as mlx_err:
                mlx_model = str(getattr(self.config, "embedding_model_mlx", "") or "").strip()
                fallback_model = str(getattr(self.config, "embedding_model_local", "") or "").strip()
                if not fallback_model:
                    raise
                fallback_key = (mlx_model, fallback_model)
                if fallback_key not in _MLX_FALLBACK_WARNED:
                    _MLX_FALLBACK_WARNED.add(fallback_key)
                    logger.warning(
                        "MLX embeddings unavailable for '%s'; falling back to local embeddings model '%s': %s",
                        mlx_model,
                        fallback_model,
                        mlx_err,
                    )
                try:
                    return await self._embed_local_backend(prepared)
                except Exception as local_err:
                    raise RuntimeError(
                        "MLX embeddings failed and local fallback also failed "
                        f"(mlx_model='{mlx_model}', "
                        f"local_model='{fallback_model}'): {local_err}"
                    ) from mlx_err
        if provider in {"local", "huggingface"}:
            return await self._embed_local_backend(prepared)
        raise RuntimeError(f"Unsupported embedding provider: {provider}")

    async def embed_chunks(self, chunks: list[Chunk], *, embed_texts: list[str] | None = None) -> list[Chunk]:
        if not chunks:
            return []
        texts = [c.content for c in chunks] if embed_texts is None else list(embed_texts)
        if len(texts) != len(chunks):
            raise ValueError("embed_texts length must match chunks length")
        embeddings = await self.embed_batch(texts)
        return [c.model_copy(update={"embedding": emb}) for c, emb in zip(chunks, embeddings, strict=True)]

    # ---------------------------------------------------------------------
    # Provider backends
    # ---------------------------------------------------------------------

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI

        model = str(getattr(self.config, "embedding_model", "") or "").strip()
        if not model:
            raise RuntimeError("embedding_model is required for OpenAI embeddings")

        timeout_s = float(getattr(self.config, "embedding_timeout", 30) or 30)
        retries = int(getattr(self.config, "embedding_retry_max", 3) or 3)

        client = AsyncOpenAI()
        last_err: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                resp = await client.embeddings.create(
                    model=model,
                    input=texts,
                    timeout=timeout_s,
                )
                data = getattr(resp, "data", None) or []
                vecs: list[list[float]] = []
                for item in data:
                    emb = getattr(item, "embedding", None)
                    if not isinstance(emb, list):
                        raise RuntimeError("OpenAI embeddings response missing embedding vectors")
                    vecs.append([float(x) for x in emb])
                for v in vecs:
                    if len(v) != self.dim:
                        raise RuntimeError(f"Embedding dimension mismatch ({len(v)} != {self.dim}). Reindex after updating embedding_dim.")
                return vecs
            except Exception as e:
                last_err = e
                if attempt + 1 >= max(1, retries):
                    break
                await asyncio.sleep(min(2.0, 0.25 * (2**attempt)))
        raise RuntimeError(f"OpenAI embeddings failed: {last_err}")

    @staticmethod
    @lru_cache(maxsize=8)
    def _load_sentence_transformer(model_name: str) -> Any:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name)

    @staticmethod
    def _mlx_platform_supported() -> bool:
        return platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}

    @staticmethod
    @lru_cache(maxsize=16)
    def _load_mlx_embeddings(model_name: str) -> tuple[Any, Any] | None:
        """Load an MLX embedding model/tokenizer pair (cached).

        Returns None if mlx-embeddings is unavailable or the model fails to load.
        """
        if not Embedder._mlx_platform_supported():
            return None
        try:
            from mlx_embeddings.utils import load

            model, tokenizer = load(str(model_name))
            return (model, tokenizer)
        except Exception:
            return None

    @staticmethod
    def _mlx_candidate_models(model_name: str) -> list[tuple[str, bool]]:
        """Return [(candidate_name, derived)] in priority order.

        - derived=True means we inferred the candidate (safe to ignore on mismatch).
        """
        raw = str(model_name or "").strip()
        if not raw:
            return []

        # If user points at a local path, don't try to guess.
        if raw.startswith(("/", "./", "../", "~")):
            return [(raw, False)]

        # If the repo name already looks MLX-specific, use it as-is.
        lowered = raw.lower()
        if raw.startswith("mlx-community/") or lowered.endswith("-mlx") or lowered.endswith("-mlx-4bit"):
            return [(raw, False)]

        # Heuristic: many MLX community conversions keep the *tail* name and add a quant suffix.
        tail = raw.split("/")[-1]
        cands: list[tuple[str, bool]] = [
            (f"mlx-community/{tail}-4bit", True),
            (f"mlx-community/{tail}", True),
        ]
        if raw not in {c for c, _ in cands}:
            # Allow explicit non-mlx-community repos that still host MLX-format weights.
            cands.append((raw, False))
        return cands

    @staticmethod
    def _resolve_max_length(tokenizer: Any, requested: int | None) -> int | None:
        req = int(requested) if requested is not None else 0
        if req <= 0:
            req = 0

        model_max = getattr(tokenizer, "model_max_length", None)
        if model_max is None:
            model_max_int = 0
        else:
            try:
                model_max_int = int(model_max)
            except Exception:
                model_max_int = 0

        # HuggingFace uses very large sentinels for "infinite"; treat those as unknown.
        if model_max_int <= 0 or model_max_int >= 1_000_000:
            return int(req) if req > 0 else None

        if req > 0:
            return int(min(req, model_max_int))
        return int(model_max_int)

    async def _try_embed_local_mlx_embeddings(self, texts: list[str]) -> list[list[float]] | None:
        """Best-effort MLX embeddings (Apple Silicon only).

        Returns None when MLX embeddings are unavailable for the configured model; callers should
        fall back to a CPU/GPU torch backend (SentenceTransformers / HF).
        """
        if not self._mlx_platform_supported():
            return None

        model_name = str(getattr(self.config, "embedding_model_local", "") or "").strip()
        if not model_name:
            return None

        batch_size = int(getattr(self.config, "embedding_batch_size", 32) or 32)
        requested_max = int(getattr(self.config, "embedding_max_tokens", 0) or 0) or None

        candidates = self._mlx_candidate_models(model_name)
        for cand, derived in candidates:
            loaded = self._load_mlx_embeddings(cand)
            if loaded is None:
                continue
            model, tokenizer = loaded
            max_length = self._resolve_max_length(tokenizer, requested_max)

            def _run(
                _model: Any = model,
                _tokenizer: Any = tokenizer,
                _max_length: int | None = max_length,
                _texts: list[str] = texts,
                _batch_size: int = batch_size,
            ) -> list[list[float]]:
                out: list[list[float]] = []
                for i in range(0, len(_texts), max(1, _batch_size)):
                    batch = _texts[i : i + max(1, _batch_size)]
                    enc = _tokenizer.batch_encode_plus(
                        batch,
                        return_tensors="mlx",
                        padding=True,
                        truncation=True,
                        max_length=int(_max_length) if _max_length else None,
                    )
                    outputs = _model(enc["input_ids"], attention_mask=enc.get("attention_mask"))
                    embeds = getattr(outputs, "text_embeds", None)
                    if embeds is None:
                        raise RuntimeError("mlx-embeddings output missing text_embeds")
                    rows = embeds.tolist()
                    if isinstance(rows, list) and rows and not isinstance(rows[0], list):
                        rows = [rows]
                    for v in rows:
                        out.append([float(x) for x in list(v)])
                return out

            try:
                vecs = await asyncio.to_thread(_run)
            except Exception:
                continue

            if any(len(v) != self.dim for v in vecs):
                if derived:
                    # If we guessed the candidate name, don't hard-fail.
                    continue
                raise RuntimeError(
                    "Embedding dimension mismatch. "
                    f"Configured embedding_dim={self.dim}, but MLX model '{cand}' returned {len(vecs[0]) if vecs else 0}."
                )
            return vecs

        return None

    async def _embed_mlx_embeddings(self, texts: list[str]) -> list[list[float]]:
        """MLX embeddings backend (Apple Silicon only).

        Unlike _try_embed_local_mlx_embeddings, this is NOT best-effort: it raises on unsupported platforms
        or missing/failed model loads.
        """
        if not self._mlx_platform_supported():
            raise RuntimeError("embedding_type='mlx' requires Apple Silicon macOS (Darwin arm64) with MLX installed")

        model_name = str(getattr(self.config, "embedding_model_mlx", "") or "").strip()
        if not model_name:
            raise RuntimeError("embedding_model_mlx is required when embedding_type='mlx'")

        batch_size = int(getattr(self.config, "embedding_batch_size", 32) or 32)
        requested_max = int(getattr(self.config, "embedding_max_tokens", 0) or 0) or None

        last_err: Exception | None = None
        candidates = self._mlx_candidate_models(model_name)
        if not candidates:
            raise RuntimeError("No MLX embedding model configured")

        for cand, derived in candidates:
            loaded = self._load_mlx_embeddings(cand)
            if loaded is None:
                continue
            model, tokenizer = loaded
            max_length = self._resolve_max_length(tokenizer, requested_max)

            def _run(
                _model: Any = model,
                _tokenizer: Any = tokenizer,
                _max_length: int | None = max_length,
                _texts: list[str] = texts,
                _batch_size: int = batch_size,
            ) -> list[list[float]]:
                out: list[list[float]] = []
                for i in range(0, len(_texts), max(1, _batch_size)):
                    batch = _texts[i : i + max(1, _batch_size)]
                    enc = _tokenizer.batch_encode_plus(
                        batch,
                        return_tensors="mlx",
                        padding=True,
                        truncation=True,
                        max_length=int(_max_length) if _max_length else None,
                    )
                    outputs = _model(enc["input_ids"], attention_mask=enc.get("attention_mask"))
                    embeds = getattr(outputs, "text_embeds", None)
                    if embeds is None:
                        raise RuntimeError("mlx-embeddings output missing text_embeds")
                    rows = embeds.tolist()
                    if isinstance(rows, list) and rows and not isinstance(rows[0], list):
                        rows = [rows]
                    for v in rows:
                        out.append([float(x) for x in list(v)])
                return out

            try:
                vecs = await asyncio.to_thread(_run)
                if any(len(v) != self.dim for v in vecs):
                    if derived:
                        continue
                    raise RuntimeError(
                        "Embedding dimension mismatch. "
                        f"Configured embedding_dim={self.dim}, but MLX model '{cand}' returned {len(vecs[0]) if vecs else 0}."
                    )
                return vecs
            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(f"MLX embeddings failed to load/embed for '{model_name}': {last_err}")

    async def _embed_local_backend(self, texts: list[str]) -> list[list[float]]:
        mode = str(getattr(self.config, "contextual_chunk_embeddings", "off") or "off").strip().lower()
        if mode == "late_chunking_local_only":
            return await self._embed_local_hf_mean_pool(texts)
        mlx_vecs = await self._try_embed_local_mlx_embeddings(texts)
        if mlx_vecs is not None:
            return mlx_vecs
        return await self._embed_local_sentence_transformers(texts)

    async def _embed_local_sentence_transformers(self, texts: list[str]) -> list[list[float]]:
        model_name = str(getattr(self.config, "embedding_model_local", "") or "").strip()
        if not model_name:
            raise RuntimeError("embedding_model_local is required for local embeddings")

        batch_size = int(getattr(self.config, "embedding_batch_size", 32) or 32)
        model = self._load_sentence_transformer(model_name)

        def _run() -> list[list[float]]:
            vecs = model.encode(
                texts,
                batch_size=max(1, batch_size),
                normalize_embeddings=True,
                convert_to_numpy=False,
                show_progress_bar=False,
            )
            out: list[list[float]] = []
            for v in vecs:
                try:
                    arr = [float(x) for x in v]
                except Exception:
                    arr = [float(x) for x in list(v)]
                out.append(arr)
            return out

        t0 = time.perf_counter()
        vecs = await asyncio.to_thread(_run)
        _ = t0
        for v in vecs:
            if len(v) != self.dim:
                raise RuntimeError(f"Embedding dimension mismatch ({len(v)} != {self.dim}). Reindex after updating embedding_dim.")
        return vecs

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_hf_tokenizer(model_name: str) -> Any:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(model_name, use_fast=True)  # type: ignore[no-untyped-call]

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_hf_model(model_name: str) -> Any:
        import torch
        from transformers import AutoModel

        m = AutoModel.from_pretrained(model_name)
        m.eval()
        if torch.backends.mps.is_available():
            m.to(torch.device("mps"))
        return m

    async def _embed_local_hf_mean_pool(self, texts: list[str]) -> list[list[float]]:
        import torch

        model_name = str(getattr(self.config, "embedding_model_local", "") or "").strip()
        if not model_name:
            raise RuntimeError("embedding_model_local is required for local HF embeddings")

        tokenizer = self._load_hf_tokenizer(model_name)
        model = self._load_hf_model(model_name)
        max_len = int(getattr(self.config, "embedding_max_tokens", 0) or 0) or None

        def _run() -> list[list[float]]:
            device = next(model.parameters()).device
            enc = tokenizer(
                texts,
                padding=True,
                truncation=True if max_len else False,
                max_length=int(max_len) if max_len else None,
                add_special_tokens=False,
                return_tensors="pt",
            )
            input_ids = enc["input_ids"].to(device)
            attention_mask = enc.get("attention_mask")
            if attention_mask is not None:
                attention_mask = attention_mask.to(device)
            with torch.no_grad():
                out = model(input_ids=input_ids, attention_mask=attention_mask)
                h = getattr(out, "last_hidden_state", None)
                if h is None:
                    raise RuntimeError("HF model output missing last_hidden_state")
                if attention_mask is None:
                    pooled = h.mean(dim=1)
                else:
                    m = attention_mask.unsqueeze(-1).to(h.dtype)
                    denom = m.sum(dim=1).clamp_min(1.0)
                    pooled = (h * m).sum(dim=1) / denom
                pooled = pooled / torch.linalg.norm(pooled, ord=2, dim=-1, keepdim=True).clamp_min(1e-12)
            vecs = pooled.cpu().tolist()
            return [[float(x) for x in v] for v in vecs]

        vecs = await asyncio.to_thread(_run)
        for v in vecs:
            if len(v) != self.dim:
                raise RuntimeError(f"Embedding dimension mismatch ({len(v)} != {self.dim}). Reindex after updating embedding_dim.")
        return vecs
