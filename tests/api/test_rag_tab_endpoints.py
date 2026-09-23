from __future__ import annotations

from typing import Any

import pytest

from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig


class _FakePostgres:
    """In-memory PostgresClient substitute for API tests."""

    chunks_by_repo: dict[str, list[Chunk]] = {}
    summaries_by_repo: dict[str, list[dict[str, Any]]] = {}
    last_build_by_repo: dict[str, dict[str, Any] | None] = {}
    meta_by_repo: dict[str, dict[str, Any]] = {}

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def connect(self) -> None:  # pragma: no cover
        return

    async def list_chunks_for_repo(self, corpus_id: str, limit: int | None = None) -> list[Chunk]:
        chunks = list(self.chunks_by_repo.get(corpus_id, []))
        return chunks if limit is None else chunks[: int(limit)]

    async def replace_chunk_summaries(self, corpus_id: str, summaries: list[Any], last_build: Any) -> None:
        # Store as JSON-ish dicts so Pydantic validation mirrors real behavior
        self.summaries_by_repo[corpus_id] = [s.model_dump(mode="json") for s in summaries]
        self.last_build_by_repo[corpus_id] = last_build.model_dump(mode="json") if last_build is not None else None

    async def list_chunk_summaries(self, corpus_id: str, limit: int | None = None) -> list[Any]:
        raw = list(self.summaries_by_repo.get(corpus_id, []))
        if limit is not None:
            raw = raw[: int(limit)]
        # Import locally to avoid circular imports in module import order
        from server.models.tribrid_config_model import ChunkSummary

        return [ChunkSummary.model_validate(x) for x in raw]

    async def get_chunk_summaries_last_build(self, corpus_id: str) -> Any | None:
        raw = self.last_build_by_repo.get(corpus_id)
        if raw is None:
            return None
        from server.models.tribrid_config_model import ChunkSummariesLastBuild

        return ChunkSummariesLastBuild.model_validate(raw)

    async def delete_chunk_summary(self, chunk_id: str, corpus_id: str | None = None) -> int:
        deleted = 0
        if corpus_id is not None:
            before = len(self.summaries_by_repo.get(corpus_id, []))
            self.summaries_by_repo[corpus_id] = [
                s for s in self.summaries_by_repo.get(corpus_id, []) if s.get("chunk_id") != chunk_id
            ]
            after = len(self.summaries_by_repo.get(corpus_id, []))
            deleted = before - after
        else:
            for rid in list(self.summaries_by_repo.keys()):
                before = len(self.summaries_by_repo[rid])
                self.summaries_by_repo[rid] = [s for s in self.summaries_by_repo[rid] if s.get("chunk_id") != chunk_id]
                after = len(self.summaries_by_repo[rid])
                deleted += before - after
        return deleted

    async def update_corpus_meta(self, corpus_id: str, meta: dict[str, Any]) -> None:
        cur = dict(self.meta_by_repo.get(corpus_id, {}))
        cur.update(meta)
        self.meta_by_repo[corpus_id] = cur


async def _fake_get_config(*_args: Any, **_kwargs: Any) -> TriBridConfig:
    cfg = TriBridConfig()
    # Make keyword generation deterministic / permissive for tests.
    cfg.keywords.keywords_min_freq = 1
    cfg.keywords.keywords_max_per_repo = 50
    return cfg


@pytest.mark.asyncio
async def test_eval_dataset_crud(client, tmp_path, monkeypatch):
    # Isolate file-backed persistence
    import server.api.dataset as dataset_api

    monkeypatch.setattr(dataset_api, "_DATASET_DIR", tmp_path / "eval_dataset", raising=True)

    corpus_id = "test_corpus"

    # List empty
    r = await client.get("/api/dataset", params={"corpus_id": corpus_id})
    assert r.status_code == 200
    assert r.json() == []

    # Add entry
    payload = {"question": "Where is config persistence implemented?", "expected_paths": ["server/api/config.py"]}
    r = await client.post("/api/dataset", params={"corpus_id": corpus_id}, json=payload)
    assert r.status_code == 200
    entry = r.json()
    assert entry["question"] == payload["question"]
    assert entry["expected_paths"] == payload["expected_paths"]
    assert "entry_id" in entry

    # Update entry (PUT)
    entry_id = entry["entry_id"]
    updated = {**entry, "question": "Where is config persisted?"}
    r = await client.put(f"/api/dataset/{entry_id}", params={"corpus_id": corpus_id}, json=updated)
    assert r.status_code == 200
    assert r.json()["question"] == "Where is config persisted?"

    # Delete entry
    r = await client.delete(f"/api/dataset/{entry_id}", params={"corpus_id": corpus_id})
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_chunk_summaries_build_list_delete(client, monkeypatch):
    import server.api.chunk_summaries as cs_api

    # Patch config + storage backend
    monkeypatch.setattr(cs_api, "get_config", _fake_get_config, raising=True)
    monkeypatch.setattr(cs_api, "PostgresClient", _FakePostgres, raising=True)

    corpus_id = "test_corpus"
    _FakePostgres.chunks_by_repo[corpus_id] = [
        Chunk(
            chunk_id="c1",
            file_path="src/foo.py",
            start_line=1,
            end_line=10,
            language="py",
            content="def foo():\n    return 1\n",
            token_count=0,
            embedding=None,
            summary=None,
        ),
        Chunk(
            chunk_id="c2",
            file_path="src/bar.py",
            start_line=1,
            end_line=10,
            language="py",
            content="class Bar:\n    pass\n",
            token_count=0,
            embedding=None,
            summary=None,
        ),
    ]

    # Build
    r = await client.post("/api/chunk_summaries/build", json={"corpus_id": corpus_id, "max": 2, "enrich": True})
    assert r.status_code == 200
    data = r.json()
    assert data["corpus_id"] == corpus_id
    assert len(data["chunk_summaries"]) == 2
    assert data["last_build"]["total"] == 2

    # List
    r = await client.get("/api/chunk_summaries", params={"corpus_id": corpus_id})
    assert r.status_code == 200
    listed = r.json()
    assert len(listed["chunk_summaries"]) == 2

    # Delete one
    r = await client.delete("/api/chunk_summaries/c1", params={"corpus_id": corpus_id})
    assert r.status_code == 200
    assert r.json()["deleted"] == 1


@pytest.mark.asyncio
async def test_keywords_generate(client, monkeypatch):
    import server.api.keywords as kw_api

    monkeypatch.setattr(kw_api, "get_config", _fake_get_config, raising=True)
    monkeypatch.setattr(kw_api, "PostgresClient", _FakePostgres, raising=True)

    corpus_id = "test_corpus"
    _FakePostgres.chunks_by_repo[corpus_id] = [
        Chunk(
            chunk_id="c1",
            file_path="src/foo.py",
            start_line=1,
            end_line=10,
            language="py",
            content="def foo():\n    foo()\n    return 1\n",
            token_count=0,
            embedding=None,
            summary=None,
        ),
        Chunk(
            chunk_id="c2",
            file_path="src/bar.py",
            start_line=1,
            end_line=10,
            language="py",
            content="class Bar:\n    def foo(self):\n        return 2\n",
            token_count=0,
            embedding=None,
            summary=None,
        ),
    ]

    r = await client.post("/api/keywords/generate", json={"corpus_id": corpus_id})
    assert r.status_code == 200
    data = r.json()
    assert data["corpus_id"] == corpus_id
    assert data["count"] == len(data["keywords"])
    # Ensure persistence was invoked
    assert "keywords" in _FakePostgres.meta_by_repo.get(corpus_id, {})


