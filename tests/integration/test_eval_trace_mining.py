"""SSE eval -> persisted trace with answer provenance -> trace-mined triplets, on a real index.

The Eval Analysis UI evaluates through the SSE route; its persisted results must carry
`expected_answer` so `POST /api/reranker/mine` can reject candidate negatives that
contain the answer. Real Postgres/Neo4j/Qdrant, deterministic embeddings, no mocks.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.api.dataset import _dataset_path_for_corpus
from server.api.eval import _EVAL_STATUS
from server.api.eval import _run_path as _eval_run_path
from server.config import load_config
from server.db.postgres import PostgresClient
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance_corpus"
CALIBRATION_QUESTION = "How often is the salinity sensor array on each Aurora buoy calibrated?"
CALIBRATION_ANSWER = "every 45 days"
STANDARD_QUESTION = "Which sealed calibration standard is produced on station for the salinity sensors?"
STANDARD_ANSWER = "Halcyon reference brine"


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 240.0) -> dict:
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        res = await client.get(f"/api/index/{corpus_id}/status")
        assert res.status_code == 200, res.text
        body = res.json()
        if body.get("status") in {"complete", "failed", "error", "cancelled"}:
            return body
        await asyncio.sleep(0.5)
    raise AssertionError("index did not finish")


async def test_sse_eval_persists_answer_provenance_and_mining_rejects_answer_leaking_negatives(
    client: AsyncClient, tmp_path: Path
) -> None:
    corpus_id = f"eval-trace-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    persisted: list[Path] = []
    triplets_path = tmp_path / "triplets.jsonl"
    status_before = dict(_EVAL_STATUS)
    try:
        await pg.connect()
        created = await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)})
        assert created.status_code in (200, 201), created.text

        cfg = load_config()
        cfg.embedding.embedding_backend = "deterministic"
        cfg.vector_search.enabled = True
        cfg.sparse_search.enabled = True
        cfg.graph_search.enabled = True
        cfg.graph_search.mode = "chunk"
        cfg.graph_indexing.enabled = True
        cfg.graph_indexing.build_lexical_graph = True
        cfg.graph_indexing.store_chunk_embeddings = True
        cfg.graph_indexing.semantic_kg_enabled = False
        cfg.chat.litellm.enabled = False
        cfg.semantic_cache.enabled = 0
        cfg.reranking.reranker_mode = "none"
        cfg.tracing.tribrid_log_path = str(tmp_path / "queries.jsonl")
        cfg.training.tribrid_triplets_path = str(triplets_path)
        cfg.training.learning_reranker_negative_ratio = 3
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None

        started = await client.post("/api/index", json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True})
        assert started.status_code == 200, started.text
        final = await _wait_for_index(client, corpus_id)
        assert final["status"] == "complete", final

        for entry_id, question, answer in (
            ("calibration", CALIBRATION_QUESTION, CALIBRATION_ANSWER),
            ("standard", STANDARD_QUESTION, STANDARD_ANSWER),
        ):
            added = await client.post(
                f"/api/dataset?corpus_id={corpus_id}",
                json={"entry_id": entry_id, "question": question, "expected_paths": ["sensor-calibration.md"], "expected_answer": answer},
            )
            assert added.status_code == 200, added.text

        async with client.stream("GET", f"/api/eval/run/stream?corpus_id={corpus_id}") as response:
            assert response.status_code == 200
            body = (await response.aread()).decode("utf-8")
        saved = [json.loads(line[6:])["message"] for line in body.splitlines() if line.startswith("data: ") and "Results saved:" in line]
        assert saved, body[-1200:]
        run_id = saved[0].split("Results saved:", 1)[1].strip()
        persisted.append(_eval_run_path(run_id))

        run = await client.get(f"/api/eval/run/{run_id}")
        assert run.status_code == 200, run.text
        results = {r["entry_id"]: r for r in run.json()["results"]}
        assert set(results) == {"calibration", "standard"}
        assert results["calibration"]["expected_answer"] == CALIBRATION_ANSWER
        assert results["standard"]["expected_answer"] == STANDARD_ANSWER
        retrieved_by_question = {
            CALIBRATION_QUESTION: list(results["calibration"]["retrieved_paths"]),
            STANDARD_QUESTION: list(results["standard"]["retrieved_paths"]),
        }
        for question, retrieved in retrieved_by_question.items():
            assert retrieved, f"the real index must retrieve something for {question!r}"
            assert "sensor-calibration.md" in retrieved, (question, retrieved)

        mined = await client.post(f"/api/reranker/mine?corpus_id={corpus_id}&eval_run_id={run_id}")
        assert mined.status_code == 200, mined.text
        payload = mined.json()
        assert payload["eval_run_id"] == run_id
        assert payload["entries_without_answer_provenance"] == 0
        rows = [json.loads(ln) for ln in triplets_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert payload["triplets_mined"] == len(rows)
        assert payload["triplets_from_eval_run"] == len(rows) > 0, payload
        assert payload["negatives_rejected_unverifiable"] == 0, payload
        assert {row["query"] for row in rows} == set(retrieved_by_question), payload
        answers = {CALIBRATION_QUESTION: CALIBRATION_ANSWER, STANDARD_QUESTION: STANDARD_ANSWER}
        for row in rows:
            # positive = the expected document as it was retrieved; negative = a document this
            # very question retrieved (not invented from the corpus), that is not expected and
            # does not contain the answer.
            assert row["positive"] == "sensor-calibration.md"
            assert row["negative"] != "sensor-calibration.md"
            assert row["negative"] in retrieved_by_question[row["query"]], (row, retrieved_by_question[row["query"]])
            text = (_CORPUS_PATH / row["negative"]).read_text(encoding="utf-8").casefold()
            assert answers[row["query"]].casefold() not in text
        # Every retrieved non-expected document without the answer became a negative (up to the ratio cap).
        for question, retrieved in retrieved_by_question.items():
            eligible = list(
                dict.fromkeys(  # first retrieval rank wins; a file retrieved through several chunks is one candidate
                    path
                    for path in retrieved
                    if path != "sensor-calibration.md"
                    and answers[question].casefold() not in (_CORPUS_PATH / path).read_text(encoding="utf-8").casefold()
                )
            )
            mined_negatives = [row["negative"] for row in rows if row["query"] == question]
            assert mined_negatives == eligible[: len(mined_negatives)], (question, eligible, mined_negatives)
            assert len(mined_negatives) == min(len(eligible), 3), (question, eligible, mined_negatives)
    finally:
        for path in persisted:
            path.unlink(missing_ok=True)
        _dataset_path_for_corpus(corpus_id).unlink(missing_ok=True)
        deleted_index = await client.delete(f"/api/index/{corpus_id}")
        deleted_corpus = await client.delete(f"/api/corpora/{corpus_id}")
        await pg.disconnect()
        _EVAL_STATUS.clear()
        _EVAL_STATUS.update(status_before)
        assert deleted_index.status_code == 200, deleted_index.text
        assert deleted_corpus.status_code in (200, 204), deleted_corpus.text
