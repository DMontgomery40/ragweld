"""Live end-to-end proof of the source document evidence viewer.

Indexes a corpus of markdown + a two-page PDF + an HTML handbook through the real API (Docling,
Postgres, Qdrant), then proves that every enabled retrieval leg carries typed provenance, that the
viewer endpoints serve text/PDF pages/rich markdown with honest provenance states, that path
escapes and unindexed files 404, that staleness is detected, and that promotion/deletion keep the
``documents`` table consistent. Nothing is mocked.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import shutil
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.generations import STAGING_REPO_PREFIX
from server.models.index import Chunk
from server.services import config_store
from tests.fixtures.pdf_builder import (
    ACCEPTANCE_DOCS_DIR,
    PAGE_TWO_SENTENCE,
    build_aurora_report_pdf,
)
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_MD_CORPUS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance_corpus"
PDF = "aurora-mission-report.pdf"
HTML = "calibration-handbook.html"
MD = "sensor-calibration.md"


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 600.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    last: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        res = await client.get(f"/api/index/{corpus_id}/status")
        assert res.status_code == 200, res.text
        last = res.json()
        if last.get("status") in {"complete", "error", "cancelled"}:
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"index did not finish in time: {last}")


async def _wait_fence_released(pg: PostgresClient, corpus_id: str, *, timeout_s: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await pg.get_index_fence(corpus_id) is None:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("fence was not released")


def _materialize_corpus(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for src in _MD_CORPUS.glob("*.md"):
        shutil.copy2(src, root / src.name)
    for src in ACCEPTANCE_DOCS_DIR.iterdir():
        if src.is_file():
            shutil.copy2(src, root / src.name)


async def _configure(pg: PostgresClient, corpus_id: str) -> None:
    cfg = load_config()
    cfg.embedding.embedding_backend = "deterministic"
    cfg.indexing.generation_retention_seconds = 0
    cfg.vector_search.enabled = True
    cfg.sparse_search.enabled = True
    cfg.graph_search.enabled = False
    cfg.graph_indexing.enabled = False
    cfg.graph_indexing.build_lexical_graph = True
    cfg.chat.litellm.enabled = False
    cfg.semantic_cache.enabled = False
    cfg.chunking.chunking_strategy = "fixed_tokens"
    cfg.chunking.chunk_size = 200
    cfg.chunking.chunk_overlap = 0
    cfg.chunking.emit_chunk_ordinal = True
    for section in (cfg.retrieval, cfg.hydration):
        if hasattr(section, "neighbor_window"):
            section.neighbor_window = 1
    await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
    config_store._store = None


async def _search(client: AsyncClient, corpus_id: str, query: str) -> list[dict]:
    res = await client.post(
        "/api/search",
        json={
            "query": query,
            "corpus_id": corpus_id,
            "top_k": 12,
            "include_vector": True,
            "include_sparse": True,
            "include_graph": False,
            "cache_mode": "bypass",
        },
    )
    assert res.status_code == 200, res.text
    matches = res.json()["matches"]
    assert matches, res.text
    return matches


async def test_source_document_viewer_end_to_end(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"viewer-e2e-{uuid.uuid4().hex[:8]}"
    legacy_id = f"{corpus_id}-legacy"
    root = tmp_path / "corpus"
    _materialize_corpus(root)
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    try:
        await pg.connect()
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(root)}
        )
        assert created.status_code in (200, 201), created.text
        await _configure(pg, corpus_id)

        started = await client.post(
            "/api/index", json={"corpus_id": corpus_id, "repo_path": str(root), "force_reindex": True}
        )
        assert started.status_code == 200, started.text
        final = await _wait_for_index(client, corpus_id)
        assert final["status"] == "complete", final
        await _wait_fence_released(pg, corpus_id)

        # 1. Every enabled leg carries typed provenance; PDF hits map to real pages, text hits are direct.
        matches = await _search(client, corpus_id, "How often is the salinity array calibrated?")
        pdf_hits = [m for m in matches if m["file_path"] == PDF]
        md_hits = [m for m in matches if m["file_path"].endswith(".md")]
        assert pdf_hits and md_hits, [m["file_path"] for m in matches]
        for m in matches:
            assert m["provenance"] is not None, m["chunk_id"]
            assert "extraction" not in m["metadata"]
        salinity = next(m for m in pdf_hits if "salinity array" in m["content"].lower())
        prov = salinity["provenance"]
        assert prov["extraction"] == "docling" and prov["page_start"] == 1
        assert prov["regions"]
        for region in prov["regions"]:
            assert 0.0 <= region["left"] < region["right"] <= 1.0
            assert 0.0 <= region["top"] < region["bottom"] <= 1.0
        assert all(m["provenance"]["extraction"] == "direct" for m in md_hits)
        assert all(m["provenance"]["regions"] == [] for m in md_hits)

        # 2. A page-2 fact resolves to page 2 (the mapping is real, not always page 1).
        thermal = await _search(client, corpus_id, "When are thermal probes recalibrated?")
        page_two = [m for m in thermal if m["file_path"] == PDF and PAGE_TWO_SENTENCE.split(".")[0] in m["content"]]
        assert page_two, [m["content"][:60] for m in thermal]
        assert all(m["provenance"]["page_end"] == 2 for m in page_two)

        # 3. Every neighbor-expanded chunk in the fused vector/sparse results keeps provenance.
        neighbors = [m for m in matches + thermal if m["metadata"].get("neighbor_of")]
        assert all(m["provenance"] is not None for m in neighbors)

        # 5. Text view: exact decode, line count, captured + not stale.
        view = await client.get(f"/api/corpora/{corpus_id}/documents/view", params={"path": MD})
        assert view.status_code == 200, view.text
        body = view.json()
        md_bytes = (root / MD).read_bytes()
        assert body["content"]["kind"] == "text"
        assert body["content"]["text"] == md_bytes.decode("utf-8", errors="ignore")
        assert body["content"]["line_count"] == body["content"]["text"].count("\n") + 1
        assert body["provenance"]["state"] == "captured"
        assert body["provenance"]["stale"] is False
        assert body["provenance"]["sha256"] == hashlib.sha256(md_bytes).hexdigest()
        assert body["provenance"]["extraction"] == "direct"

        # 6. PDF view: live page sizes, no markdown stored.
        view = await client.get(f"/api/corpora/{corpus_id}/documents/view", params={"path": PDF})
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["content"] == {
            "kind": "pdf",
            "page_count": 2,
            "page_sizes": [{"width": 612.0, "height": 792.0}] * 2,
        }
        assert body["provenance"]["extraction"] == "docling"
        record = await pg.get_document(corpus_id, PDF)
        assert record is not None and record.markdown is None and record.kind == "pdf"

        # 7. Rich view: the Docling markdown captured at index time.
        view = await client.get(f"/api/corpora/{corpus_id}/documents/view", params={"path": HTML})
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["content"]["kind"] == "rich"
        assert "calibrated every 45 days" in body["content"]["markdown"]
        assert "|" in body["content"]["markdown"]

        # 8. Page render, ETag/304, thumb variant, out-of-range, non-PDF.
        page = await client.get(
            f"/api/corpora/{corpus_id}/documents/page", params={"path": PDF, "page": 1}
        )
        assert page.status_code == 200, page.text
        assert page.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(page.content)).size == (1224, 1584)
        etag = page.headers["etag"]
        again = await client.get(
            f"/api/corpora/{corpus_id}/documents/page",
            params={"path": PDF, "page": 1},
            headers={"If-None-Match": etag},
        )
        assert again.status_code == 304
        thumb = await client.get(
            f"/api/corpora/{corpus_id}/documents/page",
            params={"path": PDF, "page": 2, "variant": "thumb"},
        )
        assert thumb.status_code == 200 and thumb.headers["etag"] != etag
        assert Image.open(io.BytesIO(thumb.content)).size == (306, 396)
        assert (
            await client.get(
                f"/api/corpora/{corpus_id}/documents/page", params={"path": PDF, "page": 3}
            )
        ).status_code == 404
        assert (
            await client.get(
                f"/api/corpora/{corpus_id}/documents/page", params={"path": MD, "page": 1}
            )
        ).status_code == 415

        # 9. Raw bytes: PDF inline, everything else attachment + nosniff + sandbox.
        raw = await client.get(f"/api/corpora/{corpus_id}/documents/raw", params={"path": PDF})
        assert raw.status_code == 200 and raw.content == build_aurora_report_pdf()
        assert raw.headers["content-type"].startswith("application/pdf")
        assert raw.headers["content-disposition"].startswith("inline;")
        raw_html = await client.get(f"/api/corpora/{corpus_id}/documents/raw", params={"path": HTML})
        assert raw_html.status_code == 200
        assert raw_html.headers["content-disposition"].startswith("attachment;")
        assert raw_html.headers["x-content-type-options"] == "nosniff"
        assert raw_html.headers["content-security-policy"] == "sandbox"
        assert not raw_html.headers["content-type"].startswith("text/html")

        # 10. Path escapes, unindexed files, unknown corpus, bad corpus id.
        (root / "unindexed.txt").write_text("written after indexing")
        for bad in ("../../etc/passwd", "/etc/passwd", "unindexed.txt", "", "docs/../" + MD):
            res = await client.get(f"/api/corpora/{corpus_id}/documents/view", params={"path": bad})
            assert res.status_code == 404, (bad, res.status_code, res.text)
        assert (
            await client.get("/api/corpora/no-such-corpus/documents/view", params={"path": MD})
        ).status_code == 404
        assert (
            await client.get("/api/corpora/a%2Fb/documents/view", params={"path": MD})
        ).status_code in (400, 404)

        # 11. Staleness: the file on disk changed since indexing.
        (root / MD).write_text("# rewritten\n", encoding="utf-8")
        view = await client.get(f"/api/corpora/{corpus_id}/documents/view", params={"path": MD})
        assert view.status_code == 200 and view.json()["provenance"]["stale"] is True

        # 12. Re-index leaves documents only under the active id; delete clears them.
        again_idx = await client.post(
            "/api/index", json={"corpus_id": corpus_id, "repo_path": str(root), "force_reindex": True}
        )
        assert again_idx.status_code == 200, again_idx.text
        assert (await _wait_for_index(client, corpus_id))["status"] == "complete"
        await _wait_fence_released(pg, corpus_id)
        assert await pg.count_documents(corpus_id) >= 3
        assert await pg._pool.fetchval(  # type: ignore[union-attr]
            "SELECT count(*) FROM documents WHERE repo_id LIKE $1;", f"{STAGING_REPO_PREFIX}{corpus_id}%"
        ) == 0
        view = await client.get(f"/api/corpora/{corpus_id}/documents/view", params={"path": MD})
        assert view.json()["provenance"]["stale"] is False

        # 13. Pre-provenance corpus: chunks without provenance and no documents rows.
        created = await client.post(
            "/api/corpora", json={"corpus_id": legacy_id, "name": legacy_id, "path": str(root)}
        )
        assert created.status_code in (200, 201), created.text
        legacy_chunks = [
            Chunk(chunk_id=f"{name}:1-1:0", content="legacy", file_path=name, start_line=1, end_line=1)
            for name in (MD, PDF, HTML)
        ]
        await pg.upsert_chunks(legacy_id, legacy_chunks)
        for name in (MD, PDF):
            res = await client.get(f"/api/corpora/{legacy_id}/documents/view", params={"path": name})
            assert res.status_code == 200, res.text
            prov = res.json()["provenance"]
            assert prov["state"] == "not_captured" and legacy_id in prov["operator_hint"]
        res = await client.get(f"/api/corpora/{legacy_id}/documents/view", params={"path": HTML})
        assert res.status_code == 409, res.text
        assert res.json()["detail"]["code"] == "document_not_captured"
        page = await client.get(
            f"/api/corpora/{legacy_id}/documents/page", params={"path": PDF, "page": 1}
        )
        assert page.status_code == 200  # pages still render without provenance

        deleted = await client.delete(f"/api/corpora/{corpus_id}")
        assert deleted.status_code == 200, deleted.text
        assert await pg.count_documents(corpus_id) == 0
    finally:
        for rid in (corpus_id, legacy_id):
            try:
                await client.delete(f"/api/corpora/{rid}")
            except Exception:
                pass
            try:
                await pg.delete_corpus_with_data(rid)
            except Exception:
                pass
        await pg.disconnect()
