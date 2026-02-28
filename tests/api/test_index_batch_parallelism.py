"""Index chunk-batch parallelism safety checks."""

from __future__ import annotations

import server.api.index as index_api


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


def test_ast_graph_build_skips_when_no_graph_files() -> None:
    assert (
        index_api._should_run_ast_graph_build(
            has_graph_builder=True,
            graph_file_count=0,
        )
        is False
    )
    assert (
        index_api._should_run_ast_graph_build(
            has_graph_builder=False,
            graph_file_count=10,
        )
        is False
    )
    assert (
        index_api._should_run_ast_graph_build(
            has_graph_builder=True,
            graph_file_count=3,
        )
        is True
    )
    assert (
        index_api._allow_parallel_chunk_batches(
            indexing_workers=8,
            batch_count=1,
            has_graph_upserts=False,
        )
        is False
    )
