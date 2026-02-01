"""API tests for dashboard index summary + storage endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dashboard_index_status_and_stats_return_storage_breakdown(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.api.index as index_api
    from server.models.index import IndexStats
    from server.models.tribrid_config_model import TriBridConfig

    class _FakePostgres:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def list_corpora(self) -> list[dict[str, object]]:
            return [{"repo_id": "test-corpus", "name": "Test Corpus", "path": "/tmp"}]

        async def get_corpus(self, repo_id: str) -> dict[str, object]:
            return {
                "repo_id": repo_id,
                "name": "Test Corpus",
                "path": "/tmp",
                "meta": {"branch": "main", "keywords": ["k1", "k2"]},
            }

        async def get_index_stats(self, repo_id: str) -> IndexStats:
            return IndexStats(
                repo_id=repo_id,
                total_files=1,
                total_chunks=3,
                total_tokens=2000,
                embedding_model="text-embedding-3-large",
                embedding_dimensions=3072,
                last_indexed=datetime.now(UTC),
                file_breakdown={".py": 1},
            )

        async def get_dashboard_storage_breakdown(self, repo_id: str) -> dict[str, int]:
            assert repo_id == "test-corpus"
            return {
                "chunks_bytes": 10,
                "embeddings_bytes": 20,
                "pgvector_index_bytes": 40,
                "bm25_index_bytes": 30,
                "chunk_summaries_bytes": 50,
            }

    class _FakeNeo4j:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def get_store_size_bytes(self) -> int:
            return 60

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        # Use defaults, but ensure embedding provider/model match the pricing mock below.
        return TriBridConfig()

    # Pricing fixture: $0.10 per 1k tokens for embedding model
    monkeypatch.setattr(
        index_api,
        "_load_models_json",
        lambda: [
            {
                "provider": "openai",
                "model": "text-embedding-3-large",
                "components": ["EMB"],
                "unit": "1k_tokens",
                "embed_per_1k": 0.1,
            }
        ],
        raising=True,
    )

    monkeypatch.setattr(index_api, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(index_api, "Neo4jClient", _FakeNeo4j, raising=True)
    monkeypatch.setattr(index_api, "load_scoped_config", _fake_load_scoped_config, raising=True)

    r_status = await client.get("/api/index/status", params={"corpus_id": "test-corpus"})
    assert r_status.status_code == 200
    payload = r_status.json()

    assert payload["running"] is False
    assert payload["metadata"]["corpus_id"] == "test-corpus"
    assert payload["metadata"]["current_repo"] == "Test Corpus"
    assert payload["metadata"]["current_branch"] == "main"
    assert payload["metadata"]["keywords_count"] == 2

    sb = payload["metadata"]["storage_breakdown"]
    assert sb["chunks_bytes"] == 10
    assert sb["embeddings_bytes"] == 20
    assert sb["pgvector_index_bytes"] == 40
    assert sb["bm25_index_bytes"] == 30
    assert sb["chunk_summaries_bytes"] == 50
    assert sb["neo4j_store_bytes"] == 60
    assert sb["postgres_total_bytes"] == 150
    assert sb["total_storage_bytes"] == 210
    assert payload["metadata"]["total_storage"] == 210

    costs = payload["metadata"]["costs"]
    assert costs["total_tokens"] == 2000
    assert costs["embedding_cost"] == pytest.approx(0.2)  # 2000 tokens @ $0.10 / 1k

    r_stats = await client.get("/api/index/stats", params={"corpus_id": "test-corpus"})
    assert r_stats.status_code == 200
    payload2 = r_stats.json()
    assert payload2["corpus_id"] == "test-corpus"
    assert payload2["keywords_count"] == 2
    assert payload2["total_storage"] == 210
    assert payload2["storage_breakdown"]["total_storage_bytes"] == 210

