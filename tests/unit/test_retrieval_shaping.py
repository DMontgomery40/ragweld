"""Unit tests for retrieval shaping helpers (no mocks)."""

import pytest

from server.models.retrieval import ChunkMatch
from server.retrieval import fusion as fusion_mod


def _mk(chunk_id: str, *, file_path: str, score: float, corpus_id: str = "c") -> ChunkMatch:
    return ChunkMatch(
        chunk_id=chunk_id,
        content=f"content {chunk_id}",
        file_path=file_path,
        start_line=1,
        end_line=1,
        language=None,
        score=float(score),
        source="vector",
        metadata={"corpus_id": corpus_id},
    )


def test_dedup_by_file_path() -> None:
    r1 = _mk("a1", file_path="a.txt", score=1.0)
    r2 = _mk("a2", file_path="a.txt", score=0.9)
    out = fusion_mod._dedup_results([r1, r2], by="file_path")
    assert [r.chunk_id for r in out] == ["a1"]


def test_cap_chunks_per_file() -> None:
    r1 = _mk("a1", file_path="a.txt", score=1.0)
    r2 = _mk("a2", file_path="a.txt", score=0.9)
    r3 = _mk("b1", file_path="b.txt", score=0.8)
    out = fusion_mod._cap_chunks_per_file([r1, r2, r3], max_per_file=1)
    assert [r.chunk_id for r in out] == ["a1", "b1"]


@pytest.mark.asyncio
async def test_mmr_prefers_diversity_when_lambda_zero() -> None:
    r1 = ChunkMatch(
        chunk_id="c1",
        content="apple banana apple",
        file_path="a.txt",
        start_line=1,
        end_line=1,
        language=None,
        score=0.9,
        source="vector",
        metadata={"corpus_id": "c"},
    )
    r2 = ChunkMatch(
        chunk_id="c2",
        content="apple banana apple",
        file_path="a.txt",
        start_line=2,
        end_line=2,
        language=None,
        score=0.8,
        source="vector",
        metadata={"corpus_id": "c"},
    )
    r3 = ChunkMatch(
        chunk_id="c3",
        content="zebra yak",
        file_path="b.txt",
        start_line=1,
        end_line=1,
        language=None,
        score=0.7,
        source="vector",
        metadata={"corpus_id": "c"},
    )

    out = await fusion_mod._apply_mmr_if_enabled([r1, r2, r3], enabled=True, mmr_lambda=0.0, final_k=2)
    assert [r.chunk_id for r in out[:2]] == ["c1", "c3"]


@pytest.mark.asyncio
async def test_expand_neighbors_no_ordinals_is_noop() -> None:
    r1 = _mk("c1", file_path="a.txt", score=1.0)
    r2 = _mk("c2", file_path="a.txt", score=0.9)
    out = await fusion_mod._expand_neighbors([r1, r2], neighbor_window=1, seed_limit=2)
    assert [r.chunk_id for r in out] == ["c1", "c2"]

