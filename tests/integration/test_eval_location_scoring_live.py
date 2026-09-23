"""A single-document corpus can fail an eval question once expectations carry a location.

Before chunk-level scoring, eval compared de-duplicated file paths: on a corpus with one
document every question scored top-1 = 100% and MRR = 1.0 however badly the chunks ranked
(the live nasa-apollo-11 eval did exactly that). This indexes a real one-file corpus on
Postgres/Qdrant/Neo4j (sparse retrieval, no embeddings, no reranker) and scores through the
real /api/eval/test route and the run core. Nothing is mocked.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.api.dataset import _dataset_path_for_corpus
from server.api.eval import _run_path as _eval_run_path
from server.api.eval import evaluate_dataset_entries
from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import EvalDatasetItem
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "single_document_corpus"
_DOC = "aurora-station-handbook.md"
RETENTION_QUESTION = "How long is raw hydrophone audio kept on the Aurora Station archive server before it is deleted?"


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 240.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        res = await client.get(f"/api/index/{corpus_id}/status")
        assert res.status_code == 200, res.text
        body = res.json()
        if body.get("status") in {"complete", "failed", "error", "cancelled"}:
            return body
        await asyncio.sleep(0.5)
    raise AssertionError("index did not finish")


def _chunk_containing(chunks: list[Chunk], phrase: str) -> Chunk:
    found = [ch for ch in chunks if phrase in ch.content]
    assert found, f"no chunk contains {phrase!r}"
    return found[0]


def _lines_of(chunk: Chunk) -> dict[str, object]:
    """The chunk's line span as an expected location, in wire form."""
    return {"path": _DOC, "unit": "line", "start": chunk.start_line, "end": chunk.end_line}


