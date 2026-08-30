from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_stateful_api_openapi_documents_typed_dependency_503() -> None:
    from server.main import app

    schema = app.openapi()
    operations = {
        ("/api/corpora", "get"): {"DependencyUnavailableResponse"},
        ("/api/search", "post"): {
            "DependencyUnavailableResponse",
            "RequiredRetrievalLegFailureResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/answer", "post"): {
            "DependencyUnavailableResponse",
            "RequiredRetrievalLegFailureResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/chat", "post"): {
            "DependencyUnavailableResponse",
            "GenerationUnavailableResponse",
            "RequiredRetrievalLegFailureResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/chat/stream", "post"): {
            "DependencyUnavailableResponse",
            "RequiredRetrievalLegFailureResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/mcp/probe", "post"): {
            "DependencyUnavailableResponse",
            "RequiredRetrievalLegFailureResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/index", "post"): {
            "DependencyUnavailableResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/index/{corpus_id}/status", "get"): {
            "DependencyUnavailableResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/index/{corpus_id}/stats", "get"): {
            "DependencyUnavailableResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/index/{corpus_id}", "delete"): {
            "DependencyUnavailableResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/config", "get"): {"DependencyUnavailableResponse"},
        ("/api/feedback", "post"): {"DependencyUnavailableResponse"},
        ("/api/reranker/click", "post"): {"DependencyUnavailableResponse"},
        ("/api/graph/{corpus_id}/stats", "get"): {
            "DependencyUnavailableResponse",
            "IndexDeletionIncompleteResponse",
        },
        ("/api/lineage/current", "get"): {"DependencyUnavailableResponse"},
    }
    for (path, method), expected_models in operations.items():
        response = schema["paths"][path][method]["responses"]["503"]
        detail_schema = response["content"]["application/json"]["schema"]
        refs = (
            [detail_schema["$ref"]]
            if "$ref" in detail_schema
            else [item["$ref"] for item in detail_schema.get("anyOf", [])]
        )
        assert {ref.rsplit("/", 1)[-1] for ref in refs} == expected_models


def test_index_start_409_is_the_discriminated_fence_union() -> None:
    from server.main import app

    schema = app.openapi()
    response = schema["paths"]["/api/index"]["post"]["responses"]["409"]
    body = response["content"]["application/json"]["schema"]
    refs = [body["$ref"]] if "$ref" in body else [item["$ref"] for item in body.get("anyOf", [])]
    assert {r.rsplit("/", 1)[-1] for r in refs} == {
        "IndexRunConflictResponse",
        "PersistedStateCorruptResponse",
        # Starting a run also refuses an unusable indexing.figures.vision_model with a 409.
        "FigureRouteConflictResponse",
    }, body
    for path, method in (
        ("/api/index/{corpus_id}/status", "get"),
        ("/api/index/{corpus_id}/stats", "get"),
        ("/api/index/{corpus_id}/runs/latest", "get"),
        ("/api/index/{corpus_id}", "delete"),
        ("/api/index/status", "get"),
        ("/api/index/stats", "get"),
    ):
        conflict = schema["paths"][path][method]["responses"]["409"]["content"]["application/json"][
            "schema"
        ]
        conflict_refs = (
            [conflict["$ref"]]
            if "$ref" in conflict
            else [item["$ref"] for item in conflict.get("anyOf", [])]
        )
        assert {r.rsplit("/", 1)[-1] for r in conflict_refs} == {
            "IndexRunConflictResponse",
            "PersistedStateCorruptResponse",
        }, (path, conflict)
    detail = schema["components"]["schemas"]["IndexRunConflictResponse"]["properties"]["detail"]
    mapping = detail.get("discriminator", {}).get("mapping", {})
    assert set(mapping) == {"index_run_in_progress", "index_fence_corrupt"}, detail
    assert {v.rsplit("/", 1)[-1] for v in mapping.values()} == {
        "IndexRunConflictDetail",
        "IndexFenceCorruptDetail",
    }


