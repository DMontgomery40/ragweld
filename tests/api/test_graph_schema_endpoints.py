import asyncio
import contextlib
import hashlib
import inspect
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from neo4j_graphrag.components.schema import GraphSchema, NodeType, Pattern, RelationshipType
from starlette.requests import Request

import server.api.index as index_api
from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.graphrag_schema import (
    canonical_schema_dict,
    graph_schema_hash,
    normalize_domain_schema,
)
from server.models.index import GraphSchemaProposal, GraphSchemaSample, IndexRequest
from server.models.tribrid_config_model import TriBridConfig
from server.services import config_store
from tests.fixtures.pdf_builder import build_pdf


@pytest.mark.asyncio
async def test_schema_fingerprint_invalidates_pre_coverage_prompt_proposals(tmp_path: Path) -> None:
    document = tmp_path / "incident.md"
    document.write_text("A failed valve caused a pressure alarm.")
    cfg = TriBridConfig()
    corpus = {"repo_id": "proposal-context", "path": str(tmp_path)}
    stat = document.stat()
    previous_payload = {
        "files": [(document.name, stat.st_size, stat.st_mtime_ns)],
        "model_alias": index_api._semantic_kg_model_override(cfg),
        "sampling_recipe": "documents-and-positions-v2",
        "graphrag": "neo4j-graphrag:1.19.0",
    }
    previous = hashlib.sha256(json.dumps(previous_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    current = await index_api.graph_schema_input_fingerprint(corpus, cfg)
    assert current != previous, "changed schema instructions must invalidate previously approved proposals"
    assert current == await index_api.graph_schema_input_fingerprint(corpus, cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_context", ["root", "chunking", "reasoning", "tokenization", "parquet_extraction"])
async def test_schema_fingerprint_binds_the_actual_proposal_context(tmp_path: Path, changed_context: str) -> None:
    original = tmp_path / "original"
    copied = tmp_path / "copied"
    original.mkdir()
    copied.mkdir()
    content = "A failed valve caused a pressure alarm."
    for path in (original, copied):
        (path / "incident.md").write_text(content)
        os.utime(path / "incident.md", ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    cfg = TriBridConfig()
    corpus = {"repo_id": "proposal-context", "path": str(original)}
    first = await index_api.graph_schema_input_fingerprint(corpus, cfg)
    if changed_context == "root":
        corpus = {**corpus, "path": str(copied)}
    elif changed_context == "chunking":
        cfg = cfg.model_copy(update={"chunking": cfg.chunking.model_copy(update={"chunk_size": 2000})})
    elif changed_context == "tokenization":
        cfg = cfg.model_copy(update={"tokenization": cfg.tokenization.model_copy(update={"lowercase": not cfg.tokenization.lowercase})})
    elif changed_context == "parquet_extraction":
        cfg = cfg.model_copy(update={"indexing": cfg.indexing.model_copy(update={"parquet_extract_max_rows": cfg.indexing.parquet_extract_max_rows + 1})})
    else:
        effort = "high" if cfg.graph_indexing.semantic_kg_reasoning_effort != "high" else "low"
        cfg = cfg.model_copy(update={"graph_indexing": cfg.graph_indexing.model_copy(update={"semantic_kg_reasoning_effort": effort})})
    assert await index_api.graph_schema_input_fingerprint(corpus, cfg) != first


def test_proposal_builder_keeps_inventory_and_chunking_off_the_api_loop() -> None:
    source = inspect.getsource(index_api.build_proposal_from_corpus)
    assert "await asyncio.to_thread(lambda: list(loader.iter_repo_files" in source
    assert "await asyncio.to_thread(chunker.chunk_file" in source


def test_schema_pdf_sampler_reads_only_stratified_pages(tmp_path: Path) -> None:
    """A large PDF proposal must not run whole-document Docling conversion behind HTTP."""
    pdf = tmp_path / "long-report.pdf"
    pdf.write_bytes(
        build_pdf(
            [
                [f"Unique schema evidence from page {page_number}."]
                for page_number in range(1, 360)
            ]
        )
    )
    sampler = getattr(index_api, "_extract_schema_sample_text_for_path", None)
    assert callable(sampler), "schema proposals need a bounded PDF page sampler"

    text = sampler(pdf, TriBridConfig())

    sampled = [int(line.rsplit(" ", 1)[1]) for line in text.splitlines() if line.startswith("# ")]
    assert len(sampled) == 36
    assert sampled[0] == 1 and sampled[-1] == 359
    assert max(b-a for a,b in zip(sampled,sampled[1:], strict=False)) <= 11


@pytest.mark.parametrize("page_count", [1, 2, 3, 8, 12, 13, 35, 36])
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
    corpus_id = f"pytest_schema_textless_{uuid4().hex[:8]}"
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


@pytest.mark.asyncio
@pytest.mark.requires_postgres
@pytest.mark.parametrize("root_kind", ["different", "registered", "symlink", "relative"])
@pytest.mark.parametrize("boundary", ["start", "approval_recheck"])
async def test_approved_schema_only_authorizes_the_registered_resolved_root(
    tmp_path: Path, root_kind: str, boundary: str
) -> None:
    """Real start boundary and persisted approval; never execute the spawned index task."""
    corpus_id = f"pytest_schema_root_{uuid4().hex[:8]}"
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / "facts.txt").write_text("Ada founded Analytical Engines.", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    (other / "stars.txt").write_text("Sirius is a star.", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(approved, target_is_directory=True)
    requested = {
        "different": str(other),
        "registered": str(approved),
        "symlink": str(alias),
        "relative": os.path.relpath(approved, index_api._resolve_corpus_root(".")),
    }[root_kind]
    cfg = load_config().model_copy(deep=True)
    cfg.graph_indexing.enabled = True
    cfg.graph_indexing.build_code_graph = False
    cfg.graph_indexing.semantic_kg_llm_model = "openai.gpt-5.6-luna"
    cfg.indexing.figures.enabled = False
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        await pg.upsert_corpus(corpus_id, corpus_id, str(approved))
        await config_store.save_config(cfg, repo_id=corpus_id)
        corpus, cfg = await index_api.load_corpus_and_scoped_config(corpus_id)
        schema = canonical_schema_dict(normalize_domain_schema(GraphSchema(
            node_types=(NodeType(label="Person"), NodeType(label="Organization")),
            relationship_types=(RelationshipType(label="FOUNDED"),),
            patterns=(Pattern(source="Person", relationship="FOUNDED", target="Organization"),),
        )))
        proposal = GraphSchemaProposal(
            corpus_id=corpus_id,
            policy="semantic",
            input_fingerprint=await index_api.graph_schema_input_fingerprint(corpus, cfg),
            schema_hash=graph_schema_hash(schema),
            schema=schema,
            sample=GraphSchemaSample(chunk_ids=[], chunk_hashes=[]),
            model_alias=index_api._semantic_kg_model_override(cfg),
            created_at=datetime.now(UTC),
        )
        await pg.set_graph_schema_proposal(corpus_id, proposal)
        request = IndexRequest(
            corpus_id=corpus_id, repo_path=requested,
            approved_graph_schema_hash=proposal.schema_hash,
        )
        http_request = Request({"type": "http", "headers": []})
        async def approve():
            if boundary == "start":
                return await index_api.start_index(request, http_request)
            return await index_api.require_approved_graph_schema(
                corpus, cfg, repo_path=requested, provided_hash=proposal.schema_hash
            )

        if root_kind == "different":
            with pytest.raises(index_api.HTTPException) as raised:
                await approve()
            assert raised.value.status_code == 400
            assert "registered" in str(raised.value.detail)
            assert corpus_id not in index_api._TASKS
        else:
            result = await approve()
            if boundary == "start":
                assert result.status == "indexing"
            else:
                assert result.schema_hash == proposal.schema_hash
    finally:
        task = index_api._TASKS.pop(corpus_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await pg.delete_corpus(corpus_id)
        await pg.disconnect()
        config_store.get_config_store().clear_cache(corpus_id)
