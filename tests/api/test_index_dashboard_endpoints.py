"""API tests for dashboard index summary + storage endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_index_status_uses_corpus_scoped_config(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.api.index as index_api
    from server.models.index import IndexStats
    from server.models.tribrid_config_model import TriBridConfig

    seen_repo_ids: list[str | None] = []

    class _FakePostgres:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def get_corpus(self, repo_id: str) -> dict[str, object]:
            return {"repo_id": repo_id, "meta": {}}

        async def get_index_fence(self, _repo_id: str) -> None:
            return None

        async def database_now(self) -> datetime:
            return datetime.now(UTC)

        async def get_index_stats(self, repo_id: str) -> IndexStats:
            return IndexStats(
                repo_id=repo_id,
                total_files=1,
                total_chunks=1,
                total_tokens=10,
                embedding_model="deterministic",
                embedding_dimensions=1536,
                last_indexed=datetime.now(UTC),
                file_breakdown={".py": 1},
            )

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        seen_repo_ids.append(repo_id)
        return TriBridConfig()

    monkeypatch.setattr(index_api, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(index_api, "load_scoped_config", _fake_load_scoped_config, raising=True)

    corpus_id = "scoped-corpus"
    index_api._STATUS.pop(corpus_id, None)
    index_api._STATS.pop(corpus_id, None)

    response = await client.get(f"/api/index/{corpus_id}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert seen_repo_ids == [corpus_id]