def test_postgres_outage_returns_structured_503_across_stateful_api_families(
    tmp_path: Path,
) -> None:
    config = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    config["indexing"]["postgres_url"] = "postgresql://postgres:postgres@127.0.0.1:1/ragweld_outage"
    (tmp_path / "tribrid_config.json").write_text(json.dumps(config), encoding="utf-8")

    script = """
import asyncio
import json
from httpx import ASGITransport, AsyncClient
from server.main import app

REQUESTS = [
    ("GET", "/api/repos", None),
    ("GET", "/api/corpora", None),
    ("POST", "/api/search", {"query": "How often is the Aurora salinity sensor array calibrated?", "repo_id": "missing", "include_vector": False, "include_sparse": False, "include_graph": False}),
    ("POST", "/api/answer", {"query": "How often is the Aurora salinity sensor array calibrated?", "repo_id": "missing", "include_vector": False, "include_sparse": False, "include_graph": False}),
    ("POST", "/api/answer/stream", {"query": "How often is the Aurora salinity sensor array calibrated?", "repo_id": "missing", "include_vector": False, "include_sparse": False, "include_graph": False}),
    ("POST", "/api/chat", {"message": "How often is the Aurora salinity sensor array calibrated?", "sources": {"corpus_ids": ["missing"]}, "include_vector": False, "include_sparse": False, "include_graph": False}),
    ("POST", "/api/chat/stream", {"message": "How often is the Aurora salinity sensor array calibrated?", "sources": {"corpus_ids": ["missing"]}, "include_vector": False, "include_sparse": False, "include_graph": False}),
    ("POST", "/api/mcp/probe?corpus_id=missing", {"question": "How often is the Aurora salinity sensor array calibrated?"}),
    ("GET", "/api/config?corpus_id=missing", None),
    ("GET", "/api/config/validate?corpus_id=missing", None),
    ("GET", "/api/graph/missing/stats", None),
    ("GET", "/api/lineage/current?corpus_id=missing", None),
    ("POST", "/api/feedback?corpus_id=missing", {"event_id": "outage-test", "signal": "thumbsup"}),
    ("POST", "/api/reranker/click?corpus_id=missing", {"event_id": "outage-click", "doc_id": "missing.md"}),
    ("POST", "/api/reranker/mine?corpus_id=missing", None),
    ("POST", "/api/synthetic/run/start", {"corpus_id": "missing", "provider": "grounded_qa", "recipe": "eval_dataset", "generator_model": "litellm:openai.gpt-5.6-luna", "judge_model": "litellm:openai.gpt-5.6-luna"}),
    ("GET", "/api/corpora/missing/documents/view?path=notes.md", None),
    ("GET", "/api/corpora/missing/documents/page?path=report.pdf&page=1", None),
    ("GET", "/api/corpora/missing/documents/raw?path=notes.md", None),
]

async def main():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    rows = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path, body in REQUESTS:
            response = await client.request(method, path, json=body)
            try:
                payload = response.json()
            except Exception:
                payload = {"raw": response.text}
            rows.append({"method": method, "path": path, "status": response.status_code, "body": payload})
    print(json.dumps(rows))

asyncio.run(main())
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["RAGWELD_LOAD_DOTENV"] = "0"
    env["RAGWELD_CONFIG_PATH"] = str(tmp_path / "tribrid_config.json")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    rows = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(rows) == 19
    for row in rows:
        assert row["status"] == 503, row
        detail = row["body"].get("detail")
        assert isinstance(detail, dict), row
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "postgres"
        assert detail["operation"]
        assert detail["retryable"] is True
        assert "operator_hint" in detail
        assert "127.0.0.1:1" not in json.dumps(row["body"])


def test_chat_generation_failure_returns_typed_sanitized_503(tmp_path: Path) -> None:
    runtime_config = tmp_path / "tribrid_config.json"
    runtime_config.write_bytes((ROOT / "tribrid_config.json").read_bytes())
    script = """
import asyncio
import json
from httpx import ASGITransport, AsyncClient
from server.main import app

async def main():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"message": "How often is the Aurora salinity sensor array calibrated?", "sources": {"corpus_ids": []}},
        )
    print(json.dumps({"status": response.status_code, "body": response.json()}))

asyncio.run(main())
"""
    env = dict(os.environ)
    env.pop("LITELLM_API_KEY", None)
    env["PYTHONPATH"] = str(ROOT)
    env["RAGWELD_LOAD_DOTENV"] = "0"
    env["RAGWELD_CONFIG_PATH"] = str(runtime_config)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == 503
    detail = payload["body"]["detail"]
    assert detail["code"] == "generation_unavailable"
    assert detail["operation"] == "Chat generation"
    assert detail["retryable"] is True
    assert detail["operator_hint"]
    assert "LITELLM_API_KEY" not in json.dumps(payload["body"])


def test_readiness_is_503_and_sanitized_when_required_dependencies_are_unavailable(
    tmp_path: Path,
) -> None:
    config = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    config["indexing"]["postgres_url"] = "postgresql://postgres:secret@127.0.0.1:1/ragweld_outage"
    config["graph_storage"]["neo4j_uri"] = "bolt://127.0.0.1:1"
    (tmp_path / "tribrid_config.json").write_text(json.dumps(config), encoding="utf-8")

    script = """
