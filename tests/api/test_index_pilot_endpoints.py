import json
import shutil
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.retrieval.contracts import contract_hash, dense_contract_from_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pilot_dir(corpus_id: str) -> Path:
    return _repo_root() / "data" / "retrieval_pilot" / corpus_id


@pytest.mark.asyncio
async def test_retrieval_pilot_export_persists_manifest_and_status(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_pilot_export_{uuid.uuid4().hex[:8]}"
    repo = tmp_path / "pilot_repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "math.py").write_text(
        "def fibonacci(n: int) -> int:\n    return n if n < 2 else fibonacci(n - 1) + fibonacci(n - 2)\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Pilot corpus\n\nThis corpus validates provenance export.\n", encoding="utf-8")

    export_dir = _pilot_dir(corpus_id)
    shutil.rmtree(export_dir, ignore_errors=True)

    try:
        res = await client.post(
            f"/api/index/{corpus_id}/pilot/export",
            json={"corpus_id": corpus_id, "repo_path": str(repo), "force_rebuild": True},
        )
        assert res.status_code == 200
        body = res.json()
        status = body["status"]
        assert status["backend"] == "haystack_qdrant_sidecar"
        assert status["export_exists"] is True
        assert status["exported_file_count"] == 2
        assert status["exported_chunk_count"] >= 2
        assert "file_path" in status["provenance_fields"]
        assert Path(status["documents_path"]).exists()
        assert Path(status["manifest_path"]).exists()

        status_res = await client.get(
            f"/api/index/{corpus_id}/pilot/status",
            params={"repo_path": str(repo)},
        )
        assert status_res.status_code == 200
        status_body = status_res.json()
        assert status_body["export_exists"] is True
        assert status_body["exported_file_count"] == 2
        assert status_body["exported_chunk_count"] == status["exported_chunk_count"]
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_retrieval_pilot_search_preview_returns_provenance_hits(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_pilot_search_{uuid.uuid4().hex[:8]}"
    repo = tmp_path / "pilot_search_repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "search_target.py").write_text(
        "def answer_question(question: str) -> str:\n    return f'answer:{question}'\n",
        encoding="utf-8",
    )
    (repo / "notes.md").write_text("answer_question is the function operators should inspect first.\n", encoding="utf-8")

    export_dir = _pilot_dir(corpus_id)
    shutil.rmtree(export_dir, ignore_errors=True)

    try:
        export_res = await client.post(
            f"/api/index/{corpus_id}/pilot/export",
            json={"corpus_id": corpus_id, "repo_path": str(repo), "force_rebuild": True},
        )
        assert export_res.status_code == 200

        search_res = await client.post(
            f"/api/index/{corpus_id}/pilot/search-preview",
            params={"repo_path": str(repo)},
            json={"corpus_id": corpus_id, "query": "answer_question", "top_k": 3},
        )
        assert search_res.status_code == 200
        body = search_res.json()
        assert body["query"] == "answer_question"
        assert len(body["results"]) >= 1
        top = body["results"][0]
        assert top["file_path"] in {"src/search_target.py", "notes.md"}
        assert int(top["start_line"]) >= 1
        assert int(top["end_line"]) >= int(top["start_line"])
        assert "source_path" in top
        assert body["status"]["search_preview_ready"] is True
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)


