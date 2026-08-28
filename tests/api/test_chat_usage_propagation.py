from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from server.api.chat import set_config, set_fusion
from server.gateway_catalog import warm_gateway_catalog
from server.main import app
from server.models.tribrid_config_model import TriBridConfig
from server.services.conversation_store import get_conversation_store


class _UsageGatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if payload.get("stream"):
            chunks = [
                {
                    "id": "usage-stream",
                    "choices": [{"delta": {"content": "Apollo 11 landed on the Moon."}}],
                },
                {
                    "id": "usage-stream",
                    "choices": [],
                    "usage": {"promptTokens": 4, "completionTokens": 2},
                },
            ]
            body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            body += "data: [DONE]\n\n"
            encoded = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        encoded = json.dumps(
            {
                "id": "usage-nonstream",
                "choices": [
                    {"message": {"role": "assistant", "content": "Apollo 11 landed on the Moon."}}
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@contextmanager
def _usage_gateway() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UsageGatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _UnusedFusion:
    last_debug: dict[str, Any] = {}

    async def search(self, *_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("No corpus was selected, so retrieval must not run")


def _usage_config(base_url: str) -> TriBridConfig:
    config = TriBridConfig()
    litellm = config.chat.litellm.model_copy(
        update={
            "enabled": True,
            "base_url": base_url,
            "default_model": "openai.gpt-5.6-terra",
        }
    )
    chat = config.chat.model_copy(update={"litellm": litellm})
    semantic_cache = config.semantic_cache.model_copy(update={"enabled": False})
    tracing = config.tracing.model_copy(
        update={
            "tracing_enabled": True,
            "tracing_mode": "local",
            "otel_export_enabled": False,
            "langfuse_enabled": False,
        }
    )
    return config.model_copy(
        update={
            "chat": chat,
            "semantic_cache": semantic_cache,
            "tracing": tracing,
        }
    )


@pytest.mark.asyncio
async def test_chat_transports_report_real_gateway_usage() -> None:
    warm_gateway_catalog()
    get_conversation_store()._conversations.clear()

    with _usage_gateway() as base_url:
        set_config(_usage_config(base_url))
        set_fusion(_UnusedFusion())
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                nonstream = await client.post(
                    "/api/chat",
                    json={
                        "message": "What was the primary purpose of Apollo 11?",
                        "sources": {"corpus_ids": []},
                        "cache_mode": "bypass",
                    },
                )
                assert nonstream.status_code == 200, nonstream.text
                nonstream_payload = nonstream.json()
                assert nonstream_payload["tokens_used"] == 6
                nonstream_trace = await client.get(
                    "/api/traces/latest",
                    params={"run_id": nonstream_payload["run_id"]},
                )
                assert nonstream_trace.status_code == 200
                trace_payload = nonstream_trace.json()["trace"]
                assert trace_payload["cost_summary"]["total_tokens"] == 6
                response_event = next(
                    event for event in trace_payload["events"] if event["kind"] == "chat.response"
                )
                assert response_event["data"]["tokens_used"] == 6

                async with client.stream(
                    "POST",
                    "/api/chat/stream",
                    json={
                        "message": "Where did Apollo 11 land?",
                        "sources": {"corpus_ids": []},
                        "stream": True,
                        "cache_mode": "bypass",
                    },
                ) as response:
                    assert response.status_code == 200
                    done_payload: dict[str, Any] | None = None
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = json.loads(line.removeprefix("data: "))
                        if payload.get("type") == "done":
                            done_payload = payload
                    assert done_payload is not None
                    assert done_payload["tokens_used"] == 6
                    stream_trace = await client.get(
                        "/api/traces/latest",
                        params={"run_id": done_payload["run_id"]},
                    )
                    assert stream_trace.status_code == 200
                    stream_trace_payload = stream_trace.json()["trace"]
                    assert stream_trace_payload["cost_summary"]["total_tokens"] == 6
                    stream_response_event = next(
                        event
                        for event in stream_trace_payload["events"]
                        if event["kind"] == "chat.response"
                    )
                    assert stream_response_event["data"]["tokens_used"] == 6
        finally:
            set_config(None)
            set_fusion(None)
