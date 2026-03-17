"""Semantic cache service for retrieval and generation payloads."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder, configure_postgres_embedding_cache_backend
from server.models.tribrid_config_model import SemanticCacheConfig, TriBridConfig
from server.observability.metrics import (
    SEMANTIC_CACHE_LOOKUP_LATENCY_SECONDS,
    SEMANTIC_CACHE_LOOKUPS_TOTAL,
    SEMANTIC_CACHE_SEMANTIC_SIMILARITY,
    SEMANTIC_CACHE_WRITES_TOTAL,
)

CacheMode = Literal["default", "bypass", "refresh"]
CacheAction = Literal["read", "write"]
CacheEndpoint = Literal["search", "answer", "chat"]

_WS_RE = re.compile(r"\s+")


def _normalize_query(text: str) -> str:
    return _WS_RE.sub(" ", str(text or "").strip()).lower()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class SemanticCacheHit:
    payload: dict[str, Any]
    match_type: Literal["exact", "semantic"]
    similarity: float
    exact_key: str


class SemanticCacheService:
    """High-level semantic cache wrapper over Postgres storage."""

    def __init__(self, config: TriBridConfig):
        self._config = config
        self._cache_cfg: SemanticCacheConfig = config.semantic_cache
        self._pg = PostgresClient(config.indexing.postgres_url)
        self._embedder = Embedder(config.embedding, config.tokenization)
        configure_postgres_embedding_cache_backend(self._embedder, self._pg)

    @property
    def cfg(self) -> SemanticCacheConfig:
        return self._cache_cfg

    @staticmethod
    def scope_key(corpus_ids: list[str]) -> str:
        norm = [str(cid).strip() for cid in (corpus_ids or []) if str(cid).strip()]
        return "corpora:" + "|".join(sorted(dict.fromkeys(norm)))

    @staticmethod
    def canonical_query(query: str) -> str:
        return _normalize_query(query)

    @staticmethod
    def fingerprint(value: Any) -> str:
        return _digest(value)

    @staticmethod
    def context_fingerprint(value: Any) -> str:
        return _digest(value)

    def _is_enabled(self) -> bool:
        return int(self._cache_cfg.enabled or 0) == 1

    def _allows(self, action: CacheAction, cache_mode: CacheMode) -> bool:
        mode = str(cache_mode or "default").strip().lower()
        if mode == "bypass":
            return False
        if not self._is_enabled():
            return False
        configured = str(self._cache_cfg.mode or "read_write").strip().lower()
        if action == "read":
            if mode == "refresh":
                return False
            return configured in {"read_only", "read_write"}
        return configured in {"write_only", "read_write"}

    def _is_query_eligible(self, query: str) -> bool:
        return len(self.canonical_query(query)) >= int(self._cache_cfg.min_query_chars or 1)

    def threshold(self, endpoint: CacheEndpoint) -> float:
        if endpoint == "answer":
            return float(self._cache_cfg.similarity_threshold_answer)
        if endpoint == "chat":
            return float(self._cache_cfg.similarity_threshold_chat)
        return float(self._cache_cfg.similarity_threshold_search)

    def ttl_seconds(self, endpoint: CacheEndpoint) -> int:
        if endpoint == "answer":
            return int(self._cache_cfg.ttl_seconds_answer)
        if endpoint == "chat":
            return int(self._cache_cfg.ttl_seconds_chat)
        return int(self._cache_cfg.ttl_seconds_search)

    @staticmethod
    def exact_key(*, query: str, request_fingerprint: str) -> str:
        return _digest({"q": _normalize_query(query), "fp": str(request_fingerprint or "")})

    async def lookup(
        self,
        *,
        endpoint: CacheEndpoint,
        scope_key: str,
        query: str,
        request_fingerprint: str,
        cache_mode: CacheMode = "default",
        allow_semantic: bool = True,
    ) -> SemanticCacheHit | None:
        if not self._allows("read", cache_mode):
            SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=endpoint, outcome="bypass").inc()
            return None
        if not self._is_query_eligible(query):
            SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=endpoint, outcome="too_short").inc()
            return None

        norm_query = self.canonical_query(query)
        ex_key = self.exact_key(query=norm_query, request_fingerprint=request_fingerprint)
        try:
            await self._pg.connect()
            with SEMANTIC_CACHE_LOOKUP_LATENCY_SECONDS.labels(endpoint=endpoint).time():
                exact = await self._pg.semantic_cache_lookup_exact(
                    scope_key=scope_key,
                    endpoint=endpoint,
                    exact_key=ex_key,
                )
            if exact is not None:
                await self._pg.semantic_cache_touch(scope_key=scope_key, endpoint=endpoint, exact_key=ex_key)
                SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=endpoint, outcome="hit_exact").inc()
                return SemanticCacheHit(
                    payload=dict(exact.get("payload") or {}),
                    match_type="exact",
                    similarity=1.0,
                    exact_key=ex_key,
                )

            if not allow_semantic:
                SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=endpoint, outcome="miss").inc()
                return None

            query_embedding = await self._embedder.embed(norm_query)
            with SEMANTIC_CACHE_LOOKUP_LATENCY_SECONDS.labels(endpoint=endpoint).time():
                sem = await self._pg.semantic_cache_lookup_semantic(
                    scope_key=scope_key,
                    endpoint=endpoint,
                    query_embedding=query_embedding,
                    request_fingerprint=str(request_fingerprint or ""),
                    min_similarity=self.threshold(endpoint),
                )
            if sem is None:
                SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=endpoint, outcome="miss").inc()
                return None

            sem_key = str(sem.get("exact_key") or "")
            if sem_key:
                await self._pg.semantic_cache_touch(scope_key=scope_key, endpoint=endpoint, exact_key=sem_key)
            similarity = float(sem.get("similarity") or 0.0)
            SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=endpoint, outcome="hit_semantic").inc()
            SEMANTIC_CACHE_SEMANTIC_SIMILARITY.labels(endpoint=endpoint).observe(similarity)
            return SemanticCacheHit(
                payload=dict(sem.get("payload") or {}),
                match_type="semantic",
                similarity=similarity,
                exact_key=sem_key or ex_key,
            )
        except Exception:
            SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=endpoint, outcome="error").inc()
            return None

    async def write(
        self,
        *,
        endpoint: CacheEndpoint,
        scope_key: str,
        query: str,
        request_fingerprint: str,
        payload: dict[str, Any],
        cache_mode: CacheMode = "default",
    ) -> bool:
        if not self._allows("write", cache_mode):
            SEMANTIC_CACHE_WRITES_TOTAL.labels(endpoint=endpoint, outcome="bypass").inc()
            return False
        if not self._is_query_eligible(query):
            SEMANTIC_CACHE_WRITES_TOTAL.labels(endpoint=endpoint, outcome="too_short").inc()
            return False
        try:
            norm_query = self.canonical_query(query)
            ex_key = self.exact_key(query=norm_query, request_fingerprint=request_fingerprint)
            await self._pg.connect()
            try:
                query_embedding = await self._embedder.embed(norm_query)
            except Exception:
                query_embedding = None
            await self._pg.semantic_cache_upsert(
                scope_key=scope_key,
                endpoint=endpoint,
                exact_key=ex_key,
                query_text=norm_query,
                query_embedding=query_embedding,
                request_fingerprint=str(request_fingerprint or ""),
                payload=dict(payload or {}),
                ttl_seconds=self.ttl_seconds(endpoint),
            )
            await self._pg.semantic_cache_delete_expired(scope_key=scope_key, endpoint=endpoint)
            await self._pg.semantic_cache_prune_lru(
                scope_key=scope_key,
                endpoint=endpoint,
                max_entries=int(self._cache_cfg.max_entries),
            )
            SEMANTIC_CACHE_WRITES_TOTAL.labels(endpoint=endpoint, outcome="ok").inc()
            return True
        except Exception:
            SEMANTIC_CACHE_WRITES_TOTAL.labels(endpoint=endpoint, outcome="error").inc()
            return False