import asyncio
import json
from httpx import ASGITransport, AsyncClient
from server.main import app

async def main():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/health")
        ready = await client.get("/api/ready")
    print(json.dumps({"health": [health.status_code, health.json()], "ready": [ready.status_code, ready.json()]}))

asyncio.run(main())
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["RAGWELD_LOAD_DOTENV"] = "0"
    env["RAGWELD_CONFIG_PATH"] = str(tmp_path / "tribrid_config.json")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["health"][0] == 200
    assert payload["ready"][0] == 503
    assert payload["ready"][1]["ready"] is False
    assert payload["ready"][1]["dependencies"]["postgres"]["ok"] is False
    assert payload["ready"][1]["dependencies"]["neo4j"]["ok"] is False
    serialized = json.dumps(payload["ready"][1])
    assert "127.0.0.1:1" not in serialized
    assert "secret" not in serialized


def test_corpus_delete_409_names_the_run_that_holds_the_corpus() -> None:
    """A 409 that only says "a run holds this" is not actionable.

    Deleting a corpus while an index run holds its fence is refused, and the operator's next
    move depends entirely on which run that is and what it is doing: a run converting a
    scanned PDF has to be waited out, a run queued behind the document extractor points at a
    third corpus, and a run whose lease has lapsed is taken over on its own. The detail
    therefore carries the run id, when it started, its fence phase and the last thing it
    reported doing.

    Both delete routes must document the envelope: the operator UI calls `/api/corpora/{id}`,
    while `/api/repos/{id}` is the same handler under its older path.
    """
    from server.main import app

    schema = app.openapi()
    for path in ("/api/repos/{corpus_id}", "/api/corpora/{corpus_id}"):
        body = schema["paths"][path]["delete"]["responses"]["409"]["content"]["application/json"][
            "schema"
        ]
        refs = (
            [body["$ref"]] if "$ref" in body else [item["$ref"] for item in body.get("anyOf", [])]
        )
        assert {r.rsplit("/", 1)[-1] for r in refs} == {"IndexRunConflictResponse"}, (path, body)

    properties = schema["components"]["schemas"]["IndexRunConflictDetail"]["properties"]
    for field in ("run_id", "started_at", "phase", "stage"):
        assert field in properties, sorted(properties)
        assert properties[field].get("description"), field


def test_the_fence_conflict_detail_reports_what_the_holding_run_is_doing(tmp_path: Path) -> None:
    """The stage comes off the holding run's real log, not a guess about its fence."""
    import asyncio
    from datetime import UTC, datetime

    import server.api.index as index_api
    from server.api.index import _append_run_event, _flush_run_events_sync, index_run_conflict
    from server.indexing.generations import IndexRunFence
    from server.models.index import IndexRunConflictDetail

    started = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)
    fence = IndexRunFence(
        run_id="7be21c04-2f9a-4a1b-9f0e-1d2c3b4a5e6f",
        owner="ragweld:4711",
        started_at=started,
        heartbeat_at=datetime(2026, 8, 30, 9, 41, tzinfo=UTC),
        phase="building",
    )
    old_runs_dir = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        _append_run_event(
            "nasa-apollo-11",
            fence.run_id,
            {
                "type": "log",
                "message": "Converting apollo-11-mission-report.pdf: still running (600s elapsed)",
            },
        )
        # The reader never drains the writer itself -- joining a live run's write queue has
        # no bounded completion, so a 409 must not wait on it. This test is the controlled
        # single-writer case, so it flushes here instead.
        _flush_run_events_sync()
        conflict = asyncio.run(
            index_run_conflict("nasa-apollo-11", fence, operator_hint="Stop that index run.")
        )
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir

    assert conflict.status_code == 409
    detail = IndexRunConflictDetail.model_validate(conflict.detail)
    assert detail.run_id == fence.run_id
    assert detail.started_at == started
    assert detail.phase == "building"
    assert detail.stage == "Converting apollo-11-mission-report.pdf: still running (600s elapsed)"
    assert detail.operator_hint == "Stop that index run."


