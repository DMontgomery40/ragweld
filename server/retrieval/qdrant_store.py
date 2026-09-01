"""Canonical Qdrant chunk-vector store (dense + IDF sparse) for ragweld corpora.

Ownership boundary:

- Postgres keeps chunk rows as control/state (hydration, summaries, neighbor
  expansion, graph hydration) and the recorded dense/sparse contracts.
- Qdrant keeps the dense and sparse vectors for every corpus in physical
  generation collections (`ragweld_chunks_<corpus>__<hex>`). Which generation
  is live is decided by the corpus's generation manifest in Postgres
  (`server/indexing/generations.py`), written by the same transaction that
  promotes the chunk rows; a full index builds a fresh staged generation and
  the commit is that single manifest write. Superseded generations are retired
  afterwards. There are no Qdrant aliases.
- The graph leg seeds traversal from this same Qdrant generation and joins to
  Neo4j through generation-qualified ``graph_join_id`` payloads.

Writes go through the Haystack Qdrant document store so the collection schema
(named `text-dense` / `text-sparse` vectors, IDF modifier) is the Haystack
contract. Reads use the Qdrant client directly against the physical
collection named by the manifest so a missing or wiped generation reads as
missing instead of being silently auto-created.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from server.db.postgres import PostgresClient
from server.dependency_errors import DependencyUnavailableError
from server.models.index import Chunk, ChunkProvenance
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
_COLLECTION_PREFIX = "ragweld_chunks_"

# Chunk metadata keys that are copied into the Qdrant payload as first-class
# provenance so every hit can become a citation without a Postgres round trip.
_PAYLOAD_META_KEYS = (
    "chunk_ordinal",
    "parent_doc_id",
    "char_start",
    "char_end",
    "kind",
    # Figure chunks (``server/indexing/provenance.py``). Without these the dense and sparse
    # legs read back a figure description as ordinary page text: only the graph leg hydrates
    # full metadata from Postgres, so the citation UI would have nothing to mark. Present on
    # figure chunks only, and only once a corpus is re-indexed with figures enabled.
    "chunk_kind",
    "figure",
)

_SPARSE_DOC_EMBEDDERS: dict[str, Any] = {}
_SPARSE_TEXT_EMBEDDERS: dict[str, Any] = {}
_SPARSE_EMBEDDER_LOCK = asyncio.Lock()
# Serializes first-write generation creation per corpus (incremental upserts).
_CORPUS_LOCKS: dict[str, asyncio.Lock] = {}


class QdrantCollectionMissingError(RuntimeError):
    """The corpus has no promoted generation, or its physical collection does not exist in Qdrant."""

    def __init__(self, corpus_id: str, collection: str | None) -> None:
        self.corpus_id = corpus_id
        self.collection = collection
        if collection:
            super().__init__(
                f"Qdrant collection '{collection}' for corpus '{corpus_id}' does not exist"
            )
        else:
            super().__init__(f"Corpus '{corpus_id}' has no promoted Qdrant generation")


class QdrantGenerationExistsError(RuntimeError):
    """A generation create met an existing collection: it is never recreated over."""

    def __init__(self, corpus_id: str, collection: str) -> None:
        self.corpus_id = corpus_id
        self.collection = collection
        super().__init__(
            f"Qdrant collection '{collection}' for corpus '{corpus_id}' already exists; "
            "a generation is never recreated over an existing collection"
        )


@dataclass(frozen=True)
class QdrantCorpusStatus:
    corpus_id: str
    prefix: str
    physical_collection: str | None
    points: int
    dense_points: int
    dense_dimensions: int


def corpus_collection_prefix(corpus_id: str) -> str:
    """Stable, injective collection-name prefix for a corpus.

    The readable part is sanitized (Qdrant names are restricted), so distinct
    corpus ids such as `my-repo` / `my_repo` / `My.Repo` would collide on it
    alone; the sha1 suffix of the exact corpus id keeps the prefix injective.
    Generations are `<prefix>__<hex>`, and the suffix guarantees no other
    corpus prefix can be a prefix of this corpus's generations.
    """
    raw = str(corpus_id or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_").lower()[:48] or "unknown"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{_COLLECTION_PREFIX}{safe}_{digest}"


def _corpus_lock(corpus_id: str) -> asyncio.Lock:
    lock = _CORPUS_LOCKS.get(corpus_id)
    if lock is None:
        lock = asyncio.Lock()
        _CORPUS_LOCKS[corpus_id] = lock
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
    if chunk.provenance is not None:
        meta["provenance"] = chunk.provenance.model_dump(mode="json")
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
    raw_provenance = meta.get("provenance")
    # Generations written before provenance capture carry no key (and may still carry the
    # retired ``extraction`` metadata key); they read back as provenance=None, never synthesized.
    provenance = (
        ChunkProvenance.model_validate(raw_provenance) if isinstance(raw_provenance, dict) else None
    )
    metadata: dict[str, Any] = {
        k: v
        for k, v in meta.items()
        if k not in {"file_path", "start_line", "end_line", "language", "provenance", "extraction"}
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
        provenance=provenance,
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

    def _raise_boundary(
        self, exc: BaseException, *, operation: str, corpus_id: str, collection: str | None
    ) -> None:
        if is_qdrant_unavailable(exc):
            raise DependencyUnavailableError("qdrant", operation) from exc
        if _is_not_found(exc):
            raise QdrantCollectionMissingError(corpus_id, collection) from exc

    async def legacy_alias_target(self, corpus_id: str) -> str | None:
        """The collection a pre-manifest corpus alias points at (startup upgrade only)."""
        prefix = corpus_collection_prefix(corpus_id)

        def _resolve() -> str | None:
            client = self._client()
            try:
                for item in client.get_aliases().aliases:
                    if str(item.alias_name) == prefix:
                        return str(item.collection_name)
                return None
            finally:
                client.close()

        try:
            return await asyncio.to_thread(_resolve)
        except Exception as exc:
            self._raise_boundary(
                exc, operation="Qdrant legacy alias lookup", corpus_id=corpus_id, collection=prefix
            )
            raise

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

    def generation_name(self, corpus_id: str) -> str:
        """A fresh physical collection name for a corpus (chosen before creation so it can be recorded).

        The suffix is a full 128-bit uuid: a generation name can never coincide
        with a live or retained collection, so creating it can never destroy one.
        """
        return f"{corpus_collection_prefix(corpus_id)}__{uuid.uuid4().hex}"

    async def create_generation(
        self, corpus_id: str, *, embedding_dim: int, physical: str | None = None
    ) -> str:
        """Create a fresh physical generation for a corpus (not live until the manifest names it).

        Never recreates: a name that already exists belongs to someone (a live or
        retained generation, or a run whose create response was lost) and is
        refused, so a generation create can never wipe readable data.
        """
        physical = physical or self.generation_name(corpus_id)

        def _create() -> None:
            client = self._client()
            try:
                if client.collection_exists(physical):
                    raise QdrantGenerationExistsError(corpus_id, physical)
            finally:
                client.close()
            store = self._document_store(physical, embedding_dim=embedding_dim, recreate=False)
            try:
                store.count_documents()
            finally:
                self._close_store(store)

        try:
            await asyncio.to_thread(_create)
        except Exception as exc:
            self._raise_boundary(
                exc, operation="Qdrant generation create", corpus_id=corpus_id, collection=physical
            )
            raise
        return physical

    async def write_chunks(
        self,
        corpus_id: str,
        physical: str,
        chunks: list[Chunk],
        *,
        embedding_dim: int,
        graph_repo_id: str | None = None,
    ) -> int:
        """Write vectors and the optional generation-qualified graph join payload."""
        if not chunks:
            return 0
        from haystack.document_stores.types import DuplicatePolicy

        documents = [_chunk_to_document(corpus_id, chunk) for chunk in chunks]
        sparse_embedder = await _sparse_doc_embedder(self.sparse_contract)
        documents = await asyncio.to_thread(
            lambda: list(sparse_embedder.run(documents=documents)["documents"])
        )

        def _write() -> int:
            store = self._document_store(physical, embedding_dim=embedding_dim, recreate=False)
            try:
                written = int(store.write_documents(documents, policy=DuplicatePolicy.OVERWRITE))
            finally:
                self._close_store(store)
            if graph_repo_id:
                from qdrant_client import models as qmodels

                client = self._client()
                try:
                    operations = [
                        qmodels.SetPayloadOperation(
                            set_payload=qmodels.SetPayload(
                                payload={
                                    "graph_join_id": f"{graph_repo_id}:{chunk.chunk_id}"
                                },
                                points=[point_id_for_chunk(chunk.chunk_id)],
                            )
                        )
                        for chunk in chunks
                    ]
                    client.batch_update_points(
                        collection_name=physical,
                        update_operations=operations,
                        wait=True,
                    )
                finally:
                    client.close()
            return written

        try:
            return await asyncio.to_thread(_write)
        except Exception as exc:
            self._raise_boundary(
                exc, operation="Qdrant chunk write", corpus_id=corpus_id, collection=physical
            )
            raise

    async def count_graph_join_payloads(self, physical: str, graph_repo_id: str) -> int:
        """Count exact payloads belonging to one staged graph in a physical generation."""
        prefix = f"{graph_repo_id}:"

        def _count() -> int:
            client = self._client()
            count = 0
            offset: Any = None
            try:
                while True:
                    points, offset = client.scroll(
                        collection_name=physical,
                        limit=256,
                        offset=offset,
                        with_payload=["graph_join_id"],
                        with_vectors=False,
                    )
                    count += sum(
                        1
                        for point in points
                        if str((point.payload or {}).get("graph_join_id") or "").startswith(prefix)
                    )
                    if offset is None:
                        return count
            finally:
                client.close()

        try:
            return await asyncio.to_thread(_count)
        except Exception as exc:
            if is_qdrant_unavailable(exc):
                raise DependencyUnavailableError(
                    "qdrant", "Qdrant graph join payload count"
                ) from exc
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

    async def drop_legacy_alias(self, corpus_id: str) -> bool:
        """Remove a pre-manifest corpus alias (startup upgrade only); returns whether one existed."""
        from qdrant_client import models as qmodels

        prefix = corpus_collection_prefix(corpus_id)

        def _drop() -> bool:
            client = self._client()
            try:
                for item in client.get_aliases().aliases:
                    if str(item.alias_name) == prefix:
                        client.update_collection_aliases(
                            change_aliases_operations=[
                                qmodels.DeleteAliasOperation(
                                    delete_alias=qmodels.DeleteAlias(alias_name=prefix)
                                )
                            ]
                        )
                        return True
                return False
            finally:
                client.close()

        try:
            return await asyncio.to_thread(_drop)
        except Exception as exc:
            self._raise_boundary(
                exc, operation="Qdrant legacy alias drop", corpus_id=corpus_id, collection=prefix
            )
            raise

    async def drop_generation(self, physical: str) -> bool:
        """Drop one physical collection; True when it existed (idempotent otherwise)."""

        def _drop() -> bool:
            client = self._client()
            try:
                if client.collection_exists(physical):
                    client.delete_collection(physical)
                    return True
                return False
            finally:
                client.close()

        try:
            return await asyncio.to_thread(_drop)
        except Exception as exc:
            if is_qdrant_unavailable(exc):
                raise DependencyUnavailableError("qdrant", "Qdrant generation drop") from exc
            raise

    async def delete_corpus(self, corpus_id: str) -> int:
        """Remove every physical generation (and any legacy alias) for a corpus; returns collections removed."""
        from qdrant_client import models as qmodels

        prefix = corpus_collection_prefix(corpus_id)

        def _delete() -> int:
            client = self._client()
            removed = 0
            try:
                for item in client.get_aliases().aliases:
                    if str(item.alias_name) == prefix:
                        client.update_collection_aliases(
                            change_aliases_operations=[
                                qmodels.DeleteAliasOperation(
                                    delete_alias=qmodels.DeleteAlias(alias_name=prefix)
                                )
                            ]
                        )
                for collection in list(client.get_collections().collections):
                    name = str(collection.name)
                    if name == prefix or name.startswith(f"{prefix}__"):
                        client.delete_collection(name)
                        removed += 1
            finally:
                client.close()
            return removed

        try:
            return await asyncio.to_thread(_delete)
        except Exception as exc:
            self._raise_boundary(
                exc, operation="Qdrant corpus delete", corpus_id=corpus_id, collection=prefix
            )
            raise

    # ------------------------------------------------------------------
    # Incremental writes (recall and other append-only corpora)
    # ------------------------------------------------------------------

    async def upsert_chunks(
        self,
        corpus_id: str,
        chunks: list[Chunk],
        *,
        embedding_dim: int,
        pg: PostgresClient,
    ) -> int:
        """Incremental write: rows and vectors as one unit of work under the corpus lock.

        Delegates to ``PostgresClient.upsert_chunks_with_vectors``: the Postgres
        transaction holds the per-corpus advisory lock, resolves (or creates)
        the live generation from the row-locked manifest, writes the vectors
        through ``write_chunks`` while the lock is held, then commits the rows.
        """
        if not chunks:
            return 0
        return await pg.upsert_chunks_with_vectors(
            corpus_id, chunks, embedding_dim=embedding_dim, qdrant=self
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def status(self, corpus_id: str, *, physical: str | None) -> QdrantCorpusStatus | None:
        """Live collection status for the generation named by the manifest; None when there is none."""
        from qdrant_client import models as qmodels

        prefix = corpus_collection_prefix(corpus_id)
        if not physical:
            return None

        def _status() -> QdrantCorpusStatus | None:
            client = self._client()
            try:
                info = client.get_collection(physical)
                vectors = getattr(getattr(info.config, "params", None), "vectors", None)
                dense_dim = 0
                if isinstance(vectors, dict) and DENSE_VECTOR_NAME in vectors:
                    dense_dim = int(getattr(vectors[DENSE_VECTOR_NAME], "size", 0) or 0)
                dense_points = int(
                    client.count(
                        physical,
                        count_filter=qmodels.Filter(
                            must=[qmodels.HasVectorCondition(has_vector=DENSE_VECTOR_NAME)]
                        ),
                        exact=True,
                    ).count
                )
                total_points = int(client.count(physical, exact=True).count)
                return QdrantCorpusStatus(
                    corpus_id=corpus_id,
                    prefix=prefix,
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
                # The manifest names a generation that was wiped from Qdrant.
                return QdrantCorpusStatus(
                    corpus_id=corpus_id,
                    prefix=prefix,
                    physical_collection=None,
                    points=0,
                    dense_points=0,
                    dense_dimensions=0,
                )
            self._raise_boundary(
                exc, operation="Qdrant corpus status", corpus_id=corpus_id, collection=physical
            )
            raise

    async def vector_search(
        self, corpus_id: str, query_embedding: list[float], top_k: int, *, physical: str | None
    ) -> list[ChunkMatch]:
        if top_k <= 0 or not query_embedding:
            return []
        if not physical:
            raise QdrantCollectionMissingError(corpus_id, None)

        def _search() -> list[Any]:
            client = self._client()
            try:
                response = client.query_points(
                    physical,
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
            self._raise_boundary(
                exc, operation="Qdrant vector search", corpus_id=corpus_id, collection=physical
            )
            raise
        return [_point_to_match(p, source="vector", corpus_id=corpus_id) for p in points]

    async def sparse_search(
        self, corpus_id: str, query: str, top_k: int, *, physical: str | None
    ) -> list[ChunkMatch]:
        if top_k <= 0 or not str(query or "").strip():
            return []
        from qdrant_client import models as qmodels

        if not physical:
            raise QdrantCollectionMissingError(corpus_id, None)
        embedder = await _sparse_text_embedder(self.sparse_contract)
        sparse = await asyncio.to_thread(lambda: embedder.run(text=str(query))["sparse_embedding"])
        if not sparse.indices:
            return []

        def _search() -> list[Any]:
            client = self._client()
            try:
                response = client.query_points(
                    physical,
                    query=qmodels.SparseVector(
                        indices=list(sparse.indices), values=list(sparse.values)
                    ),
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
            self._raise_boundary(
                exc, operation="Qdrant sparse search", corpus_id=corpus_id, collection=physical
            )
            raise
        return [_point_to_match(p, source="sparse", corpus_id=corpus_id) for p in points]

    async def get_embeddings(
        self, corpus_id: str, chunk_ids: list[str], *, physical: str | None
    ) -> dict[str, list[float]]:
        ids = list(dict.fromkeys(str(cid) for cid in chunk_ids if str(cid).strip()))
        if not ids or not physical:
            return {}

        def _retrieve() -> list[Any]:
            client = self._client()
            try:
                return list(
                    client.retrieve(
                        physical,
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
            self._raise_boundary(
                exc, operation="Qdrant embedding fetch", corpus_id=corpus_id, collection=physical
            )
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
