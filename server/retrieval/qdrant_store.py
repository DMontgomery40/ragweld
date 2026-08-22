"""Canonical Qdrant chunk-vector store (dense + IDF sparse) for ragweld corpora.

Ownership boundary:

- Postgres keeps chunk rows as control/state (hydration, summaries, neighbor
  expansion, graph hydration) and the recorded dense/sparse contracts.
- Qdrant keeps the dense and sparse vectors for every corpus. Each corpus is
  addressed through a stable alias (`ragweld_chunks_<corpus>`) that points at
  one physical generation; a full index builds a fresh staged generation and
  promotes it with an atomic alias switch.
- Neo4j keeps its own chunk-vector index as the graph leg's implementation
  detail; it is not a vector engine for the vector leg.

Writes go through the Haystack Qdrant document store so the collection schema
(named `text-dense` / `text-sparse` vectors, IDF modifier) is the Haystack
contract. Reads use the Qdrant client directly against the alias so a missing
or wiped generation reads as missing instead of being silently auto-created.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from server.dependency_errors import DependencyUnavailableError
from server.models.index import Chunk
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.contracts import (
    SPARSE_ENGINE,
    SPARSE_MODEL,
    contract_hash,
    sparse_contract_from_config,
)

logger = logging.getLogger(__name__)

DENSE_VECTOR_NAME = "text-dense"
SPARSE_VECTOR_NAME = "text-sparse"
_ALIAS_PREFIX = "ragweld_chunks_"

# Chunk metadata keys that are copied into the Qdrant payload as first-class
# provenance so every hit can become a citation without a Postgres round trip.
_PAYLOAD_META_KEYS = ("chunk_ordinal", "parent_doc_id", "char_start", "char_end", "extraction", "kind")

_SPARSE_DOC_EMBEDDERS: dict[str, Any] = {}
_SPARSE_TEXT_EMBEDDERS: dict[str, Any] = {}
_SPARSE_EMBEDDER_LOCK = asyncio.Lock()
# Serializes first-write generation creation per alias (incremental upserts).
_ALIAS_LOCKS: dict[str, asyncio.Lock] = {}


class QdrantCollectionMissingError(RuntimeError):
    """The corpus alias (or its physical generation) does not exist in Qdrant."""

    def __init__(self, corpus_id: str, alias: str) -> None:
        self.corpus_id = corpus_id
        self.alias = alias
        super().__init__(f"Qdrant collection '{alias}' for corpus '{corpus_id}' does not exist")


@dataclass(frozen=True)
class QdrantCorpusStatus:
    corpus_id: str
    alias: str
    physical_collection: str | None
    points: int
    dense_points: int
    dense_dimensions: int


def corpus_alias(corpus_id: str) -> str:
    """Stable, injective alias for a corpus.

    The readable part is sanitized (Qdrant names are restricted), so distinct
    corpus ids such as `my-repo` / `my_repo` / `My.Repo` would collide on it
    alone; the sha1 suffix of the exact corpus id keeps the alias injective.
    Generations are `<alias>__<hex>`, and the suffix guarantees no other
    corpus alias can be a prefix of this corpus's generations.
    """
    raw = str(corpus_id or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_").lower()[:48] or "unknown"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{_ALIAS_PREFIX}{safe}_{digest}"


def _alias_lock(alias: str) -> asyncio.Lock:
    lock = _ALIAS_LOCKS.get(alias)
    if lock is None:
        lock = asyncio.Lock()
        _ALIAS_LOCKS[alias] = lock
    return lock


def point_id_for_chunk(chunk_id: str) -> str:
    """Deterministic point id matching the Haystack Qdrant converter."""
    from haystack_integrations.document_stores.qdrant.converters import UUID_NAMESPACE

    return uuid.uuid5(UUID_NAMESPACE, str(chunk_id)).hex


def is_qdrant_unavailable(exc: BaseException) -> bool:
    from qdrant_client.http.exceptions import ResponseHandlingException

    return isinstance(exc, (ConnectionError, TimeoutError, OSError, ResponseHandlingException))


def _is_not_found(exc: BaseException) -> bool:
    from qdrant_client.http.exceptions import UnexpectedResponse

    return isinstance(exc, UnexpectedResponse) and int(getattr(exc, "status_code", 0) or 0) == 404


def _sparse_model_kwargs(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "k": float(contract["k1"]),
        "b": float(contract["b"]),
        "language": str(contract["language"]),
        "disable_stemmer": not bool(contract["stemmer"]),
    }


async def _sparse_doc_embedder(contract: dict[str, Any]) -> Any:
    key = contract_hash(contract)
    async with _SPARSE_EMBEDDER_LOCK:
        embedder = _SPARSE_DOC_EMBEDDERS.get(key)
        if embedder is None:
            from haystack_integrations.components.embedders.fastembed import (
                FastembedSparseDocumentEmbedder,
            )

            embedder = FastembedSparseDocumentEmbedder(
                model=SPARSE_MODEL,
                progress_bar=False,
                model_kwargs=_sparse_model_kwargs(contract),
            )
            await asyncio.to_thread(embedder.warm_up)
            _SPARSE_DOC_EMBEDDERS[key] = embedder
    return embedder


async def _sparse_text_embedder(contract: dict[str, Any]) -> Any:
    key = contract_hash(contract)
    async with _SPARSE_EMBEDDER_LOCK:
        embedder = _SPARSE_TEXT_EMBEDDERS.get(key)
        if embedder is None:
            from haystack_integrations.components.embedders.fastembed import (
                FastembedSparseTextEmbedder,
            )

            embedder = FastembedSparseTextEmbedder(
                model=SPARSE_MODEL,
                progress_bar=False,
                model_kwargs=_sparse_model_kwargs(contract),
            )
            await asyncio.to_thread(embedder.warm_up)
            _SPARSE_TEXT_EMBEDDERS[key] = embedder
    return embedder


def _chunk_to_document(corpus_id: str, chunk: Chunk) -> Any:
    from haystack import Document

    metadata = dict(chunk.metadata or {})
    meta: dict[str, Any] = {
        "corpus_id": corpus_id,
        "file_path": str(chunk.file_path),
        "start_line": int(chunk.start_line),
        "end_line": int(chunk.end_line),
        "language": chunk.language,
        "token_count": int(chunk.token_count or 0),
    }
    for key in _PAYLOAD_META_KEYS:
        if key in metadata and metadata[key] is not None:
            meta[key] = metadata[key]
    return Document(
        id=str(chunk.chunk_id),
        content=str(chunk.content or ""),
        embedding=list(chunk.embedding) if chunk.embedding else None,
        meta=meta,
    )


def _point_to_match(point: Any, *, source: str, corpus_id: str) -> ChunkMatch:
    payload = dict(point.payload or {})
    meta = dict(payload.get("meta") or {})
    language = meta.get("language")
    metadata: dict[str, Any] = {
        k: v for k, v in meta.items() if k not in {"file_path", "start_line", "end_line", "language"}
    }
    metadata["corpus_id"] = corpus_id
    if source == "sparse":
        metadata["sparse_engine"] = SPARSE_ENGINE
    return ChunkMatch(
        chunk_id=str(payload.get("id") or ""),
        content=str(payload.get("content") or ""),
        file_path=str(meta.get("file_path") or ""),
        start_line=int(meta.get("start_line") or 1),
        end_line=int(meta.get("end_line") or 1),
        language=str(language) if language is not None else None,
        score=float(getattr(point, "score", 0.0) or 0.0),
        source=source,  # type: ignore[arg-type]
        metadata=metadata,
    )


class QdrantChunkStore:
    """Corpus-scoped dense + sparse vector store on the Compose-owned Qdrant service."""

    def __init__(self, config: TriBridConfig) -> None:
        self.url = str(config.qdrant.url or "").strip().rstrip("/")
        self.sparse_contract = sparse_contract_from_config(config)

    # ------------------------------------------------------------------
    # Client / error plumbing
    # ------------------------------------------------------------------

    def _client(self) -> Any:
        from qdrant_client import QdrantClient

        return QdrantClient(url=self.url, timeout=30)

    def _raise_boundary(self, exc: BaseException, *, operation: str, corpus_id: str, alias: str) -> None:
        if is_qdrant_unavailable(exc):
            raise DependencyUnavailableError("qdrant", operation) from exc
        if _is_not_found(exc):
            raise QdrantCollectionMissingError(corpus_id, alias) from exc

    def _resolve_physical_sync(self, client: Any, alias: str) -> str | None:
        for item in client.get_aliases().aliases:
            if str(item.alias_name) == alias:
                return str(item.collection_name)
        return None

    # ------------------------------------------------------------------
    # Staged generations (full index runs)
    # ------------------------------------------------------------------

    def _document_store(self, physical: str, *, embedding_dim: int, recreate: bool) -> Any:
        from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

        return QdrantDocumentStore(
            url=self.url,
            index=physical,
            embedding_dim=max(1, int(embedding_dim)),
            recreate_index=bool(recreate),
            use_sparse_embeddings=True,
            sparse_idf=True,
            progress_bar=False,
            timeout=60,
        )

    @staticmethod
    def _close_store(store: Any) -> None:
        client = getattr(store, "_client", None)
        if client is not None:
            client.close()

    async def create_generation(self, corpus_id: str, *, embedding_dim: int) -> str:
        """Create a fresh physical generation for a corpus (not yet visible through the alias)."""
        alias = corpus_alias(corpus_id)
        physical = f"{alias}__{uuid.uuid4().hex[:8]}"

        def _create() -> None:
            store = self._document_store(physical, embedding_dim=embedding_dim, recreate=True)
            try:
                store.count_documents()
            finally:
                self._close_store(store)

        try:
            await asyncio.to_thread(_create)
        except Exception as exc:
            self._raise_boundary(exc, operation="Qdrant generation create", corpus_id=corpus_id, alias=alias)
            raise
        return physical

    async def write_chunks(self, corpus_id: str, physical: str, chunks: list[Chunk], *, embedding_dim: int) -> int:
        """Write dense + sparse vectors for chunks into a physical generation."""
        if not chunks:
            return 0
        from haystack.document_stores.types import DuplicatePolicy

        documents = [_chunk_to_document(corpus_id, chunk) for chunk in chunks]
        sparse_embedder = await _sparse_doc_embedder(self.sparse_contract)
        documents = await asyncio.to_thread(lambda: list(sparse_embedder.run(documents=documents)["documents"]))

        def _write() -> int:
            store = self._document_store(physical, embedding_dim=embedding_dim, recreate=False)
            try:
                return int(store.write_documents(documents, policy=DuplicatePolicy.OVERWRITE))
            finally:
                self._close_store(store)

        try:
            return await asyncio.to_thread(_write)
        except Exception as exc:
            self._raise_boundary(exc, operation="Qdrant chunk write", corpus_id=corpus_id, alias=corpus_alias(corpus_id))
            raise

    async def count_points(self, physical: str) -> int:
        """Exact point count of a physical generation (staged or live)."""

        def _count() -> int:
            client = self._client()
            try:
                return int(client.count(physical, exact=True).count)
            finally:
                client.close()

        try:
            return await asyncio.to_thread(_count)
        except Exception as exc:
            if is_qdrant_unavailable(exc):
                raise DependencyUnavailableError("qdrant", "Qdrant generation count") from exc
            raise

    async def promote_generation(self, corpus_id: str, physical: str) -> None:
        """Atomically point the corpus alias at `physical`; remove superseded generations.

        The alias is injective per corpus, so every `<alias>__*` collection
        other than `physical` is a superseded or orphaned generation of this
        corpus (a previous live generation, or a staged generation left by a
        run that died before it could drop it).
        """
        from qdrant_client import models as qmodels

        alias = corpus_alias(corpus_id)

        def _promote() -> None:
            client = self._client()
            try:
                previous = self._resolve_physical_sync(client, alias)
                if previous is None and client.collection_exists(alias):
                    # A physical collection occupying the alias name cannot coexist with the alias.
                    client.delete_collection(alias)
                operations: list[Any] = []
                if previous is not None:
                    operations.append(qmodels.DeleteAliasOperation(delete_alias=qmodels.DeleteAlias(alias_name=alias)))
                operations.append(
                    qmodels.CreateAliasOperation(
                        create_alias=qmodels.CreateAlias(collection_name=physical, alias_name=alias)
                    )
                )
                client.update_collection_aliases(change_aliases_operations=operations)
                for collection in client.get_collections().collections:
                    name = str(collection.name)
                    if name.startswith(f"{alias}__") and name != physical:
                        client.delete_collection(name)
            finally:
                client.close()

        try:
            await asyncio.to_thread(_promote)
        except Exception as exc:
            self._raise_boundary(exc, operation="Qdrant generation promote", corpus_id=corpus_id, alias=alias)
            raise

    async def drop_generation(self, physical: str) -> None:
        def _drop() -> None:
            client = self._client()
            try:
                if client.collection_exists(physical):
                    client.delete_collection(physical)
            finally:
                client.close()

        try:
            await asyncio.to_thread(_drop)
        except Exception as exc:
            if is_qdrant_unavailable(exc):
                raise DependencyUnavailableError("qdrant", "Qdrant generation drop") from exc
            raise

    async def delete_corpus(self, corpus_id: str) -> int:
        """Remove the alias and every physical generation for a corpus; returns collections removed."""
        from qdrant_client import models as qmodels

        alias = corpus_alias(corpus_id)

        def _delete() -> int:
            client = self._client()
            removed = 0
            try:
                if self._resolve_physical_sync(client, alias) is not None:
                    client.update_collection_aliases(
                        change_aliases_operations=[
                            qmodels.DeleteAliasOperation(delete_alias=qmodels.DeleteAlias(alias_name=alias))
                        ]
                    )
                for collection in list(client.get_collections().collections):
                    name = str(collection.name)
                    if name == alias or name.startswith(f"{alias}__"):
                        client.delete_collection(name)
                        removed += 1
            finally:
                client.close()
            return removed

        try:
            return await asyncio.to_thread(_delete)
        except Exception as exc:
            self._raise_boundary(exc, operation="Qdrant corpus delete", corpus_id=corpus_id, alias=alias)
            raise

    # ------------------------------------------------------------------
    # Incremental writes (recall and other append-only corpora)
    # ------------------------------------------------------------------

    async def upsert_chunks(self, corpus_id: str, chunks: list[Chunk], *, embedding_dim: int) -> int:
        """Upsert chunks into the live generation, creating and aliasing one when missing."""
        if not chunks:
            return 0
        alias = corpus_alias(corpus_id)

        def _resolve() -> str | None:
            client = self._client()
            try:
                return self._resolve_physical_sync(client, alias)
            finally:
                client.close()

        async with _alias_lock(alias):
            try:
                physical = await asyncio.to_thread(_resolve)
            except Exception as exc:
                self._raise_boundary(exc, operation="Qdrant alias resolve", corpus_id=corpus_id, alias=alias)
                raise
            if physical is None:
                physical = await self.create_generation(corpus_id, embedding_dim=embedding_dim)
                await self.promote_generation(corpus_id, physical)
            return await self.write_chunks(corpus_id, physical, chunks, embedding_dim=embedding_dim)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def status(self, corpus_id: str) -> QdrantCorpusStatus | None:
        """Live collection status for a corpus; None when the alias does not exist."""
        from qdrant_client import models as qmodels

        alias = corpus_alias(corpus_id)

        def _status() -> QdrantCorpusStatus | None:
            client = self._client()
            try:
                physical = self._resolve_physical_sync(client, alias)
                if physical is None:
                    return None
                info = client.get_collection(physical)
                vectors = getattr(getattr(info.config, "params", None), "vectors", None)
                dense_dim = 0
                if isinstance(vectors, dict) and DENSE_VECTOR_NAME in vectors:
                    dense_dim = int(getattr(vectors[DENSE_VECTOR_NAME], "size", 0) or 0)
                dense_points = int(
                    client.count(
                        physical,
                        count_filter=qmodels.Filter(must=[qmodels.HasVectorCondition(has_vector=DENSE_VECTOR_NAME)]),
                        exact=True,
                    ).count
                )
                total_points = int(client.count(physical, exact=True).count)
                return QdrantCorpusStatus(
                    corpus_id=corpus_id,
                    alias=alias,
                    physical_collection=physical,
                    points=total_points,
                    dense_points=dense_points,
                    dense_dimensions=dense_dim,
                )
            finally:
                client.close()

        try:
            return await asyncio.to_thread(_status)
        except Exception as exc:
            if _is_not_found(exc):
                # Alias present but its physical generation was wiped.
                return QdrantCorpusStatus(
                    corpus_id=corpus_id,
                    alias=alias,
                    physical_collection=None,
                    points=0,
                    dense_points=0,
                    dense_dimensions=0,
                )
            self._raise_boundary(exc, operation="Qdrant corpus status", corpus_id=corpus_id, alias=alias)
            raise

    async def vector_search(self, corpus_id: str, query_embedding: list[float], top_k: int) -> list[ChunkMatch]:
        if top_k <= 0 or not query_embedding:
            return []
        alias = corpus_alias(corpus_id)

        def _search() -> list[Any]:
            client = self._client()
            try:
                response = client.query_points(
                    alias,
                    query=[float(x) for x in query_embedding],
                    using=DENSE_VECTOR_NAME,
                    limit=int(top_k),
                    with_payload=True,
                )
                return list(response.points)
            finally:
                client.close()

        try:
            points = await asyncio.to_thread(_search)
        except Exception as exc:
            self._raise_boundary(exc, operation="Qdrant vector search", corpus_id=corpus_id, alias=alias)
            raise
        return [_point_to_match(p, source="vector", corpus_id=corpus_id) for p in points]

    async def sparse_search(self, corpus_id: str, query: str, top_k: int) -> list[ChunkMatch]:
        if top_k <= 0 or not str(query or "").strip():
            return []
        from qdrant_client import models as qmodels

        alias = corpus_alias(corpus_id)
        embedder = await _sparse_text_embedder(self.sparse_contract)
        sparse = await asyncio.to_thread(lambda: embedder.run(text=str(query))["sparse_embedding"])
        if not sparse.indices:
            return []

        def _search() -> list[Any]:
            client = self._client()
            try:
                response = client.query_points(
                    alias,
                    query=qmodels.SparseVector(indices=list(sparse.indices), values=list(sparse.values)),
                    using=SPARSE_VECTOR_NAME,
                    limit=int(top_k),
                    with_payload=True,
                )
                return list(response.points)
            finally:
                client.close()

        try:
            points = await asyncio.to_thread(_search)
        except Exception as exc:
            self._raise_boundary(exc, operation="Qdrant sparse search", corpus_id=corpus_id, alias=alias)
            raise
        return [_point_to_match(p, source="sparse", corpus_id=corpus_id) for p in points]

    async def get_embeddings(self, corpus_id: str, chunk_ids: list[str]) -> dict[str, list[float]]:
        ids = list(dict.fromkeys(str(cid) for cid in chunk_ids if str(cid).strip()))
        if not ids:
            return {}
        alias = corpus_alias(corpus_id)

        def _retrieve() -> list[Any]:
            client = self._client()
            try:
                return list(
                    client.retrieve(
                        alias,
                        ids=[point_id_for_chunk(cid) for cid in ids],
                        with_payload=["id"],
                        with_vectors=[DENSE_VECTOR_NAME],
                    )
                )
            finally:
                client.close()

        try:
            records = await asyncio.to_thread(_retrieve)
        except Exception as exc:
            self._raise_boundary(exc, operation="Qdrant embedding fetch", corpus_id=corpus_id, alias=alias)
            raise
        out: dict[str, list[float]] = {}
        for record in records:
            payload = dict(record.payload or {})
            vectors = record.vector if isinstance(record.vector, dict) else {}
            dense = vectors.get(DENSE_VECTOR_NAME)
            chunk_id = str(payload.get("id") or "")
            if chunk_id and dense:
                out[chunk_id] = [float(x) for x in dense]
        return out

    async def ping(self) -> bool:
        """Functional readiness probe against the Qdrant service."""

        def _ping() -> bool:
            client = self._client()
            try:
                client.get_collections()
                return True
            finally:
                client.close()

        try:
            return await asyncio.to_thread(_ping)
        except Exception:
            return False
