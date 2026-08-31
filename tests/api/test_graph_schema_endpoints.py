from pathlib import Path
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig


@pytest.mark.asyncio
async def test_proposal_builder_uses_the_complete_public_chunker_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "early.md").write_text("# Early\n\n" + "crew mission telemetry " * 80)
    (tmp_path / "late.md").write_text("# Late\n\n" + "landing procedure review " * 80)
    cfg = TriBridConfig()
    cfg.chunking.chunking_strategy = "fixed_chars"
    cfg.chunking.chunk_size = 240
    cfg.chunking.chunk_overlap = 0
    cfg.graph_indexing.semantic_kg_llm_model = "deepseek.deepseek-v4-flash"
    monkeypatch.setattr(index_api, "warm_sampler", lambda _chunker: None)
    monkeypatch.setattr(
        index_api,
        "_resolve_semantic_kg_route",
        lambda _cfg: SimpleNamespace(
            model="deepseek-v4-flash", base_url="http://gateway/v1", api_key="test-key"
        ),
    )
    captured: dict[str, object] = {}

    async def _capture_proposal(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(index_api, "derive_graph_schema_proposal", _capture_proposal)

    result = await index_api.build_proposal_from_corpus(
        {"repo_id": "apollo-sample", "path": str(tmp_path), "meta": {}},
        cfg,
        fingerprint="f" * 64,
    )

    chunks = captured["chunks"]
    assert isinstance(chunks, list) and chunks
    assert {chunk.file_path for chunk in chunks} == {"early.md", "late.md"}
    assert all(chunk.chunk_id.startswith(chunk.file_path) for chunk in chunks)
    assert result is not None


@pytest.mark.asyncio
async def test_proposal_inventory_and_chunking_run_off_the_api_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "sample.md"
    source.write_text("# Apollo\n\nMission telemetry and crew procedures.")
    loop_thread = threading.get_ident()
    worker_threads: dict[str, int] = {}

    class _RecordingLoader:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def iter_repo_files(self, _root: str):
            worker_threads["inventory"] = threading.get_ident()
            return iter([("sample.md", source)])

    class _RecordingChunker:
        def __init__(self, *_args: object) -> None:
            pass

        def chunk_file(self, file_path: str, content: str) -> list[Chunk]:
            worker_threads["chunking"] = threading.get_ident()
            return [
                Chunk(
                    chunk_id=f"{file_path}:1-2:0",
                    content=content,
                    file_path=file_path,
                    start_line=1,
                    end_line=2,
                )
            ]

    monkeypatch.setattr(index_api, "FileLoader", _RecordingLoader)
    monkeypatch.setattr(index_api, "Chunker", _RecordingChunker)
    monkeypatch.setattr(index_api, "warm_sampler", lambda _chunker: None)
    monkeypatch.setattr(
        index_api,
        "_resolve_semantic_kg_route",
        lambda _cfg: SimpleNamespace(
            model="deepseek-v4-flash", base_url="http://gateway/v1", api_key="test-key"
        ),
    )

    async def _capture_proposal(**kwargs: object) -> object:
        return kwargs

    monkeypatch.setattr(index_api, "derive_graph_schema_proposal", _capture_proposal)

    await index_api.build_proposal_from_corpus(
        {"repo_id": "apollo-sample", "path": str(tmp_path), "meta": {}},
        TriBridConfig(),
        fingerprint="f" * 64,
    )

    assert worker_threads["inventory"] != loop_thread
    assert worker_threads["chunking"] != loop_thread

@pytest.mark.asyncio
async def test_graph_schema_proposal_refuses_graph_off_policy_with_typed_conflict(
    client: AsyncClient,
) -> None:
    corpus_id = f"schema-off-{uuid4().hex[:8]}"
    corpus_path = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_path)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        patched = await client.patch(
            f"/api/config/graph_indexing?corpus_id={corpus_id}", json={"enabled": False}
        )
        assert patched.status_code == 200, patched.text

        response = await client.post(
            f"/api/index/{corpus_id}/graph-schema/proposal",
            json={"force_refresh": False},
        )
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "graph_schema_policy_not_semantic"
        assert detail["policy"] == "off"
        assert "operator_hint" in detail
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_semantic_index_refuses_missing_schema_approval_before_taking_a_run_fence(
    client: AsyncClient,
) -> None:
    corpus_id = f"schema-required-{uuid4().hex[:8]}"
    corpus_path = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_path)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        response = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(corpus_path), "force_reindex": True},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "graph_schema_approval_required"

        status = await client.get(f"/api/index/{corpus_id}/status")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "idle"
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
