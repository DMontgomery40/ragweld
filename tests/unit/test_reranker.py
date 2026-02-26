"""Real tests for the reranker module (no mocks)."""

from __future__ import annotations

import os

import pytest

from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import RerankingConfig
from server.retrieval.rerank import Reranker


def make_chunk(chunk_id: str, *, score: float, content: str | None = None) -> ChunkMatch:
    return ChunkMatch(
        chunk_id=chunk_id,
        content=content or f"Content for {chunk_id}",
        file_path="test.py",
        start_line=1,
        end_line=10,
        language="python",
        score=float(score),
        source="vector",
        metadata={},
    )


@pytest.mark.asyncio
async def test_reranker_none_passthrough() -> None:
    config = RerankingConfig(reranker_mode="none")
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8), make_chunk("c3", score=0.7)]
    out = await reranker.rerank("test query", chunks)

    assert [c.chunk_id for c in out] == ["c1", "c2", "c3"]
    assert [c.score for c in out] == [0.9, 0.8, 0.7]


@pytest.mark.asyncio
async def test_reranker_learning_missing_trained_model_reports_skipped() -> None:
    config = RerankingConfig(reranker_mode="learning")
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    res = await reranker.try_rerank("auth login", chunks)

    assert res.ok is True
    assert res.applied is False
    assert res.skipped_reason == "missing_trained_model"
    assert res.error is None
    assert [c.chunk_id for c in res.chunks] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_reranker_cloud_missing_api_key_reports_skipped() -> None:
    os.environ.pop("COHERE_API_KEY", None)

    config = RerankingConfig(
        reranker_mode="cloud",
        reranker_cloud_provider="cohere",
        reranker_cloud_model="rerank-v3.5",
        reranker_cloud_top_n=10,
        reranker_timeout=5,
    )
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    res = await reranker.try_rerank("auth login", chunks)

    assert res.ok is True
    assert res.applied is False
    assert res.skipped_reason == "missing_api_key"
    assert res.error is None
    assert [c.chunk_id for c in res.chunks] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_reranker_empty_input() -> None:
    config = RerankingConfig(reranker_mode="none")
    reranker = Reranker(config)
    out = await reranker.rerank("test query", [])
    assert out == []

