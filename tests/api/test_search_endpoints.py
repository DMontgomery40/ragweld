"""API tests for search endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_search(client: AsyncClient) -> None:
    """Test POST /api/search endpoint."""
    request = {
        "query": "How does authentication work?",
        "repo_id": "test-repo",
        "top_k": 10,
    }
    response = await client.post("/api/search", json=request)
    assert response.status_code in [200, 404]  # 404 if repo doesn't exist

    if response.status_code == 200:
        data = response.json()
        assert "query" in data
        assert "matches" in data
        assert "fusion_method" in data
        assert "latency_ms" in data


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_search_with_options(client: AsyncClient) -> None:
    """Test POST /api/search with search type options."""
    request = {
        "query": "Find login function",
        "repo_id": "test-repo",
        "top_k": 5,
        "include_vector": True,
        "include_sparse": True,
        "include_graph": False,
    }
    response = await client.post("/api/search", json=request)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_search_empty_query(client: AsyncClient) -> None:
    """Test POST /api/search with empty query."""
    request = {
        "query": "",
        "repo_id": "test-repo",
    }
    response = await client.post("/api/search", json=request)
    assert response.status_code in [400, 422]


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_answer(client: AsyncClient) -> None:
    """Test POST /api/answer endpoint."""
    request = {
        "query": "Explain the main function",
        "repo_id": "test-repo",
        "top_k": 5,
        "stream": False,
    }
    response = await client.post("/api/answer", json=request)
    assert response.status_code in [200, 404]

    if response.status_code == 200:
        data = response.json()
        assert "query" in data
        assert "answer" in data
        assert "sources" in data


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_answer_with_system_prompt(client: AsyncClient) -> None:
    """Test POST /api/answer with custom system prompt."""
    request = {
        "query": "What does this code do?",
        "repo_id": "test-repo",
        "system_prompt": "You are a senior code reviewer.",
        "stream": False,
    }
    response = await client.post("/api/answer", json=request)
    assert response.status_code in [200, 404]


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_answer_stream(client: AsyncClient) -> None:
    """Test POST /api/answer/stream endpoint."""
    request = {
        "query": "Explain the authentication flow",
        "repo_id": "test-repo",
        "stream": True,
    }
    response = await client.post("/api/answer/stream", json=request)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_search_accepts_corpus_id_without_postgres(client: AsyncClient, monkeypatch) -> None:
    """Search should accept corpus_id even when Postgres is mocked."""
    import server.api.search as search_api
    from server.models.retrieval import ChunkMatch
    from server.models.tribrid_config_model import TriBridConfig
    from server.retrieval.fusion import TriBridFusion

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def get_corpus(self, repo_id: str):
            return {"repo_id": repo_id}

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        return TriBridConfig()

    expected_corpus_id = "test-corpus"

    async def _fake_fusion_search(self, corpus_ids: list[str], query: str, *_args, **_kwargs):
        assert corpus_ids == [expected_corpus_id]
        assert query == "hello"
        return [
            ChunkMatch(
                chunk_id="c1",
                content="def hello():\n    return 'world'\n",
                file_path="src/hello.py",
                start_line=1,
                end_line=2,
                language="py",
                score=1.0,
                source="vector",
                metadata={},
            )
        ]

    monkeypatch.setattr(search_api, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(search_api, "load_scoped_config", _fake_load_scoped_config, raising=True)
    monkeypatch.setattr(TriBridFusion, "search", _fake_fusion_search, raising=True)

    r = await client.post(
        "/api/search",
        json={
            "query": "hello",
            "corpus_id": expected_corpus_id,
            "top_k": 5,
            "include_vector": True,
            "include_sparse": False,
            "include_graph": False,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "hello"
    assert isinstance(data.get("matches"), list)
    assert len(data["matches"]) == 1
    assert data["matches"][0]["file_path"] == "src/hello.py"
    assert data.get("debug", {}).get("vector_enabled") is True
    assert data.get("debug", {}).get("sparse_enabled") is False
    assert data.get("debug", {}).get("graph_enabled") is False


@pytest.mark.asyncio
async def test_search_accepts_repo_id_without_postgres(client: AsyncClient, monkeypatch) -> None:
    """Search should still accept legacy repo_id."""
    import server.api.search as search_api
    from server.models.retrieval import ChunkMatch
    from server.models.tribrid_config_model import TriBridConfig
    from server.retrieval.fusion import TriBridFusion

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def get_corpus(self, repo_id: str):
            return {"repo_id": repo_id}

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        return TriBridConfig()

    expected_repo_id = "legacy-repo"

    async def _fake_fusion_search(self, corpus_ids: list[str], query: str, *_args, **_kwargs):
        assert corpus_ids == [expected_repo_id]
        assert query == "legacy"
        return [
            ChunkMatch(
                chunk_id="c1",
                content="print('legacy')\n",
                file_path="src/legacy.py",
                start_line=1,
                end_line=1,
                language="py",
                score=0.5,
                source="sparse",
                metadata={},
            )
        ]

    monkeypatch.setattr(search_api, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(search_api, "load_scoped_config", _fake_load_scoped_config, raising=True)
    monkeypatch.setattr(TriBridFusion, "search", _fake_fusion_search, raising=True)

    r = await client.post(
        "/api/search",
        json={
            "query": "legacy",
            "repo_id": expected_repo_id,
            "top_k": 5,
            "include_vector": False,
            "include_sparse": True,
            "include_graph": False,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "legacy"
    assert isinstance(data.get("matches"), list)
    assert len(data["matches"]) == 1
    assert data["matches"][0]["file_path"] == "src/legacy.py"
    assert data.get("debug", {}).get("vector_enabled") is False
    assert data.get("debug", {}).get("sparse_enabled") is True
    assert data.get("debug", {}).get("graph_enabled") is False


@pytest.mark.asyncio
async def test_answer_stream_empty_provider_output_is_not_cached(client: AsyncClient, monkeypatch) -> None:
    """Synthetic empty-stream fallback text must not be written to semantic cache."""
    from types import SimpleNamespace

    import server.api.search as search_api
    import server.services.answer_service as answer_service
    from server.models.tribrid_config_model import TriBridConfig
    from server.retrieval.fusion import TriBridFusion

    class _FakePostgres:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def get_corpus(self, repo_id: str):
            return {"repo_id": repo_id}

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        _ = repo_id
        cfg = TriBridConfig()
        cfg.semantic_cache.enabled = 1
        cfg.semantic_cache.mode = "read_write"
        cfg.semantic_cache.min_query_chars = 1
        return cfg

    async def _fake_fusion_search(self, *_args, **_kwargs):
        return []

    async def _fake_stream_chat_text(*_args, **_kwargs):
        if False:  # pragma: no cover
            yield ""

    async def _fake_lookup(self, **_kwargs):
        return None

    cache_writes: list[dict[str, object]] = []

    async def _fake_write(self, **kwargs):
        cache_writes.append(kwargs)
        return True

    def _fake_select_provider_route(*_args, **_kwargs):
        return SimpleNamespace(
            kind="litellm",
            provider_name="OpenAI",
            model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
        )

    monkeypatch.setattr(search_api, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(search_api, "load_scoped_config", _fake_load_scoped_config, raising=True)
    monkeypatch.setattr(TriBridFusion, "search", _fake_fusion_search, raising=True)
    monkeypatch.setattr(answer_service, "select_provider_route", _fake_select_provider_route, raising=True)
    monkeypatch.setattr(answer_service, "stream_chat_text", _fake_stream_chat_text, raising=True)
    monkeypatch.setattr(answer_service.SemanticCacheService, "lookup", _fake_lookup, raising=True)
    monkeypatch.setattr(answer_service.SemanticCacheService, "write", _fake_write, raising=True)

    response = await client.post(
        "/api/answer/stream",
        json={
            "query": "empty stream",
            "repo_id": "test-repo",
            "include_vector": False,
            "include_sparse": False,
            "include_graph": False,
        },
    )

    assert response.status_code == 200
    assert "Error: LLM stream produced no content" in response.text
    assert '"llm_used": false' in response.text
    assert cache_writes == []