def test_the_fence_conflict_detail_reports_no_stage_for_a_run_that_logged_nothing(
    tmp_path: Path,
) -> None:
    """A run with an empty log gets a null stage, never an invented one."""
    import asyncio
    from datetime import UTC, datetime

    import server.api.index as index_api
    from server.api.index import index_run_conflict
    from server.indexing.generations import IndexRunFence
    from server.models.index import IndexRunConflictDetail

    fence = IndexRunFence(
        run_id="0d3f9a71-1111-2222-3333-444455556666",
        owner="ragweld:4711",
        started_at=datetime(2026, 8, 30, 9, 15, tzinfo=UTC),
        heartbeat_at=datetime(2026, 8, 30, 9, 15, tzinfo=UTC),
        phase="retiring",
    )
    old_runs_dir = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        conflict = asyncio.run(index_run_conflict("nasa-apollo-11", fence))
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir

    detail = IndexRunConflictDetail.model_validate(conflict.detail)
    assert detail.stage is None
    assert detail.phase == "retiring"
    assert "index_run_lease_seconds" in detail.operator_hint


def test_the_conflict_stage_reads_only_events_that_describe_a_stage(tmp_path: Path) -> None:
    """A warning is about a file that was skipped, not about what the run is doing now.

    Also drives the bounded tail read past a log far longer than the window it inspects: the
    stage has to come off the end of a long-running run's log without parsing all of it.
    """
    import asyncio
    from datetime import UTC, datetime

    import server.api.index as index_api
    from server.api.index import _append_run_event, _flush_run_events_sync, index_run_conflict
    from server.indexing.generations import IndexRunFence
    from server.models.index import IndexRunConflictDetail

    fence = IndexRunFence(
        run_id="7be21c04-2f9a-4a1b-9f0e-1d2c3b4a5e6f",
        owner="ragweld:4711",
        started_at=datetime(2026, 8, 30, 9, 15, tzinfo=UTC),
        heartbeat_at=datetime(2026, 8, 30, 9, 41, tzinfo=UTC),
    )
    old_runs_dir = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        for ordinal in range(400):
            _append_run_event(
                "nasa-apollo-11",
                fence.run_id,
                {"type": "log", "message": f"Indexed file {ordinal}"},
            )
        _append_run_event(
            "nasa-apollo-11",
            fence.run_id,
            {
                "type": "progress",
                "message": "Converting apollo-11.pdf: still running (600s elapsed)",
            },
        )
        # Last line in the log, and not a stage: the run kept going past it.
        _append_run_event(
            "nasa-apollo-11",
            fence.run_id,
            {"type": "warning", "message": "Skipping file due to read/extract failure: junk.bin"},
        )
        _flush_run_events_sync()
        conflict = asyncio.run(index_run_conflict("nasa-apollo-11", fence))
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir

    detail = IndexRunConflictDetail.model_validate(conflict.detail)
    assert detail.stage == "Converting apollo-11.pdf: still running (600s elapsed)"


def test_the_conflict_stage_is_capped_at_the_field_length(tmp_path: Path) -> None:
    """The run log is not a length-checked surface, so the reader has to cap what it lifts.

    `stage` declares `max_length=200`; without the cap an over-long message would fail the
    detail's own validation and turn a 409 into a 500.
    """
    import asyncio
    from datetime import UTC, datetime

    import server.api.index as index_api
    from server.api.index import _append_run_event, _flush_run_events_sync, index_run_conflict
    from server.indexing.generations import IndexRunFence
    from server.models.index import IndexRunConflictDetail

    long_message = "Converting " + ("deeply-nested-" * 40) + "report.pdf"
    assert len(long_message) > 200
    fence = IndexRunFence(
        run_id="0d3f9a71-1111-2222-3333-444455556666",
        owner="ragweld:4711",
        started_at=datetime(2026, 8, 30, 9, 15, tzinfo=UTC),
        heartbeat_at=datetime(2026, 8, 30, 9, 15, tzinfo=UTC),
    )
    old_runs_dir = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        _append_run_event("nasa-apollo-11", fence.run_id, {"type": "log", "message": long_message})
        _flush_run_events_sync()
        conflict = asyncio.run(index_run_conflict("nasa-apollo-11", fence))
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir

    detail = IndexRunConflictDetail.model_validate(conflict.detail)
    assert detail.stage == long_message[:200]
    assert len(detail.stage or "") == 200
