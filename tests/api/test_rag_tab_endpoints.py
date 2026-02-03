from __future__ import annotations

from typing import Any

import pytest

from server.models.index import Chunk
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import TriBridConfig, VocabPreviewTerm
from server.retrieval.fusion import TriBridFusion


class _FakePostgres:
    """In-memory PostgresClient substitute for API tests."""

    chunks_by_repo: dict[str, list[Chunk]] = {}
    summaries_by_repo: dict[str, list[dict[str, Any]]] = {}
    last_build_by_repo: dict[str, dict[str, Any] | None] = {}
    meta_by_repo: dict[str, dict[str, Any]] = {}
    vocab_by_repo: dict[str, tuple[list[VocabPreviewTerm], int]] = {}

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

    async def vocab_preview(self, repo_id: str, top_n: int) -> tuple[list[VocabPreviewTerm], int]:
        terms, total = self.vocab_by_repo.get(repo_id, ([], 0))
        return (terms[: int(top_n)], int(total))


async def _fake_get_config(*_args: Any, **_kwargs: Any) -> TriBridConfig:
    cfg = TriBridConfig()
    # Make keyword generation deterministic / permissive for tests.
    cfg.keywords.keywords_min_freq = 1
    cfg.keywords.keywords_max_per_repo = 50
    return cfg


async def _fake_fusion_search(
    self: TriBridFusion,
    corpus_ids: list[str],
    query: str,
    config: Any,
    *,
    include_vector: bool = True,
    include_sparse: bool = True,
    include_graph: bool = True,
    top_k: int | None = None,
) -> list[ChunkMatch]:
    _ = (self, corpus_ids, config, include_vector, include_sparse, include_graph)
    # Deterministic: return config.py first for "config" queries, otherwise chunk_summaries.py first.
    if "config" in query.lower():
        paths = ["server/api/config.py", "server/api/eval.py", "server/api/dataset.py"]
    else:
        paths = ["server/api/chunk_summaries.py", "server/api/keywords.py", "server/api/eval.py"]
    out: list[ChunkMatch] = []
    for i, fp in enumerate(paths[: int(top_k or 3)]):
        out.append(
            ChunkMatch(
                chunk_id=f"c{i}",
                content="",
                file_path=fp,
                start_line=1,
                end_line=1,
                language="py",
                score=1.0 / (i + 1),
                source="vector",
                metadata={},
            )
        )
    return out


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
async def test_eval_run_list_get_delete(client, tmp_path, monkeypatch):
    # Isolate dataset + runs persistence
    import server.api.dataset as dataset_api
    import server.api.eval as eval_api

    monkeypatch.setattr(dataset_api, "_DATASET_DIR", tmp_path / "eval_dataset", raising=True)
    monkeypatch.setattr(eval_api, "_RUNS_DIR", tmp_path / "eval_runs", raising=True)
    monkeypatch.setattr(eval_api, "load_scoped_config", _fake_get_config, raising=True)
    monkeypatch.setattr(TriBridFusion, "search", _fake_fusion_search, raising=True)

    corpus_id = "test_corpus"

    # Seed dataset with 2 entries
    entries = [
        {"question": "Where is config persistence implemented?", "expected_paths": ["server/api/config.py"]},
        {"question": "Where are chunk summaries endpoints implemented?", "expected_paths": ["server/api/chunk_summaries.py"]},
    ]
    for e in entries:
        r = await client.post("/api/dataset", params={"corpus_id": corpus_id}, json=e)
        assert r.status_code == 200

    # Single entry test
    r = await client.post(
        "/api/eval/test",
        json={"corpus_id": corpus_id, "question": entries[0]["question"], "expected_paths": entries[0]["expected_paths"]},
    )
    assert r.status_code == 200
    test_result = r.json()
    assert test_result["topk_hit"] is True
    assert test_result["top_paths"]

    # Run evaluation
    r = await client.post("/api/eval/run", json={"corpus_id": corpus_id, "dataset_id": None, "sample_size": None})
    assert r.status_code == 200
    run = r.json()
    assert run["corpus_id"] == corpus_id
    assert run["total"] == 2
    assert "run_id" in run

    run_id = run["run_id"]

    # List runs
    r = await client.get("/api/eval/runs", params={"corpus_id": corpus_id})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["runs"][0]["run_id"] == run_id

    # Latest results
    r = await client.get("/api/eval/results", params={"corpus_id": corpus_id})
    assert r.status_code == 200
    assert r.json()["run_id"] == run_id

    # Run results by id
    r = await client.get(f"/api/eval/results/{run_id}")
    assert r.status_code == 200
    assert r.json()["run_id"] == run_id

    # Get eval run (alias)
    r = await client.get(f"/api/eval/run/{run_id}")
    assert r.status_code == 200
    assert r.json()["run_id"] == run_id

    # Delete eval run
    r = await client.delete(f"/api/eval/run/{run_id}")
    assert r.status_code == 200

    # Now missing
    r = await client.get(f"/api/eval/run/{run_id}")
    assert r.status_code == 404


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


@pytest.mark.asyncio
async def test_index_vocab_preview_accepts_corpus_aliases(client, monkeypatch):
    import server.api.index as index_api

    monkeypatch.setattr(index_api, "load_scoped_config", _fake_get_config, raising=True)
    monkeypatch.setattr(index_api, "PostgresClient", _FakePostgres, raising=True)

    corpus_id = "test_corpus"
    _FakePostgres.vocab_by_repo[corpus_id] = ([VocabPreviewTerm(term="config", doc_count=3)], 42)

    # Preferred param: corpus_id
    r = await client.get("/api/index/vocab-preview", params={"corpus_id": corpus_id, "top_n": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["corpus_id"] == corpus_id
    assert data["top_n"] == 10
    assert data["total_terms"] == 42
    assert data["terms"][0]["term"] == "config"
    assert data["terms"][0]["doc_count"] == 3
    assert data["tokenizer"]
    assert data["ts_config"]

    # Legacy param: repo_id
    r = await client.get("/api/index/vocab-preview", params={"repo_id": corpus_id, "top_n": 10})
    assert r.status_code == 200
    assert r.json()["corpus_id"] == corpus_id

    # Legacy param: repo
    r = await client.get("/api/index/vocab-preview", params={"repo": corpus_id, "top_n": 10})
    assert r.status_code == 200
    assert r.json()["corpus_id"] == corpus_id

