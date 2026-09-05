from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from pypdf import PdfReader

from server.db.postgres import PostgresClient
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

_APOLLO_SOURCE = Path("/srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf")
_MODEL = os.environ.get("GRAPH_E2E_KG_MODEL", "openai.gpt-5.6-luna")


@pytest.mark.requires_model_gateway
async def test_real_full_apollo_pdf_schema_proposal_fits_the_public_edge_window(
    client: AsyncClient,
) -> None:
    """The production PDF path must return before the public proxy closes the request."""
    if not _APOLLO_SOURCE.is_file():
        pytest.skip(f"Apollo source is unavailable on this runtime: {_APOLLO_SOURCE}")

    corpus_id = f"pytest_apollo_full_schema_{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_APOLLO_SOURCE.parent)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        configured = await client.patch(
            f"/api/config/graph_indexing?corpus_id={corpus_id}",
            json={
                "enabled": True,
                "build_code_graph": False,
                "semantic_kg_llm_model": _MODEL,
            },
        )
        assert configured.status_code == 200, configured.text

        loop = asyncio.get_running_loop()
        started = loop.time()
        async with asyncio.timeout(90):
            response = await client.post(
                f"/api/index/{corpus_id}/graph-schema/proposal",
                json={"force_refresh": False},
            )
        elapsed = loop.time() - started

        assert response.status_code == 200, response.text
        assert elapsed < 90
        assert response.json()["sample"]["chunk_ids"]
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.requires_model_gateway
async def test_real_apollo_schema_proposal_persists_reuses_and_invalidates_approval(
    client: AsyncClient, tmp_path: Path
) -> None:
    if not _APOLLO_SOURCE.is_file():
        pytest.skip(f"Apollo source is unavailable on this runtime: {_APOLLO_SOURCE}")

    corpus_id = f"pytest_apollo_schema_{uuid.uuid4().hex[:8]}"
    subset = tmp_path / "apollo-subset"
    subset.mkdir()
    reader = PdfReader(_APOLLO_SOURCE)
    last = len(reader.pages) - 1
    page_indexes = sorted(
        {
            0,
            1,
            2,
            max(0, last // 2 - 1),
            last // 2,
            min(last, last // 2 + 1),
            max(0, last - 2),
            max(0, last - 1),
            last,
        }
    )
    page_text = [
        f"# Apollo 11 Mission Report page {index + 1}\n\n{reader.pages[index].extract_text() or ''}"
        for index in page_indexes
    ]
    (subset / "A11_MissionReport_subset.md").write_text(
        "\n\n".join(page_text), encoding="utf-8"
    )
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    await pg.connect()
    try:
        created = await client.post(
            "/api/corpora",
            json={"corpus_id": corpus_id, "name": corpus_id, "path": str(subset)},
        )
        assert created.status_code in (200, 201), created.text
        configured = await client.patch(
            f"/api/config/graph_indexing?corpus_id={corpus_id}",
            json={
                "enabled": True,
                "build_code_graph": False,
                "semantic_kg_llm_model": _MODEL,
            },
        )
        assert configured.status_code == 200, configured.text

        first = await client.post(
            f"/api/index/{corpus_id}/graph-schema/proposal",
            json={"force_refresh": False},
            timeout=180,
        )
        assert first.status_code == 200, first.text
        proposal = first.json()
        assert proposal["corpus_id"] == corpus_id
        assert proposal["model_alias"] == _MODEL
        assert proposal["graphrag_version"] == "1.19.0"
        assert proposal["schema_hash"]
        assert proposal["sample"]["chunk_ids"]
        assert proposal["schema"]["additional_node_types"] is False
        assert proposal["schema"]["additional_relationship_types"] is False
        assert proposal["schema"]["additional_patterns"] is False

        persisted = await pg.get_graph_schema_proposal(corpus_id)
        assert persisted is not None
        assert persisted.schema_hash == proposal["schema_hash"]
        assert persisted.input_fingerprint == proposal["input_fingerprint"]

        # Both writers lock and merge the authoritative JSONB row. A proposal write
        # racing an unrelated metadata patch must preserve both keys, regardless of
        # which transaction takes the row lock first.
        await asyncio.gather(
            pg.patch_corpus_meta_locked(corpus_id, {"parallel_marker": "preserved"}),
            pg.set_graph_schema_proposal(corpus_id, persisted),
        )
        after_race = await pg.get_corpus(corpus_id)
        assert (after_race or {})["meta"]["parallel_marker"] == "preserved"
        assert (
            (after_race or {})["meta"]["graph_schema_proposal"]["schema_hash"]
            == proposal["schema_hash"]
        )

        reused = await client.post(
            f"/api/index/{corpus_id}/graph-schema/proposal",
            json={"force_refresh": False},
            timeout=30,
        )
        assert reused.status_code == 200, reused.text
        assert reused.json() == proposal

        missing = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(subset), "force_reindex": True},
        )
        assert missing.status_code == 409, missing.text
        assert missing.json()["detail"]["code"] == "graph_schema_approval_required"

        # A new source file changes the canonical inventory fingerprint. The exact
        # proposal the operator reviewed can no longer authorize the run.
        (subset / "new-evidence.md").write_text(
            "# Apollo guidance update\n\nThe crew reviewed a new landing procedure.\n",
            encoding="utf-8",
        )
        stale = await client.post(
            "/api/index",
            json={
                "corpus_id": corpus_id,
                "repo_path": str(subset),
                "force_reindex": True,
                "approved_graph_schema_hash": proposal["schema_hash"],
            },
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "graph_schema_approval_required"
        assert stale.json()["detail"]["current_schema_hash"] is None

        recall = await client.post(
            "/api/index/recall_default/graph-schema/proposal",
            json={"force_refresh": False},
        )
        assert recall.status_code == 409, recall.text
        assert recall.json()["detail"]["policy"] == "excluded"
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
        await pg.disconnect()


@pytest.mark.requires_model_gateway
async def test_numeric_only_corpus_proposal_is_a_typed_422_not_a_500(
    client: AsyncClient, tmp_path: Path
) -> None:
    """Task 8 drive finding D8: a corpus whose sampled text carries no extractable domain
    (the disposable numeric fixture) makes the proposer return an empty schema; the domain
    validator rejects it, and the API used to surface that as an unhandled 500. The operator
    must get a typed 422 that names the reason instead.
    """
    corpus_dir = tmp_path / "numeric-only"
    corpus_dir.mkdir()
    (corpus_dir / "measurements.txt").write_text("0000 1111 2222 3333 4444 5555.\n" * 20)
    corpus_id = f"pytest_numeric_schema_{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_dir)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        configured = await client.patch(
            f"/api/config/graph_indexing?corpus_id={corpus_id}",
            json={"enabled": True, "build_code_graph": False, "semantic_kg_llm_model": _MODEL},
        )
        assert configured.status_code == 200, configured.text
        response = await client.post(
            f"/api/index/{corpus_id}/graph-schema/proposal", json={"force_refresh": True}
        )
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "graph_schema_unusable"
        assert detail["corpus_id"] == corpus_id
        assert "node types" in detail["message"]
        assert detail["model_alias"] == _MODEL
        assert detail["operator_hint"]
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
