"""Tests for health endpoints."""

import http.server
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from server.main import app


@contextmanager
def _models_server(payload: dict[str, object]) -> Iterator[str]:
    class _ModelsHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ModelsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_health_endpoint_returns_pydantic_shape(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["status"] in {"healthy", "unhealthy", "unknown"}
    assert "ts" in data
    assert isinstance(data.get("services"), dict)
    assert data["services"]["api"]["status"] == "up"


@pytest.mark.asyncio
async def test_ready_reports_gateway_and_serving_failures_separately(client: AsyncClient) -> None:
    old_litellm = os.environ.get("LITELLM_BASE_URL")
    old_vllm = os.environ.get("VLLM_BASE_URL")
    os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:1/v1"
    try:
        response = await client.get("/api/ready")
    finally:
        if old_litellm is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = old_litellm
        if old_vllm is None:
            os.environ.pop("VLLM_BASE_URL", None)
        else:
            os.environ["VLLM_BASE_URL"] = old_vllm

    assert response.status_code == 503
    dependencies = response.json()["dependencies"]
    assert dependencies["litellm"]["ok"] is False
    assert dependencies["vllm"]["ok"] is False
    assert "operator_hint" in dependencies["litellm"]
    assert "operator_hint" in dependencies["vllm"]


@pytest.mark.asyncio
async def test_ready_reports_disabled_vllm_dependency_when_other_readiness_checks_are_pending(
    client: AsyncClient,
) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    config = baseline.json()
    config["chat"]["vllm"]["enabled"] = False
    saved = await client.put("/api/config", json=config)
    assert saved.status_code == 200

    litellm_payload = {"object": "list", "data": [{"id": "gpt-5.4-mini", "object": "model"}]}
    old_litellm = os.environ.get("LITELLM_BASE_URL")
    old_vllm = os.environ.get("VLLM_BASE_URL")
    with _models_server(litellm_payload) as litellm_url:
        os.environ["LITELLM_BASE_URL"] = litellm_url
        os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:1/v1"
        try:
            response = await client.get("/api/ready")
        finally:
            if old_litellm is None:
                os.environ.pop("LITELLM_BASE_URL", None)
            else:
                os.environ["LITELLM_BASE_URL"] = old_litellm
            if old_vllm is None:
                os.environ.pop("VLLM_BASE_URL", None)
            else:
                os.environ["VLLM_BASE_URL"] = old_vllm

    dependency = response.json()["dependencies"]["vllm"]
    assert dependency["ok"] is True
    assert dependency["error"] is None
    assert dependency["operator_hint"] is None
    assert dependency["info"] == {
        "status": "disabled by configuration",
        "required": False,
    }


@pytest.mark.requires_postgres
@pytest.mark.requires_neo4j
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
async def test_ready_marks_configured_disabled_vllm_nonblocking() -> None:
    litellm_payload = {"object": "list", "data": [{"id": "gpt-5.4-mini", "object": "model"}]}
    old_litellm = os.environ.get("LITELLM_BASE_URL")
    old_vllm = os.environ.get("VLLM_BASE_URL")
    with _models_server(litellm_payload) as litellm_url:
        os.environ["LITELLM_BASE_URL"] = litellm_url
        os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:1/v1"
        try:
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    baseline = await client.get("/api/config")
                    assert baseline.status_code == 200
                    config = baseline.json()
                    config["chat"]["vllm"]["enabled"] = False
                    saved = await client.put("/api/config", json=config)
                    assert saved.status_code == 200

                    response = await client.get("/api/ready")
        finally:
            if old_litellm is None:
                os.environ.pop("LITELLM_BASE_URL", None)
            else:
                os.environ["LITELLM_BASE_URL"] = old_litellm
            if old_vllm is None:
                os.environ.pop("VLLM_BASE_URL", None)
            else:
                os.environ["VLLM_BASE_URL"] = old_vllm

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    dependency = payload["dependencies"]["vllm"]
    assert dependency["ok"] is True
    assert dependency["error"] is None
    assert dependency["operator_hint"] is None
    assert dependency["info"] == {
        "status": "disabled by configuration",
        "required": False,
    }


@pytest.mark.requires_postgres
@pytest.mark.requires_neo4j
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
async def test_ready_marks_configured_enabled_vllm_blocking_when_unreachable() -> None:
    litellm_payload = {"object": "list", "data": [{"id": "gpt-5.4-mini", "object": "model"}]}
    old_litellm = os.environ.get("LITELLM_BASE_URL")
    old_vllm = os.environ.get("VLLM_BASE_URL")
    with _models_server(litellm_payload) as litellm_url:
        os.environ["LITELLM_BASE_URL"] = litellm_url
        os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:1/v1"
        try:
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    baseline = await client.get("/api/config")
                    assert baseline.status_code == 200
                    config = baseline.json()
                    config["chat"]["vllm"]["enabled"] = True
                    saved = await client.put("/api/config", json=config)
                    assert saved.status_code == 200

                    response = await client.get("/api/ready")
        finally:
            if old_litellm is None:
                os.environ.pop("LITELLM_BASE_URL", None)
            else:
                os.environ["LITELLM_BASE_URL"] = old_litellm
            if old_vllm is None:
                os.environ.pop("VLLM_BASE_URL", None)
            else:
                os.environ["VLLM_BASE_URL"] = old_vllm

    assert response.status_code == 503
    payload = response.json()
    assert payload["ready"] is False
    dependency = payload["dependencies"]["vllm"]
    assert dependency["ok"] is False
    assert dependency["error"] == "vLLM model serving is unavailable."
    assert dependency["operator_hint"] is not None


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_ready_unknown_corpus_reports_not_ready(client: AsyncClient) -> None:
    """A missing requested corpus is a truthful 503 readiness failure, not a crash."""
    corpora = await client.get("/api/corpora")
    assert corpora.status_code == 200
    existing_ids = {
        (c.get("corpus_id") or c.get("repo_id"))
        for c in corpora.json()
        if isinstance(c, dict)
    }

    missing_id = "does_not_exist_corpus__ready"
    assert missing_id not in existing_ids

    resp = await client.get("/api/ready", params={"corpus_id": missing_id})
    assert resp.status_code == 503
    payload = resp.json()
    assert payload["ready"] is False
    assert payload["corpus_id"] == missing_id
    assert payload["corpus_error"] == f"Corpus not found: {missing_id}"
    assert payload["dependencies"]["postgres"]["ok"] is True

    data = resp.json()
    assert data.get("corpus_id") == missing_id
    assert data.get("ready") is False
    assert "corpus_error" in data
    assert "Corpus not found" in str(data.get("corpus_error"))


@pytest.mark.asyncio
async def test_ready_fails_closed_when_the_local_server_serves_the_wrong_model(client: AsyncClient) -> None:
    """A listener on the vLLM URL is not enough: the served identity must match.

    A real throwaway HTTP server answers /v1/models with a stale model card; the
    readiness probe must refuse it with the serving-mismatch reason instead of
    reporting the dependency healthy.
    """
    import http.server
    import json as _json
    import threading

    stale_card = {
        "object": "list",
        "data": [{"id": "ragweld-local", "object": "model", "root": "Qwen/stale-model", "max_model_len": 2048}],
    }

    class _StaleModelHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            body = _json.dumps(stale_card).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StaleModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old_vllm = os.environ.get("VLLM_BASE_URL")
    os.environ["VLLM_BASE_URL"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
    try:
        response = await client.get("/api/ready")
    finally:
        server.shutdown()
        server.server_close()
        if old_vllm is None:
            os.environ.pop("VLLM_BASE_URL", None)
        else:
            os.environ["VLLM_BASE_URL"] = old_vllm

    assert response.status_code == 503
    vllm_dependency = response.json()["dependencies"]["vllm"]
    assert vllm_dependency["ok"] is False
    assert "mismatch" in vllm_dependency["error"]
    assert "serving Qwen/stale-model" in vllm_dependency["error"]