@pytest.mark.requires_qdrant
@pytest.mark.asyncio
async def test_retrieval_pilot_ingest_and_real_search_return_qdrant_hits(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_pilot_real_{uuid.uuid4().hex[:8]}"
    repo = tmp_path / "pilot_real_repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "retrieval_target.py").write_text(
        "def retrieve_context(question: str) -> str:\n    return f'context:{question}'\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("retrieve_context is the retrieval entry point.\n", encoding="utf-8")

    export_dir = _pilot_dir(corpus_id)
    shutil.rmtree(export_dir, ignore_errors=True)

    try:
        export_res = await client.post(
            f"/api/index/{corpus_id}/pilot/export",
            json={"corpus_id": corpus_id, "repo_path": str(repo), "force_rebuild": True},
        )
        assert export_res.status_code == 200

        ingest_res = await client.post(
            f"/api/index/{corpus_id}/pilot/ingest",
            params={"repo_path": str(repo)},
            json={"corpus_id": corpus_id, "force_rebuild": True},
        )
        assert ingest_res.status_code == 200
        ingest_body = ingest_res.json()
        assert ingest_body["status"]["execution_ready"] is True
        assert ingest_body["status"]["indexed_document_count"] >= 1
        assert ingest_body["status"]["qdrant_url"].startswith("http")

        # The pilot must record the operator's real dense contract at ingest time.
        manifest_path = _pilot_dir(corpus_id) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_contract = dense_contract_from_config(load_config())
        assert manifest["dense_contract_hash"] == contract_hash(expected_contract)
        assert manifest["dense_contract"]["dimensions"] == expected_contract["dimensions"]

        search_res = await client.post(
            f"/api/index/{corpus_id}/pilot/search",
            params={"repo_path": str(repo)},
            json={"corpus_id": corpus_id, "query": "retrieve_context", "top_k": 3},
        )
        assert search_res.status_code == 200
        body = search_res.json()
        assert body["backend"] == "haystack_qdrant_local"
        assert len(body["results"]) >= 1
        top = body["results"][0]
        assert top["file_path"] in {"src/retrieval_target.py", "README.md"}
        assert float(top["score"]) >= 0.0
        assert body["status"]["execution_ready"] is True
        # Citation-capable result shape: full content, leg discriminator, metadata.
        assert top["content"].strip()
        assert top["source"] == "vector"
        assert top["metadata"].get("file_path") == top["file_path"]

        # A drifted stored contract must fail closed with the typed 409, not
        # silently search under a different embedding space.
        drifted = dict(manifest)
        drifted["dense_contract"] = dict(manifest["dense_contract"], dimensions=9999)
        manifest_path.write_text(json.dumps(drifted, indent=2, sort_keys=True), encoding="utf-8")
        mismatch_res = await client.post(
            f"/api/index/{corpus_id}/pilot/search",
            params={"repo_path": str(repo)},
            json={"corpus_id": corpus_id, "query": "retrieve_context", "top_k": 3},
        )
        assert mismatch_res.status_code == 409, mismatch_res.text
        detail = mismatch_res.json()["detail"]
        assert detail["code"] == "embedding_contract_mismatch"
        assert detail["leg"] == "vector"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        # Re-ingesting under a drifted contract without force_rebuild is a 409.
        manifest_path.write_text(json.dumps(drifted, indent=2, sort_keys=True), encoding="utf-8")
        drift_ingest = await client.post(
            f"/api/index/{corpus_id}/pilot/ingest",
            params={"repo_path": str(repo)},
            json={"corpus_id": corpus_id, "force_rebuild": False},
        )
        assert drift_ingest.status_code == 409, drift_ingest.text
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        # A wiped/empty Qdrant collection with a "ready" manifest must read as
        # not-ready (404), never as an empty 200.
        import httpx as _httpx

        collection = body["status"]["collection_name"]
        qdrant_url = body["status"]["qdrant_url"]
        delete_res = _httpx.delete(f"{qdrant_url}/collections/{collection}", timeout=10.0)
        assert delete_res.status_code in (200, 202), delete_res.text
        wiped_res = await client.post(
            f"/api/index/{corpus_id}/pilot/search",
            params={"repo_path": str(repo)},
            json={"corpus_id": corpus_id, "query": "retrieve_context", "top_k": 3},
        )
        assert wiped_res.status_code == 404, wiped_res.text
        assert "re-ingest" in wiped_res.json()["detail"]

    finally:
        shutil.rmtree(export_dir, ignore_errors=True)
