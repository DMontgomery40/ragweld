"""Real HTTP contract tests for LiteLLM-only Chat model discovery."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from httpx import AsyncClient

from server.api.chat import set_config
from server.models.chat_config import ChatConfig, LiteLLMConfig
from server.models.tribrid_config_model import TriBridConfig


class _ModelsHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != "Bearer gateway-key":
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps(
            {
                "data": [
                    {"id": "ragweld-local"},
                    {"id": "openai.gpt-5.4-mini"},
                    {"id": "openai.text-embedding-3-small"},
                    {"id": "openai.text-embedding-3-large"},
                    {"id": "hand-added-alias-not-in-catalog"},
                ]
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _gateway_models() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old_key = os.environ.get("LITELLM_API_KEY")
    old_url = os.environ.get("LITELLM_BASE_URL")
    try:
        host, port = server.server_address
        base_url = f"http://{host}:{port}/v1"
        os.environ["LITELLM_API_KEY"] = "gateway-key"
        os.environ["LITELLM_BASE_URL"] = base_url
        set_config(
            TriBridConfig(
                chat=ChatConfig(
                    litellm=LiteLLMConfig(
                        enabled=True,
                        base_url=base_url,
                        default_model="ragweld-local",
                    )
                )
            )
        )
        yield base_url
    finally:
        set_config(None)
        if old_key is None:
            os.environ.pop("LITELLM_API_KEY", None)
        else:
            os.environ["LITELLM_API_KEY"] = old_key
        if old_url is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = old_url
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_chat_models_publish_only_catalog_backed_aliases(client: AsyncClient) -> None:
    with _gateway_models():
        response = await client.get("/api/chat/models")

    assert response.status_code == 200
    models = response.json()["models"]
    assert [row["id"] for row in models] == ["ragweld-local", "openai.gpt-5.4-mini"]
    assert [row["override"] for row in models] == ["litellm:ragweld-local", "litellm:openai.gpt-5.4-mini"]
    assert {row["source"] for row in models} == {"litellm"}
    assert {row["provider"] for row in models} == {"LiteLLM"}
    assert all(row["catalog_provider"] and row["catalog_model"] for row in models)

    local, paid = models
    assert local["catalog_provider"] == "ragweld"
    assert local["catalog_model"]
    assert local["input_per_1k"] == 0.0 and local["output_per_1k"] == 0.0
    assert local["supports_vision"] is False

    assert paid["catalog_provider"] == "openai"
    assert paid["catalog_model"] == "openai/gpt-5.4-mini"
    assert paid["display_name"] == "OpenAI: GPT-5.4 Mini"
    assert paid["context"] and paid["context"] > 0
    assert paid["input_per_1k"] and paid["input_per_1k"] > 0
    assert paid["output_per_1k"] and paid["output_per_1k"] > 0
    assert paid["supports_vision"] is True


@pytest.mark.asyncio
async def test_chat_models_returns_503_when_gateway_is_unreachable(client: AsyncClient) -> None:
    old_url = os.environ.get("LITELLM_BASE_URL")
    os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:1/v1"
    set_config(TriBridConfig())
    try:
        response = await client.get("/api/chat/models")
    finally:
        set_config(None)
        if old_url is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = old_url

    assert response.status_code == 503
    assert "LiteLLM" in str(response.json().get("detail") or "")
