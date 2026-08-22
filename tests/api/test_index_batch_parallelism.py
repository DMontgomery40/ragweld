"""Index chunk-batch parallelism safety checks."""

from __future__ import annotations

from pathlib import Path

import pytest

import server.api.index as index_api
from server.indexing.chunker import Chunker
from server.indexing.loader import FileLoader
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.contracts import sparse_contract_from_config


def test_parallel_batches_disabled_when_neo4j_graph_upserts_enabled() -> None:
    assert (
        index_api._allow_parallel_chunk_batches(
            indexing_workers=8,
            batch_count=4,
            has_graph_upserts=True,
        )
        is False
    )


def test_parallel_batches_enabled_without_graph_upserts() -> None:
    assert (
        index_api._allow_parallel_chunk_batches(
            indexing_workers=8,
            batch_count=4,
            has_graph_upserts=False,
        )
        is True
    )


def test_parallel_batches_disabled_for_single_worker_or_single_batch() -> None:
    assert (
        index_api._allow_parallel_chunk_batches(
            indexing_workers=1,
            batch_count=4,
            has_graph_upserts=False,
        )
        is False
    )


def test_cross_file_chunk_batching_enabled_only_without_graph_or_semantic_work() -> None:
    assert (
        index_api._allow_cross_file_chunk_batching(
            has_graph_upserts=False,
            semantic_kg_enabled=False,
        )
        is True
    )
    assert (
        index_api._allow_cross_file_chunk_batching(
            has_graph_upserts=True,
            semantic_kg_enabled=False,
        )
        is False
    )
    assert (
        index_api._allow_cross_file_chunk_batching(
            has_graph_upserts=False,
            semantic_kg_enabled=True,
        )
        is False
    )


def test_parallel_batches_still_require_multiple_batches() -> None:
    assert (
        index_api._allow_parallel_chunk_batches(
            indexing_workers=8,
            batch_count=1,
            has_graph_upserts=False,
        )
        is False
    )


class _RecordingPostgres:
    def __init__(self) -> None:
        self.chunk_batch_sizes: list[int] = []
        self.embedding_meta: dict[str, object] | None = None
        self.semantic_cache_cleared: list[str] = []

    async def delete_chunks(self, _repo_id: str) -> int:
        return 0

    async def upsert_chunks(self, _repo_id: str, chunks) -> int:
        assert all(ch.embedding is not None for ch in chunks)
        self.chunk_batch_sizes.append(len(chunks))
        return len(chunks)

    async def update_corpus_embedding_meta(
        self,
        _repo_id: str,
        *,
        backend: str,
        provider: str,
        model: str,
        dimensions: int,
        sparse_contract: dict[str, object] | None = None,
    ) -> None:
        self.embedding_meta = {
            "backend": backend,
            "provider": provider,
            "model": model,
            "dimensions": dimensions,
            "sparse_contract": sparse_contract,
        }

    async def semantic_cache_clear_for_corpus(self, repo_id: str) -> None:
        self.semantic_cache_cleared.append(repo_id)


class _RecordingQdrant:
    def __init__(self, sparse_contract: dict[str, object]) -> None:
        self.sparse_contract = sparse_contract
        self.writes: list[tuple[str, str, int, int]] = []

    async def write_chunks(self, corpus_id: str, physical: str, chunks, *, embedding_dim: int) -> int:
        self.writes.append((corpus_id, physical, len(chunks), int(embedding_dim)))
        return len(chunks)


class _RecordingEmbedder:
    dim = 2

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_chunks(self, chunks, *, embed_texts=None):
        assert embed_texts is None
        self.calls.append([str(ch.file_path) for ch in chunks])
        return [ch.model_copy(update={"embedding": [0.1, 0.2]}) for ch in chunks]


@pytest.mark.asyncio
async def test_run_index_body_batches_small_files_across_files_when_graph_work_is_disabled(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    for idx in range(3):
        (root / f"doc-{idx}.txt").write_text(("small file content " * 16).strip(), encoding="utf-8")

    cfg = TriBridConfig()
    cfg.tokenization.estimate_only = True
    cfg.embedding.embedding_backend = "provider"
    cfg.embedding.embedding_type = "openai"
    cfg.embedding.embedding_model = "text-embedding-3-large"
    cfg.indexing.indexing_batch_size = 10
    cfg.indexing.indexing_workers = 4
    cfg.graph_indexing.enabled = False
    cfg.graph_indexing.build_lexical_graph = False
    cfg.graph_indexing.semantic_kg_enabled = False

    chunker = Chunker(cfg.chunking, cfg.tokenization)
    loader = FileLoader()
    postgres = _RecordingPostgres()
    embedder = _RecordingEmbedder()
    qdrant = _RecordingQdrant(sparse_contract_from_config(cfg))

    stats = await index_api._run_index_body(
        repo_id="tiny-corpus",
        repo_path=str(root),
        force_reindex=False,
        run_id="run-small-files",
        cfg=cfg,
        chunker=chunker,
        max_indexable_bytes=10_000_000,
        skip_dense=False,
        embedder=embedder,
        postgres=postgres,
        neo4j=None,
        loader=loader,
        event_queue=None,
        write_repo_id="tiny-corpus",
        qdrant=qdrant,  # type: ignore[arg-type]
        qdrant_generation="ragweld_chunks_tiny_corpus__test",
    )

    assert stats.total_files == 3
    assert stats.total_chunks >= 3
    assert len(embedder.calls) == 1
    assert set(embedder.calls[0]) == {"doc-0.txt", "doc-1.txt", "doc-2.txt"}
    assert postgres.chunk_batch_sizes == [stats.total_chunks]
    assert qdrant.writes == [("tiny-corpus", "ragweld_chunks_tiny_corpus__test", stats.total_chunks, 2)]
    assert postgres.embedding_meta == {
        "backend": "provider",
        "provider": "openai",
        "model": "text-embedding-3-large",
        "dimensions": 2,
        "sparse_contract": sparse_contract_from_config(cfg),
    }
    assert postgres.semantic_cache_cleared == ["tiny-corpus"]
