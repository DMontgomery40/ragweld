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
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

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
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)
    results = fusion.rrf_fusion([[], [], []], k=60)
    assert len(results) == 0


def test_weighted_fusion() -> None:
    """Test weighted fusion."""
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    vector_results = [make_chunk("v1", 0.9, "vector")]
    sparse_results = [make_chunk("s1", 0.8, "sparse")]
    graph_results = [make_chunk("g1", 0.7, "graph")]

    results = fusion.weighted_fusion(
        [vector_results, sparse_results, graph_results],
        weights=[0.4, 0.3, 0.3],
    )

    assert len(results) == 3


def test_weighted_fusion_normalization() -> None:
    """Test that weighted fusion normalizes scores."""
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

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

    fusion = TriBridFusion(vector=None, sparse=None, graph=None)
    out = await fusion.search(
        corpus_ids=[],
        query="foo",
        config=FusionConfig(),
        include_vector=True,
        include_sparse=True,
        include_graph=False,
        top_k=5,
    )
    assert out == []


@pytest.mark.asyncio
async def test_search_multiple_corpora_dedupes_by_corpus_and_chunk_id(monkeypatch) -> None:
    """Same chunk_id in different corpora must not collide in fusion."""
    import server.retrieval.fusion as fusion_mod
    from server.models.tribrid_config_model import FusionConfig, TriBridConfig

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def vector_search(self, repo_id: str, _embedding: list[float], top_k: int):
            _ = top_k
            return [
                ChunkMatch(
                    chunk_id="c1",
                    content=f"content-{repo_id}",
                    file_path=f"{repo_id}.txt",
                    start_line=1,
                    end_line=1,
                    language=None,
                    score=0.9,
                    source="vector",
                    metadata={},
                )
            ]

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        _ = repo_id
        cfg = TriBridConfig()
        cfg.vector_search.enabled = 1
        cfg.sparse_search.enabled = 0
        cfg.graph_search.enabled = 0
        cfg.vector_search.top_k = 5
        cfg.retrieval.final_k = 10
        return cfg

    monkeypatch.setattr(fusion_mod, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(fusion_mod, "load_scoped_config", _fake_load_scoped_config, raising=True)

    fusion = TriBridFusion(vector=None, sparse=None, graph=None)
    out = await fusion.search(
        corpus_ids=["a", "b"],
        query="foo",
        config=FusionConfig(method="rrf", rrf_k=60),
        include_vector=True,
        include_sparse=False,
        include_graph=False,
        top_k=5,
    )

    assert len(out) == 2
    assert {c.content for c in out} == {"content-a", "content-b"}
    assert {str((c.metadata or {}).get("corpus_id")) for c in out} == {"a", "b"}


@pytest.mark.asyncio
async def test_search_graph_leg_records_error_in_debug(monkeypatch) -> None:
    """Graph leg failures should be visible in fusion.last_debug (no silent swallow)."""
    import server.retrieval.fusion as fusion_mod
    from server.models.tribrid_config_model import FusionConfig, TriBridConfig

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

    class _FailingNeo4j:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            raise RuntimeError("neo4j down")

        async def disconnect(self) -> None:
            return None

        async def graph_search(self, *_args, **_kwargs):
            return []

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        cfg = TriBridConfig()
        # Disable Postgres-backed legs; enable graph leg to exercise error path.
        cfg.vector_search.enabled = 0
        cfg.sparse_search.enabled = 0
        cfg.graph_search.enabled = 1
        cfg.retrieval.final_k = 5
        return cfg

    monkeypatch.setattr(fusion_mod, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(fusion_mod, "Neo4jClient", _FailingNeo4j, raising=True)
    monkeypatch.setattr(fusion_mod, "load_scoped_config", _fake_load_scoped_config, raising=True)

    fusion = TriBridFusion(vector=None, sparse=None, graph=None)
    out = await fusion.search(
        corpus_ids=["test-corpus"],
        query="foo",
        config=FusionConfig(),
        include_vector=False,
        include_sparse=False,
        include_graph=True,
        top_k=5,
    )
    assert out == []
    assert fusion.last_debug.get("fusion_graph_attempted") is True
    assert "neo4j down" in str(fusion.last_debug.get("fusion_graph_error"))


@pytest.mark.asyncio
async def test_search_graph_chunk_mode_hydrates_by_chunk_id(monkeypatch) -> None:
    """Chunk-mode graph leg should return real chunk_ids (no file-span guessing)."""
    import server.retrieval.fusion as fusion_mod
    from server.models.index import Chunk
    from server.models.tribrid_config_model import FusionConfig, TriBridConfig

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def get_chunks(self, repo_id: str, chunk_ids: list[str]) -> list[Chunk]:
            return [
                Chunk(
                    chunk_id=cid,
                    content=f"content {cid}",
                    file_path="src/test.py",
                    start_line=1,
                    end_line=2,
                    language="python",
                    token_count=3,
                    embedding=None,
                    summary=None,
                )
                for cid in chunk_ids
            ]

    class _FakeNeo4j:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def chunk_vector_search(
            self,
            repo_id: str,
            _embedding: list[float],
            *,
            index_name: str,
            top_k: int,
            neighbor_window: int = 0,
            overfetch_multiplier: int = 1,
        ) -> list[tuple[str, float]]:
            assert repo_id == "test-corpus"
            assert index_name == "tribrid_chunk_embeddings"
            assert top_k == 5
            _ = (neighbor_window, overfetch_multiplier)
            return [("c1", 0.9), ("c2", 0.8)]

        async def expand_chunks_via_entities(
            self,
            repo_id: str,
            seeds: list[tuple[str, float]],
            *,
            max_hops: int,
            top_k: int,
        ) -> list[tuple[str, float]]:
            _ = (repo_id, seeds, max_hops, top_k)
            return []

    class _FakeEmbedder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def embed(self, _text: str) -> list[float]:
            return [0.0, 0.1, 0.2]

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        _ = repo_id
        cfg = TriBridConfig()
        cfg.vector_search.enabled = 0
        cfg.sparse_search.enabled = 0
        cfg.graph_search.enabled = 1
        cfg.graph_search.mode = "chunk"
        cfg.graph_search.top_k = 5
        cfg.graph_indexing.chunk_vector_index_name = "tribrid_chunk_embeddings"
        cfg.graph_storage.neo4j_database_mode = "shared"
        cfg.retrieval.final_k = 10
        return cfg

    monkeypatch.setattr(fusion_mod, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(fusion_mod, "Neo4jClient", _FakeNeo4j, raising=True)
    monkeypatch.setattr(fusion_mod, "Embedder", _FakeEmbedder, raising=True)
    monkeypatch.setattr(fusion_mod, "load_scoped_config", _fake_load_scoped_config, raising=True)

    fusion = TriBridFusion(vector=None, sparse=None, graph=None)
    out = await fusion.search(
        corpus_ids=["test-corpus"],
        query="foo",
        config=FusionConfig(),
        include_vector=False,
        include_sparse=False,
        include_graph=True,
        top_k=5,
    )
    assert [c.chunk_id for c in out] == ["c1", "c2"]
    assert all(c.source == "graph" for c in out)
    assert out[0].content.startswith("content ")
    assert fusion.last_debug.get("fusion_graph_mode") == "chunk"
    assert fusion.last_debug.get("fusion_graph_hydrated_chunks") == 2


@pytest.mark.asyncio
async def test_search_graph_chunk_mode_entity_expansion_adds_chunks(monkeypatch) -> None:
    """Chunk-mode entity expansion should add additional chunk_ids."""
    import server.retrieval.fusion as fusion_mod
    from server.models.index import Chunk
    from server.models.tribrid_config_model import FusionConfig, TriBridConfig

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def get_chunks(self, repo_id: str, chunk_ids: list[str]) -> list[Chunk]:
            return [
                Chunk(
                    chunk_id=cid,
                    content=f"content {cid}",
                    file_path="src/test.py",
                    start_line=1,
                    end_line=2,
                    language="python",
                    token_count=3,
                    embedding=None,
                    summary=None,
                )
                for cid in chunk_ids
            ]

    class _FakeNeo4j:
        def __init__(self, *_args, **_kwargs) -> None:
            self.expand_called = False

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def chunk_vector_search(self, *_args, **_kwargs) -> list[tuple[str, float]]:
            return [("c1", 0.9), ("c2", 0.8)]

        async def expand_chunks_via_entities(
            self,
            repo_id: str,
            seeds: list[tuple[str, float]],
            *,
            max_hops: int,
            top_k: int,
        ) -> list[tuple[str, float]]:
            assert repo_id == "test-corpus"
            assert max_hops == 2
            assert top_k == 5
            assert seeds[:2] == [("c1", 0.9), ("c2", 0.8)]
            self.expand_called = True
            return [("c3", 0.95)]

    class _FakeEmbedder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def embed(self, _text: str) -> list[float]:
            return [0.0, 0.1, 0.2]

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        _ = repo_id
        cfg = TriBridConfig()
        cfg.vector_search.enabled = 0
        cfg.sparse_search.enabled = 0
        cfg.graph_search.enabled = 1
        cfg.graph_search.mode = "chunk"
        cfg.graph_search.max_hops = 2
        cfg.graph_search.top_k = 5
        cfg.graph_search.chunk_entity_expansion_enabled = True
        cfg.graph_search.chunk_entity_expansion_weight = 0.8
        cfg.graph_indexing.chunk_vector_index_name = "tribrid_chunk_embeddings"
        cfg.graph_storage.neo4j_database_mode = "shared"
        cfg.retrieval.final_k = 10
        return cfg

    fake_neo = _FakeNeo4j()

    # Patch constructors to return our instances.
    monkeypatch.setattr(fusion_mod, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(fusion_mod, "Neo4jClient", lambda *_a, **_k: fake_neo, raising=True)
    monkeypatch.setattr(fusion_mod, "Embedder", _FakeEmbedder, raising=True)
    monkeypatch.setattr(fusion_mod, "load_scoped_config", _fake_load_scoped_config, raising=True)

    fusion = TriBridFusion(vector=None, sparse=None, graph=None)
    out = await fusion.search(
        corpus_ids=["test-corpus"],
        query="foo",
        config=FusionConfig(),
        include_vector=False,
        include_sparse=False,
        include_graph=True,
        top_k=5,
    )
    assert fake_neo.expand_called is True
    assert [c.chunk_id for c in out] == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_search_graph_entity_mode_hydrates_by_chunk_id(monkeypatch) -> None:
    """Entity-mode graph leg should still hydrate by chunk_id via IN_CHUNK links."""
    import server.retrieval.fusion as fusion_mod
    from server.models.index import Chunk
    from server.models.tribrid_config_model import FusionConfig, TriBridConfig

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def get_chunks(self, repo_id: str, chunk_ids: list[str]) -> list[Chunk]:
            assert repo_id == "test-corpus"
            return [
                Chunk(
                    chunk_id=cid,
                    content=f"content {cid}",
                    file_path="src/test.py",
                    start_line=1,
                    end_line=2,
                    language="python",
                    token_count=3,
                    embedding=None,
                    summary=None,
                )
                for cid in chunk_ids
            ]

    class _FakeNeo4j:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def entity_chunk_search(self, repo_id: str, _query: str, max_hops: int, top_k: int) -> list[tuple[str, float]]:
            assert repo_id == "test-corpus"
            assert max_hops == 2
            assert top_k == 5
            return [("c1", 0.9)]

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        _ = repo_id
        cfg = TriBridConfig()
        cfg.vector_search.enabled = 0
        cfg.sparse_search.enabled = 0
        cfg.graph_search.enabled = 1
        cfg.graph_search.mode = "entity"
        cfg.graph_search.max_hops = 2
        cfg.graph_search.top_k = 5
        cfg.retrieval.final_k = 10
        return cfg

    monkeypatch.setattr(fusion_mod, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(fusion_mod, "Neo4jClient", _FakeNeo4j, raising=True)
    monkeypatch.setattr(fusion_mod, "load_scoped_config", _fake_load_scoped_config, raising=True)

    fusion = TriBridFusion(vector=None, sparse=None, graph=None)
    out = await fusion.search(
        corpus_ids=["test-corpus"],
        query="foo",
        config=FusionConfig(),
        include_vector=False,
        include_sparse=False,
        include_graph=True,
        top_k=5,
    )
    assert [c.chunk_id for c in out] == ["c1"]
    assert fusion.last_debug.get("fusion_graph_mode") == "entity"
