"""Tests for the fusion module."""

import pytest

from server.models.retrieval import ChunkMatch
from server.retrieval.fusion import TriBridFusion


def make_chunk(chunk_id: str, score: float, source: str) -> ChunkMatch:
    """Create a test chunk match."""
    return ChunkMatch(
        chunk_id=chunk_id,
        content=f"Content for {chunk_id}",
        file_path="test.py",
        start_line=1,
        end_line=10,
        language="python",
        score=score,
        source=source,
    )


def test_rrf_fusion_basic() -> None:
    """Test basic RRF fusion."""
    fusion = TriBridFusion()

    vector_results = [make_chunk("v1", 0.9, "vector"), make_chunk("v2", 0.8, "vector")]
    sparse_results = [make_chunk("s1", 0.85, "sparse"), make_chunk("v1", 0.7, "sparse")]
    graph_results = [make_chunk("g1", 0.95, "graph")]

    results = fusion.rrf_fusion(
        [vector_results, sparse_results, graph_results],
        k=60,
    )

    # v1 appears in both vector and sparse, should rank higher
    chunk_ids = [r.chunk_id for r in results]
    assert "v1" in chunk_ids


def test_rrf_fusion_empty() -> None:
    """Test RRF fusion with empty results."""
    fusion = TriBridFusion()
    results = fusion.rrf_fusion([[], [], []], k=60)
    assert len(results) == 0


def test_weighted_fusion() -> None:
    """Test weighted fusion."""
    fusion = TriBridFusion()

    vector_results = [make_chunk("v1", 0.9, "vector")]
    sparse_results = [make_chunk("s1", 0.8, "sparse")]
    graph_results = [make_chunk("g1", 0.7, "graph")]

    results = fusion.weighted_fusion(
        [vector_results, sparse_results, graph_results],
        weights=[0.4, 0.3, 0.3],
    )

    assert len(results) == 3


def test_weighted_fusion_normalizes_weights_by_their_sum() -> None:
    """Weights that do not sum to 1.0 are normalized at fusion time, not at config-save time (M7)."""
    fusion = TriBridFusion()
    vector_results = [make_chunk("v1", 1.0, "vector")]
    sparse_results = [make_chunk("s1", 1.0, "sparse")]

    unit = fusion.weighted_fusion([vector_results, sparse_results, []], weights=[0.4, 0.6, 0.0])
    scaled = fusion.weighted_fusion([vector_results, sparse_results, []], weights=[0.8, 1.2, 0.0])
    assert [(c.chunk_id, round(c.score, 6)) for c in unit] == [(c.chunk_id, round(c.score, 6)) for c in scaled]
    assert unit[0].chunk_id == "s1" and round(unit[0].score, 6) == 0.6
    assert unit[1].chunk_id == "v1" and round(unit[1].score, 6) == 0.4

    with pytest.raises(ValueError):
        fusion.weighted_fusion([vector_results, sparse_results, []], weights=[0.0, 0.0, 0.0])


def test_weighted_fusion_normalization() -> None:
    """Test that weighted fusion normalizes scores."""
    fusion = TriBridFusion()

    # Same chunk with different scores from different sources
    vector_results = [make_chunk("c1", 0.9, "vector")]
    sparse_results = [make_chunk("c1", 0.6, "sparse")]

    results = fusion.weighted_fusion(
        [vector_results, sparse_results, []],
        weights=[0.5, 0.5, 0.0],
    )

    assert len(results) == 1
    # Combined score should be between the two
    assert 0.6 < results[0].score < 0.9


@pytest.mark.asyncio
async def test_search_empty_corpus_ids_returns_empty() -> None:
    """Multi-corpus search should return empty list for empty corpus_ids."""
    from server.models.tribrid_config_model import FusionConfig

    fusion = TriBridFusion()
    out = await fusion.search(
        corpus_ids=[],
        query="How often is the salinity sensor calibrated?",
        config=FusionConfig(),
        include_vector=True,
        include_sparse=True,
        include_graph=False,
        top_k=5,
    )
    assert out == []
