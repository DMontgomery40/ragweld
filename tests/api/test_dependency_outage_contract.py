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
        ("/api/index", "post"): {"DependencyUnavailableResponse", "IndexDeletionIncompleteResponse"},
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
        refs = [detail_schema["$ref"]] if "$ref" in detail_schema else [
            item["$ref"] for item in detail_schema.get("anyOf", [])
        ]
        assert {ref.rsplit("/", 1)[-1] for ref in refs} == expected_models


def test_index_start_409_is_the_discriminated_fence_union() -> None:
    from server.main import app

    schema = app.openapi()
    response = schema["paths"]["/api/index"]["post"]["responses"]["409"]
    ref = response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    assert ref == "IndexRunConflictResponse"
    detail = schema["components"]["schemas"]["IndexRunConflictResponse"]["properties"]["detail"]
    mapping = detail.get("discriminator", {}).get("mapping", {})
    assert set(mapping) == {"index_run_in_progress", "index_fence_corrupt"}, detail
    assert {v.rsplit("/", 1)[-1] for v in mapping.values()} == {
        "IndexRunConflictDetail",
        "IndexFenceCorruptDetail",
    }


def test_postgres_outage_returns_structured_503_across_stateful_api_families(tmp_path: Path) -> None:
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
    assert len(rows) == 16
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


def test_readiness_is_503_and_sanitized_when_required_dependencies_are_unavailable(tmp_path: Path) -> None:
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
