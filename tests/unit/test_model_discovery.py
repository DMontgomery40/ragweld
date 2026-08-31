from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.chat.model_discovery import discover_litellm_models
from server.models.chat_config import LiteLLMConfig


class _ModelsHandler(BaseHTTPRequestHandler):
    authorization: str | None = None

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        type(self).authorization = self.headers.get("Authorization")
        if type(self).authorization != "Bearer gateway-key":
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps(
            {
                "data": [
                    {"id": "ragweld-local"},
                    {"id": "openai.gpt-5.4-mini"},
                    {"id": "ragweld-local"},
                ]
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _models_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous_base_url = os.environ.get("LITELLM_BASE_URL")
    try:
        host, port = server.server_address
        base_url = f"http://{host}:{port}/v1"
        os.environ["LITELLM_BASE_URL"] = base_url
        yield base_url
    finally:
        if previous_base_url is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = previous_base_url
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _key(value: str | None) -> Iterator[None]:
    old = os.environ.get("LITELLM_API_KEY")
    if value is None:
        os.environ.pop("LITELLM_API_KEY", None)
    else:
        os.environ["LITELLM_API_KEY"] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("LITELLM_API_KEY", None)
        else:
            os.environ["LITELLM_API_KEY"] = old


@pytest.mark.asyncio
async def test_discovery_is_authenticated_litellm_only_and_deduplicated() -> None:
    with _models_server() as base_url, _key("gateway-key"):
        rows = await discover_litellm_models(
            LiteLLMConfig(enabled=True, base_url=base_url, default_model="ragweld-local")
        )

    assert [row["id"] for row in rows] == ["ragweld-local", "openai.gpt-5.4-mini"]
    assert {row["source"] for row in rows} == {"litellm"}
    assert _ModelsHandler.authorization == "Bearer gateway-key"


@pytest.mark.asyncio
async def test_disabled_gateway_fails_honestly() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        await discover_litellm_models(LiteLLMConfig(enabled=False))


@pytest.mark.asyncio
async def test_bad_gateway_auth_fails_honestly() -> None:
    with _models_server() as base_url, _key("wrong-key"):
        with pytest.raises(RuntimeError, match="HTTP 401"):
            await discover_litellm_models(LiteLLMConfig(enabled=True, base_url=base_url))
