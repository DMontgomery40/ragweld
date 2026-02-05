from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from functools import lru_cache
from typing import Any

from server.models.index import Chunk
from server.indexing.tokenizer import TextTokenizer
from server.models.tribrid_config_model import EmbeddingConfig, TokenizationConfig

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{1,63}")


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
        if provider in {"local", "huggingface"}:
            return (await self.embed_batch([t]))[0]
        raise RuntimeError(f"Unsupported embedding provider: {provider}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        prepared = [self._prepare_text(t) for t in (texts or [])]
        backend = str(getattr(self.config, "embedding_backend", "deterministic") or "deterministic").strip().lower()
        if backend != "provider":
            return await asyncio.to_thread(lambda: [self._embed_sync(t) for t in prepared])

        provider = str(getattr(self.config, "embedding_type", "") or "").strip().lower()
        if provider == "openai":
            return await self._embed_openai(prepared)
        if provider in {"local", "huggingface"}:
            mode = str(getattr(self.config, "contextual_chunk_embeddings", "off") or "off").strip().lower()
            if mode == "late_chunking_local_only":
                return await self._embed_local_hf_mean_pool(prepared)
            return await self._embed_local_sentence_transformers(prepared)
        raise RuntimeError(f"Unsupported embedding provider: {provider}")

    async def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return []
        embeddings = await self.embed_batch([c.content for c in chunks])
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
        from transformers import AutoModel

        m = AutoModel.from_pretrained(model_name)
        m.eval()
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
            enc = tokenizer(
                texts,
                padding=True,
                truncation=True if max_len else False,
                max_length=int(max_len) if max_len else None,
                add_special_tokens=False,
                return_tensors="pt",
            )
            with torch.no_grad():
                out = model(input_ids=enc["input_ids"], attention_mask=enc.get("attention_mask"))
                h = getattr(out, "last_hidden_state", None)
                if h is None:
                    raise RuntimeError("HF model output missing last_hidden_state")
                mask = enc.get("attention_mask")
                if mask is None:
                    pooled = h.mean(dim=1)
                else:
                    m = mask.unsqueeze(-1).to(h.dtype)
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