async def test_single_document_corpus_scores_a_miss_when_the_location_is_wrong(
    client: AsyncClient, tmp_path: Path
) -> None:
    corpus_id = f"pytest_eval_location_{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    persisted: list[Path] = []
    try:
        await pg.connect()
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)}
        )
        assert created.status_code in (200, 201), created.text

        cfg = load_config()
        cfg.embedding.embedding_backend = "deterministic"
        cfg.indexing.skip_dense = True  # sparse-only retrieval: a deterministic ranking
        cfg.vector_search.enabled = False
        cfg.sparse_search.enabled = True
        cfg.graph_search.enabled = False
        cfg.graph_indexing.enabled = False
        cfg.graph_indexing.build_lexical_graph = True
        cfg.chat.litellm.enabled = False
        cfg.semantic_cache.enabled = False
        cfg.reranking.reranker_mode = "none"
        cfg.evaluation.ragas_enabled = False
        cfg.chunking.chunking_strategy = "markdown"
        cfg.chunking.chunk_size = 300
        cfg.chunking.chunk_overlap = 0
        cfg.tracing.tribrid_log_path = str(tmp_path / "queries.jsonl")
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None

        started = await client.post(
            "/api/index", json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True}
        )
        assert started.status_code == 200, started.text
        final = await _wait_for_index(client, corpus_id)
        assert final["status"] == "complete", final

        chunks = await pg.list_chunks_for_repo(corpus_id)
        assert {ch.file_path for ch in chunks} == {_DOC}, "the corpus must hold exactly one document"
        assert len(chunks) >= 3, [(ch.start_line, ch.end_line) for ch in chunks]
        retention = _chunk_containing(chunks, "ninety days")
        radio = _chunk_containing(chunks, "VHF channel 16")
        assert radio.end_line < retention.start_line or radio.start_line > retention.end_line

        # The answer is in the Data Retention section; expecting the Radio Schedule lines instead
        # must score a miss. File-level scoring called this a top-1 hit (the only file matched).
        wrong = await client.post(
            "/api/eval/test",
            json={
                "corpus_id": corpus_id,
                "question": RETENTION_QUESTION,
                "expected_paths": [_DOC],
                "expected_locations": [_lines_of(radio)],
                "final_k": 1,
            },
        )
        assert wrong.status_code == 200, wrong.text
        wrong_body = wrong.json()
        assert wrong_body["docs"], "sparse retrieval must return the retention chunk"
        assert wrong_body["top1_hit"] is False, wrong_body
        assert wrong_body["topk_hit"] is False, wrong_body
        assert wrong_body["uninformative"] is False
        assert wrong_body["docs"][0]["match"] == "outside_location"

        right = await client.post(
            "/api/eval/test",
            json={
                "corpus_id": corpus_id,
                "question": RETENTION_QUESTION,
                "expected_paths": [_DOC],
                "expected_locations": [_lines_of(retention)],
                "final_k": 1,
            },
        )
        assert right.status_code == 200, right.text
        right_body = right.json()
        top = right_body["docs"][0]
        assert top["start_line"] <= retention.end_line and top["end_line"] >= retention.start_line, right_body
        assert right_body["top1_hit"] is True
        assert right_body["reciprocal_rank"] == 1.0
        assert top["match"] == "location"

        # Run core: the file-only row is uninformative and excluded; the two located rows are scored.
        run = await evaluate_dataset_entries(
            repo_id=corpus_id,
            dataset=[
                EvalDatasetItem.model_validate(
                    {"entry_id": entry_id, "question": RETENTION_QUESTION, "expected_paths": [_DOC], "expected_locations": locations}
                )
                for entry_id, locations in (
                    ("file_only", []),
                    ("located_right", [_lines_of(retention)]),
                    ("located_wrong", [_lines_of(radio)]),
                )
            ],
            persist_run=False,
        )
        by_id = {result.entry_id: result for result in run.results}
        assert run.total == 3
        assert run.uninformative_count == 1
        assert by_id["file_only"].uninformative is True
        assert by_id["located_right"].top1_hit is True
        assert by_id["located_wrong"].top1_hit is False
        assert (run.top1_hits, run.top1_accuracy) == (1, 0.5)
        assert run.metrics.map_at_5 is not None

        # The persisted POST /eval/run lifecycle (dataset -> run -> list -> get -> delete) carries
        # the typed locations in and the uninformative count out.
        for entry_id, locations in (("file_only", []), ("located_wrong", [_lines_of(radio)])):
            added = await client.post(
                f"/api/dataset?corpus_id={corpus_id}",
                json={
                    "entry_id": entry_id,
                    "question": RETENTION_QUESTION,
                    "expected_paths": [_DOC],
                    "expected_locations": locations,
                },
            )
            assert added.status_code == 200, added.text
        ran = await client.post("/api/eval/run", json={"corpus_id": corpus_id})
        assert ran.status_code == 200, ran.text
        body = ran.json()
        run_id = body["run_id"]
        persisted.append(_eval_run_path(run_id))
        assert (body["total"], body["uninformative_count"], body["top1_hits"], body["top1_accuracy"]) == (2, 1, 0, 0.0)

        listed = await client.get("/api/eval/runs", params={"corpus_id": corpus_id})
        assert listed.status_code == 200, listed.text
        meta = listed.json()["runs"][0]
        assert (meta["run_id"], meta["total"], meta["uninformative_count"]) == (run_id, 2, 1)

        fetched = await client.get(f"/api/eval/run/{run_id}")
        assert fetched.status_code == 200, fetched.text
        by_entry = {r["entry_id"]: r for r in fetched.json()["results"]}
        assert by_entry["file_only"]["uninformative"] is True
        assert by_entry["located_wrong"]["expected_locations"] == [_lines_of(radio)]
        assert by_entry["located_wrong"]["docs"][0]["match"] == "outside_location"

        deleted = await client.delete(f"/api/eval/run/{run_id}")
        assert deleted.status_code == 200, deleted.text
        assert (await client.get(f"/api/eval/run/{run_id}")).status_code == 404
    finally:
        for path in persisted:
            path.unlink(missing_ok=True)
        _dataset_path_for_corpus(corpus_id).unlink(missing_ok=True)
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        await pg.disconnect()
