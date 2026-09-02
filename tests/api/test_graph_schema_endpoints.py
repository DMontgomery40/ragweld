import asyncio
import inspect
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.models.tribrid_config_model import TriBridConfig
from tests.fixtures.pdf_builder import build_pdf


def test_proposal_builder_keeps_inventory_and_chunking_off_the_api_loop() -> None:
    source = inspect.getsource(index_api.build_proposal_from_corpus)
    assert "await asyncio.to_thread(lambda: list(loader.iter_repo_files" in source
    assert "await asyncio.to_thread(chunker.chunk_file" in source


def test_schema_pdf_sampler_reads_only_stratified_pages(tmp_path: Path) -> None:
    """A large PDF proposal must not run whole-document Docling conversion behind HTTP."""
    pdf = tmp_path / "thirteen-pages.pdf"
    pdf.write_bytes(
        build_pdf(
            [
                [f"Unique schema evidence from page {page_number}."]
                for page_number in range(1, 14)
            ]
        )
    )
    sampler = getattr(index_api, "_extract_schema_sample_text_for_path", None)
    assert callable(sampler), "schema proposals need a bounded PDF page sampler"

    text = sampler(pdf, TriBridConfig())

    assert [line for line in text.splitlines() if line.startswith("# ")] == [
        "# thirteen-pages.pdf page 1",
        "# thirteen-pages.pdf page 2",
        "# thirteen-pages.pdf page 3",
        "# thirteen-pages.pdf page 6",
        "# thirteen-pages.pdf page 7",
        "# thirteen-pages.pdf page 8",
        "# thirteen-pages.pdf page 11",
        "# thirteen-pages.pdf page 12",
        "# thirteen-pages.pdf page 13",
    ]
    assert "Unique schema evidence from page 4." not in text
    assert "Unique schema evidence from page 10." not in text


@pytest.mark.parametrize("page_count", [1, 2, 3, 8, 12])
def test_schema_pdf_sampler_reads_every_page_of_small_pdfs(
    tmp_path: Path, page_count: int
) -> None:
    pdf = tmp_path / f"{page_count}-pages.pdf"
    pdf.write_bytes(
        build_pdf(
            [
                [f"Unique schema evidence from page {page_number}."]
                for page_number in range(1, page_count + 1)
            ]
        )
    )

    text = index_api._extract_schema_sample_text_for_path(pdf, TriBridConfig())

    assert [line for line in text.splitlines() if line.startswith("# ")] == [
        f"# {page_count}-pages.pdf page {page_number}"
        for page_number in range(1, page_count + 1)
    ]


@pytest.mark.asyncio
async def test_schema_proposal_refuses_a_large_textless_pdf_inside_the_edge_window(
    client: AsyncClient, tmp_path: Path
) -> None:
    corpus_id = f"schema-textless-{uuid4().hex[:8]}"
    corpus_path = tmp_path / "textless"
    corpus_path.mkdir()
    (corpus_path / "one-hundred-empty-pages.pdf").write_bytes(
        build_pdf([[] for _ in range(100)])
    )
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_path)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        configured = await client.patch(
            f"/api/config/graph_indexing?corpus_id={corpus_id}",
            json={"enabled": True, "build_code_graph": False},
        )
        assert configured.status_code == 200, configured.text

        async with asyncio.timeout(5):
            response = await client.post(
                f"/api/index/{corpus_id}/graph-schema/proposal",
                json={"force_refresh": False},
            )

        assert response.status_code == 422, response.text
        assert "no embedded PDF text" in str(response.json()["detail"])
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_graph_schema_proposal_refuses_graph_off_policy_with_typed_conflict(
    client: AsyncClient,
) -> None:
    corpus_id = f"pytest_schema_off_{uuid4().hex[:8]}"
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
    corpus_id = f"pytest_schema_required_{uuid4().hex[:8]}"
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


@pytest.mark.asyncio
async def test_semantic_index_refuses_an_unformattable_extraction_prompt_before_the_fence(
    client: AsyncClient,
) -> None:
    """D24: the operator's Semantic KG Extraction prompt is the official extractor's template.
    A template the extractor cannot format (no ``{schema}`` or ``{text}``) is refused as a
    typed 422 before any schema approval, fence, or staged generation, with the hint that
    names the System Prompts reset.
    """
    corpus_id = f"pytest_schema_prompt_{uuid4().hex[:8]}"
    corpus_path = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_path)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        patched = await client.patch(
            f"/api/config/system_prompts?corpus_id={corpus_id}",
            json={"semantic_kg_extraction": "Extract everything from: {text}"},
        )
        assert patched.status_code == 200, patched.text
        scoped = await client.get(f"/api/config?corpus_id={corpus_id}")
        assert scoped.status_code == 200, scoped.text
        assert scoped.json()["system_prompts"]["semantic_kg_extraction"] == "Extract everything from: {text}"

        response = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(corpus_path), "force_reindex": True},
        )
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "graph_extraction_prompt_invalid"
        assert detail["corpus_id"] == corpus_id
        assert "{schema}" in detail["message"]
        assert "System Prompts" in detail["operator_hint"]

        status = await client.get(f"/api/index/{corpus_id}/status")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "idle"
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
