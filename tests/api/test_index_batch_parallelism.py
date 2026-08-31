"""Index chunk-batch parallelism safety checks."""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from pathlib import Path

import pytest

import server.api.index as index_api
from server.indexing.chunker import Chunker
from server.indexing.loader import FileLoader
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.contracts import sparse_contract_from_config


@pytest.mark.asyncio
async def test_file_extraction_yields_the_api_event_loop(tmp_path: Path) -> None:
    extractor = index_api._extract_text_for_index
    fifo = tmp_path / "slow-reader.txt"
    os.mkfifo(fifo)

    def _delayed_writer() -> None:
        time.sleep(0.5)
        fifo.write_text("event loop stayed responsive", encoding="utf-8")

    writer = threading.Thread(target=_delayed_writer, daemon=True)
    writer.start()
    started = time.monotonic()
    extraction = asyncio.create_task(extractor(fifo))
    await asyncio.sleep(0.05)
    responsive_after = time.monotonic() - started
    content = await asyncio.wait_for(extraction, timeout=2.0)
    writer.join(timeout=2.0)

    assert responsive_after < 0.35
    assert content is not None and content.text == "event loop stayed responsive"
    assert not writer.is_alive()


@pytest.mark.asyncio
async def test_unsupported_suffix_fallback_file_read_yields_the_api_event_loop(
    tmp_path: Path,
) -> None:
    extractor = index_api._extract_text_for_index
    fifo = tmp_path / "slow-reader.unsupported"
    os.mkfifo(fifo)

    def _delayed_writer() -> None:
        time.sleep(0.5)
        fifo.write_text("fallback stayed responsive", encoding="utf-8")

    writer = threading.Thread(target=_delayed_writer, daemon=True)
    writer.start()
    started = time.monotonic()
    extraction = asyncio.create_task(extractor(fifo))
    await asyncio.sleep(0.05)
    responsive_after = time.monotonic() - started
    content = await asyncio.wait_for(extraction, timeout=2.0)
    writer.join(timeout=2.0)

    assert responsive_after < 0.35
    assert content is not None and content.text == "fallback stayed responsive"
    assert not writer.is_alive()


@pytest.mark.asyncio
async def test_unsupported_suffix_fallback_bypasses_the_docling_lock(tmp_path: Path) -> None:
    extractor = index_api._extract_text_for_index
    fifo = tmp_path / "slow-reader.lockless"
    os.mkfifo(fifo)

    def _delayed_writer() -> None:
        time.sleep(0.5)
        fifo.write_text("docling lock ignored", encoding="utf-8")

    writer = threading.Thread(target=_delayed_writer, daemon=True)
    writer.start()
    started = time.monotonic()
    async with index_api._DOCLING_EXTRACTION_LOCK:
        extraction = asyncio.create_task(extractor(fifo))
        await asyncio.sleep(0.05)
        responsive_after = time.monotonic() - started
        content = await asyncio.wait_for(extraction, timeout=2.0)
    writer.join(timeout=2.0)

    assert responsive_after < 0.35
    assert content is not None and content.text == "docling lock ignored"
    assert not writer.is_alive()


@pytest.mark.asyncio
async def test_docling_cancellation_keeps_lock_until_blocking_worker_finishes(
) -> None:
    first_started = threading.Event()
    first_release = threading.Event()
    second_entered = threading.Event()

    def _first_worker() -> str:
        first_started.set()
        assert first_release.wait(timeout=5.0)
        return "first worker released"

    def _second_worker() -> str:
        second_entered.set()
        return "second worker entered"

    second_task: asyncio.Task[str | None] | None = None
    first_task = asyncio.create_task(index_api._run_docling_extraction_locked(_first_worker))
    try:
        assert await asyncio.to_thread(first_started.wait, 5.0)

        first_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_task

        second_task = asyncio.create_task(index_api._run_docling_extraction_locked(_second_worker))
        await asyncio.sleep(0.2)
        assert not second_entered.is_set()

        first_release.set()
        content = await asyncio.wait_for(second_task, timeout=10.0)
    finally:
        first_release.set()
        if second_task is not None and not second_task.done():
            second_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await second_task

    assert content is not None
    assert content == "second worker entered"


@pytest.mark.asyncio
async def test_docling_task_creation_failure_releases_extraction_lock() -> None:
    loop = asyncio.get_running_loop()
    original_factory = loop.get_task_factory()
    lock = index_api._DOCLING_EXTRACTION_LOCK

    await lock.acquire()
    extraction = asyncio.create_task(
        index_api._run_docling_extraction_locked(lambda: "must not run")
    )
    await asyncio.sleep(0)

    def _fail_to_thread_task_creation(
        event_loop: asyncio.AbstractEventLoop,
        coroutine: object,
        **kwargs: object,
    ) -> asyncio.Task[object]:
        code = getattr(coroutine, "cr_code", None)
        if getattr(code, "co_name", None) == "to_thread":
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            raise MemoryError("forced task creation failure")
        if original_factory is not None:
            return original_factory(event_loop, coroutine, **kwargs)  # type: ignore[arg-type]
        return asyncio.Task(coroutine, loop=event_loop, **kwargs)  # type: ignore[arg-type]

    loop.set_task_factory(_fail_to_thread_task_creation)
    lock.release()
    try:
        with pytest.raises(MemoryError, match="forced task creation failure"):
            await extraction
    finally:
        loop.set_task_factory(original_factory)

    stranded = lock.locked()
    if stranded:
        lock.release()

    assert not stranded
    assert await index_api._run_docling_extraction_locked(lambda: "next worker entered") == (
        "next worker entered"
    )


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
            semantic_graph_active=False,
        )
        is True
    )
    assert (
        index_api._allow_cross_file_chunk_batching(
            has_graph_upserts=True,
            semantic_graph_active=False,
        )
        is False
    )
    assert (
        index_api._allow_cross_file_chunk_batching(
            has_graph_upserts=False,
            semantic_graph_active=True,
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
        self.documents: list[tuple[str, str]] = []

    async def delete_chunks(self, _repo_id: str) -> int:
        return 0

    async def upsert_document(self, repo_id: str, record) -> None:
        # One provenance record per extracted file, written under the staging id.
        self.documents.append((repo_id, record.file_path))

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

    chunker = Chunker(cfg.chunking, cfg.tokenization)
    loader = FileLoader()
    postgres = _RecordingPostgres()
    embedder = _RecordingEmbedder()
    qdrant = _RecordingQdrant(sparse_contract_from_config(cfg))

    stats, figure_totals = await index_api._run_index_body(
        repo_id="tiny-corpus",
        repo_path=str(root),
        force_reindex=False,
        run_id="run-small-files",
        cfg=cfg,
        graph_policy="off",
        graph_schema=None,
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
    # A text-only corpus with figures off still returns a totals record, all zeroes and unpriced:
    # the run summary reports "no figures", never a missing figure phase.
    assert figure_totals == index_api.FigureRunTotals()
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
