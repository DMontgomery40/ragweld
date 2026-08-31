"""Observability routes observe real traffic and fail closed on unknown corpora (no mocks).

Runs real queries against an indexed corpus, then reads /api/observability/status
and /incidents for that corpus and checks they describe what actually happened:
the retrieval component reports the live generation with its point count, the
request evidence carries the search route, no retrieval incident fires; wiping
the live Qdrant generation turns into a firing retrieval incident; an unknown
corpus is a 404 on status, catalog and incidents (never the global config).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.postgres import PostgresClient
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance_corpus"
_QUESTIONS = [
    "How often is the salinity sensor calibrated?",
    "What is the manual failover procedure for the tidal gateway?",
]


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 240.0) -> dict:
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


def _component(payload: dict, component_id: str) -> dict:
    for item in payload.get("components") or []:
        if item.get("id") == component_id:
            return item
    raise AssertionError(
        f"component {component_id} missing from {[c.get('id') for c in payload.get('components') or []]}"
    )


async def test_unknown_corpus_is_a_404_on_every_observability_route(client: AsyncClient) -> None:
    missing = f"missing-obs-{uuid.uuid4().hex[:8]}"
    for path in (
        "/api/observability/status",
        "/api/observability/catalog",
        "/api/observability/incidents",
        "/api/observability/alert-rules",
    ):
        res = await client.get(path, params={"corpus_id": missing})
        assert res.status_code == 404, (path, res.status_code, res.text[:200])
        assert missing in str(res.json().get("detail"))


async def test_status_and_incidents_reflect_real_queries_on_the_corpus(client: AsyncClient) -> None:
    corpus_id = f"obs-live-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    cfg = load_config()
    qdrant = QdrantChunkStore(cfg)
    try:
        await pg.connect()
        created = await client.post(
            "/api/corpora",
            json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)},
        )
        assert created.status_code in (200, 201), created.text
        cfg.embedding.embedding_backend = "deterministic"
        cfg.graph_indexing.semantic_kg_enabled = False
        cfg.reranking.reranker_mode = "none"
        cfg.chat.litellm.enabled = False
        cfg.semantic_cache.enabled = False
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None
        started = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True},
        )
        assert started.status_code == 200, started.text
        assert (await _wait_for_index(client, corpus_id))["status"] == "complete"
        chunk_rows = await pg.count_chunks(corpus_id)
        generation = await pg.get_generation(corpus_id)
        assert chunk_rows > 0 and generation and generation.qdrant_collection

        # Real queries first, then observe them.
        correlation_ids: list[str] = []  # observability run ids of the searches we make
        for question in _QUESTIONS:
            res = await client.post(
                "/api/search",
                json={
                    "query": question,
                    "corpus_id": corpus_id,
                    "top_k": 5,
                    "cache_mode": "bypass",
                },
            )
            assert res.status_code == 200, res.text
            assert res.json()["matches"], question
            # Every request carries its observability identity back to the caller.
            assert res.headers.get("X-Correlation-ID") and res.headers.get("X-Trace-ID"), dict(
                res.headers
            )
            correlation_ids.append(str(res.json()["debug"]["observability_run_id"]))

        status = await client.get("/api/observability/status", params={"corpus_id": corpus_id})
        assert status.status_code == 200, status.text
        status_payload = status.json()
        retrieval = _component(status_payload, "haystack_docling_qdrant")
        assert retrieval["reachable"] is True
        assert f"'{corpus_id}': {chunk_rows} points" in str(retrieval["detail"]), retrieval[
            "detail"
        ]
        assert generation.qdrant_collection in str(retrieval["detail"])
        assert status_payload["incident_count"] == status_payload[
            "critical_incident_count"
        ] == 0 or all(
            not str(i.get("id", "")).startswith("retrieval:")
            for i in (
                await client.get("/api/observability/incidents", params={"corpus_id": corpus_id})
            ).json()["incidents"]
        )
        incidents = await client.get(
            "/api/observability/incidents", params={"corpus_id": corpus_id}
        )
        assert incidents.status_code == 200, incidents.text
        assert not [i for i in incidents.json()["incidents"] if i["id"] == f"retrieval:{corpus_id}"]

        # The most recent search is the latest request evidence for this corpus:
        # the trace the observability surface links to is one of the runs above,
        # scoped to this corpus, and it recorded the question that was asked.
        latest = await client.get("/api/traces/latest", params={"corpus_id": corpus_id})
        assert latest.status_code == 200, latest.text
        trace_payload = latest.json()
        assert trace_payload["repo"] == corpus_id, trace_payload
        assert trace_payload["run_id"] in correlation_ids, (
            trace_payload["run_id"],
            correlation_ids,
        )
        trace = trace_payload["trace"]
        assert trace, "tracing must have captured the search run"
        recorded = str(trace)
        assert any(q in recorded for q in _QUESTIONS), "the trace must carry the asked question"

        # Wipe the live generation out from under the corpus: chunk rows exist,
        # vectors do not -> the retrieval incident fires and status reports it.
        await qdrant.drop_generation(generation.qdrant_collection)
        incidents = await client.get(
            "/api/observability/incidents", params={"corpus_id": corpus_id}
        )
        assert incidents.status_code == 200, incidents.text
        firing = [i for i in incidents.json()["incidents"] if i["id"] == f"retrieval:{corpus_id}"]
        assert firing and firing[0]["status"] == "firing" and firing[0]["severity"] == "critical", (
            incidents.text[:400]
        )
        status_after = await client.get(
            "/api/observability/status", params={"corpus_id": corpus_id}
        )
        assert status_after.status_code == 200
        assert status_after.json()["incident_count"] >= 1
        retrieval_after = _component(status_after.json(), "haystack_docling_qdrant")
        assert "empty or wiped" in str(retrieval_after["detail"]), retrieval_after["detail"]
        broken = await client.post(
            "/api/search",
            json={
                "query": _QUESTIONS[0],
                "corpus_id": corpus_id,
                "top_k": 5,
                "cache_mode": "bypass",
            },
        )
        assert broken.status_code == 503, (
            broken.text
        )  # required leg failed: fails closed, never an empty 200
        assert broken.json()["detail"]["code"] == "required_retrieval_leg_failed", broken.text
    finally:
        config_store._store = None
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        try:
            await pg.disconnect()
        except Exception:
            pass
