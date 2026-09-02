from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from server.api.index import _semantic_kg_reasoning_effort
from server.chat.generation import generate_chat_text, stream_chat_text
from server.chat.provider_router import ProviderRoute
from server.gateway_catalog import warm_gateway_catalog
from server.models.tribrid_config_model import TriBridConfig

FAIL_ONCE_KEY = "fail-once-key"


@pytest.fixture(autouse=True)
def _warm_catalog_snapshot() -> None:
    # The transport budgets every call against the alias's catalog context window.
    warm_gateway_catalog()


class _GatewayHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "payload": payload,
            }
        )
        if self.headers.get("Authorization") == f"Bearer {FAIL_ONCE_KEY}":
            body = json.dumps({"error": {"message": "controlled failure"}}).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if payload.get("stream"):
            chunks = [
                {"id": "resp-stream", "choices": [{"delta": {"content": "Hello"}}]},
                {"id": "resp-stream", "choices": [{"delta": {"content": " gateway"}}]},
                {"id": "resp-stream", "choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}},
            ]
            body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            encoded = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("X-Request-Id", "trace-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        body = json.dumps(
            {
                "id": "resp-nonstream",
                "choices": [{"message": {"role": "assistant", "content": "Hello gateway"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Request-Id", "trace-nonstream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _gateway_server() -> Iterator[str]:
    _GatewayHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _route(base_url: str, model: str = "ragweld-local", api_key: str = "test-gateway-key") -> ProviderRoute:
    return ProviderRoute(
        kind="litellm",
        provider_name="LiteLLM",
        base_url=base_url,
        model=model,
        api_key=api_key,
    )


@pytest.mark.asyncio
async def test_nonstream_uses_one_authenticated_openai_compatible_request() -> None:
    with _gateway_server() as base_url:
        result = await generate_chat_text(
            route=_route(base_url),
            system_prompt="System",
            user_message="Hello",
            images=[],
            temperature=0,
            max_tokens=8,
            context_chunks=[],
        )

    assert result.text == "Hello gateway"
    assert result.provider_response_id == "resp-nonstream"
    assert result.debug_trace_id == "trace-nonstream"
    assert result.usage == {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
    assert len(_GatewayHandler.requests) == 1
    request = _GatewayHandler.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer test-gateway-key"
    assert request["payload"]["model"] == "ragweld-local"
    assert request["payload"]["max_tokens"] == 8
    assert request["payload"]["stream"] is False


@pytest.mark.asyncio
async def test_stream_emits_deltas_usage_id_and_trace() -> None:
    provider_ids: list[str] = []
    usages: list[dict[str, Any]] = []
    traces: list[str] = []
    with _gateway_server() as base_url:
        deltas = [
            delta
            async for delta in stream_chat_text(
                route=_route(base_url),
                system_prompt="System",
                user_message="Hello",
                images=[],
                temperature=0,
                max_tokens=8,
                context_chunks=[],
                on_provider_response_id=provider_ids.append,
                on_usage=usages.append,
                on_debug_trace_id=traces.append,
            )
        ]

    assert deltas == ["Hello", " gateway"]
    assert provider_ids == ["resp-stream"]
    assert usages == [{"prompt_tokens": 4, "completion_tokens": 2}]
    assert traces == ["trace-stream"]
    assert len(_GatewayHandler.requests) == 1
    assert _GatewayHandler.requests[0]["payload"]["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_gateway_failure_is_not_retried_or_fallback_routed() -> None:
    with _gateway_server() as base_url:
        with pytest.raises(RuntimeError, match="controlled failure"):
            await generate_chat_text(
                route=_route(base_url, api_key=FAIL_ONCE_KEY),
                system_prompt="System",
                user_message="Hello",
                images=[],
                temperature=0,
                max_tokens=8,
                context_chunks=[],
            )

    assert len(_GatewayHandler.requests) == 1


@pytest.mark.asyncio
async def test_streaming_gateway_failure_reads_and_reports_error_body() -> None:
    with _gateway_server() as base_url:
        with pytest.raises(RuntimeError, match="controlled failure"):
            _ = [
                delta
                async for delta in stream_chat_text(
                    route=_route(base_url, api_key=FAIL_ONCE_KEY),
                    system_prompt="System",
                    user_message="Hello",
                    images=[],
                    temperature=0,
                    max_tokens=8,
                    context_chunks=[],
                )
            ]

    assert len(_GatewayHandler.requests) == 1


def _large_inline_png(pixels: int = 1400) -> str:
    """A poorly compressible PNG of a few MiB, the size class the UI allows per attachment."""
    import base64
    import os
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.frombytes("RGB", (pixels, pixels), os.urandom(pixels * pixels * 3)).save(buffer, format="PNG", compress_level=1)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


@pytest.mark.asyncio
async def test_image_bearing_requests_do_not_stall_the_event_loop() -> None:
    """Decoding, budgeting and serializing five multi-MiB attachments must not block unrelated loop work."""
    import asyncio
    import time

    from server.models.tribrid_config_model import ImageAttachment

    encoded = _large_inline_png()
    images = [ImageAttachment(base64=encoded, mime_type="image/png") for _ in range(5)]
    assert len(encoded) * 5 > 5 * 1024 * 1024  # > 5 MiB of base64 in flight

    max_gap = 0.0
    stop = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal max_gap
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            max_gap = max(max_gap, now - last - 0.01)
            last = now

    with _gateway_server() as base_url:
        ticker = asyncio.create_task(heartbeat())
        try:
            for transport in ("nonstream", "stream"):
                if transport == "nonstream":
                    result = await generate_chat_text(
                        route=_route(base_url, model="openai.gpt-4o"),
                        system_prompt="Describe the attached plane-management documents.",
                        user_message="Which aircraft management change do these scans discuss?",
                        images=images,
                        temperature=0.0,
                        max_tokens=128,
                        context_text="",
                        context_chunks=[],
                    )
                    assert result.text == "Hello gateway"
                else:
                    deltas = [
                        delta
                        async for delta in stream_chat_text(
                            route=_route(base_url, model="openai.gpt-4o"),
                            system_prompt="Describe the attached plane-management documents.",
                            user_message="Which aircraft management change do these scans discuss?",
                            images=images,
                            temperature=0.0,
                            max_tokens=128,
                            context_text="",
                            context_chunks=[],
                        )
                    ]
                    assert "".join(deltas) == "Hello gateway"
        finally:
            stop.set()
            await ticker
    assert max_gap < 0.25, f"event loop stalled for {max_gap:.3f}s while handling image attachments"
    sent = [req for req in _GatewayHandler.requests if req["payload"].get("messages")]
    assert len(sent) == 2
    assert all(len(req["payload"]["messages"][1]["content"]) == 6 for req in sent)  # text + 5 images


def test_semantic_kg_reasoning_effort_only_reaches_openai_routes() -> None:
    """Task 8 drive defect D22: the operator's reasoning effort is bound for OpenAI aliases and
    withheld from every other provider and from unknown aliases, because the knob is OpenAI's
    and DeepSeek answered it with output the official extractor rejects."""
    warm_gateway_catalog()
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_reasoning_effort = "xhigh"
    assert _semantic_kg_reasoning_effort(cfg, "openai.gpt-5.6-luna") == "xhigh"
    assert _semantic_kg_reasoning_effort(cfg, "deepseek.deepseek-v4-flash") is None
    assert _semantic_kg_reasoning_effort(cfg, "z-ai.glm-5.3-flash") is None
    assert _semantic_kg_reasoning_effort(cfg, "no.such-alias") is None
