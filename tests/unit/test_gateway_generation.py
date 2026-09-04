from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from server.chat.generation import (
    GatewayContentMissingError,
    generate_chat_text,
    stream_chat_text,
)
from server.chat.provider_router import ProviderRoute
from server.gateway_catalog import warm_gateway_catalog
from server.models.tribrid_config_model import TriBridConfig
from server.observability.runtime import current_trace_payload_fields, start_request_observation

FAIL_ONCE_KEY = "fail-once-key"
# A reasoning model that spends its whole output budget thinking answers with no assistant
# content, and the gateway bills it anyway (defect D26).
REASONING_ONLY_KEY = "reasoning-only-key"
REASONING_ONLY_COST_USD = 0.004212


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
        if self.headers.get("Authorization") == f"Bearer {REASONING_ONLY_KEY}":
            if payload.get("stream"):
                chunks = [
                    {"id": "resp-reasoning-only-stream", "choices": [{"delta": {"reasoning": "..."}}]},
                    {
                        "id": "resp-reasoning-only-stream",
                        "choices": [{"delta": {}, "finish_reason": "length"}],
                        "usage": {
                            "prompt_tokens": 918,
                            "completion_tokens": 256,
                            "total_tokens": 1174,
                            "completion_tokens_details": {"reasoning_tokens": 256},
                        },
                    },
                ]
                stream_body = (
                    "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("X-Request-Id", "trace-reasoning-only-stream")
                self.send_header("Content-Length", str(len(stream_body)))
                self.end_headers()
                self.wfile.write(stream_body)
                return
            body = json.dumps(
                {
                    "id": "resp-reasoning-only",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": None, "reasoning": "..."},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 918,
                        "completion_tokens": 256,
                        "total_tokens": 1174,
                        "completion_tokens_details": {"reasoning_tokens": 256},
                    },
                    "hidden_params": {"response_cost": REASONING_ONLY_COST_USD},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Request-Id", "trace-reasoning-only")
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
                "choices": [{"message": {"role": "assistant", "content": "Hello gateway"}, "finish_reason": "stop"}],
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
            user_message="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?",
            images=[],
            temperature=0,
            max_tokens=8,
            context_chunks=[],
        )

    assert result.text == "Hello gateway"
    assert result.provider_response_id == "resp-nonstream"
    assert result.debug_trace_id == "trace-nonstream"
    assert result.usage == {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
    assert result.finish_reason == "stop"
    assert len(_GatewayHandler.requests) == 1
    request = _GatewayHandler.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer test-gateway-key"
    assert request["payload"]["model"] == "ragweld-local"
    assert request["payload"]["max_tokens"] == 8
    assert request["payload"]["stream"] is False
    assert "reasoning" not in request["payload"] and "reasoning_effort" not in request["payload"]


@pytest.mark.asyncio
async def test_nonstream_body_fields_ride_at_the_top_level_of_the_request() -> None:
    """A lane's reasoning control (defect D26) is a top-level body key in the upstream's own
    protocol; the transport carries it verbatim and never lets it redefine its own keys."""
    with _gateway_server() as base_url:
        result = await generate_chat_text(
            route=_route(base_url, model="openai.gpt-5.6-luna"),
            system_prompt="You are a retrieval reranker.",
            user_message="Which plane management company did Barry Cohen consider switching to from Jet Aviation?",
            images=[],
            temperature=0,
            max_tokens=8,
            context_chunks=[],
            body_fields={"reasoning": {"effort": "none"}},
        )
        assert result.text == "Hello gateway"
        payload = _GatewayHandler.requests[-1]["payload"]
        assert payload["reasoning"] == {"effort": "none"}
        assert payload["max_tokens"] == 8 and payload["model"] == "openai.gpt-5.6-luna"

        with pytest.raises(ValueError, match="max_tokens"):
            await generate_chat_text(
                route=_route(base_url, model="openai.gpt-5.6-luna"),
                system_prompt="You are a retrieval reranker.",
                user_message="Which plane management company did Barry Cohen consider switching to from Jet Aviation?",
                images=[],
                temperature=0,
                max_tokens=8,
                context_chunks=[],
                body_fields={"max_tokens": 4096},
            )
    assert len(_GatewayHandler.requests) == 1


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
                user_message="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?",
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
                user_message="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?",
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
                    user_message="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?",
                    images=[],
                    temperature=0,
                    max_tokens=8,
                    context_chunks=[],
                )
            ]

    assert len(_GatewayHandler.requests) == 1


@pytest.mark.asyncio
async def test_a_billed_reasoning_only_reply_is_costed_before_the_typed_error() -> None:
    """A 200 with no assistant content was still billed, so it must still be costed (D26).

    The gateway answered, charged for 256 reasoning tokens and returned ``content: null``.
    ``generate_chat_text`` used to raise ``GatewayContentMissingError`` before it extracted the
    provider cost, so the request's whole spend disappeared from the trace. The typed error
    still carries the usage AND the trace now carries the provider's own cost.
    """
    config = TriBridConfig()
    config.tracing.tracing_enabled = True
    config.tracing.tracing_mode = "local"
    config.tracing.otel_export_enabled = False

    with _gateway_server() as base_url:
        with start_request_observation(
            config=config, route_name="chat.send", path="/api/chat", method="POST"
        ) as observation:
            # Without a live observation `set_cost_summary` is a no-op and this test would
            # assert nothing at all.
            assert observation is not None, "tracing is off in this config; the test is vacuous"
            with pytest.raises(GatewayContentMissingError) as raised:
                await generate_chat_text(
                    route=_route(
                        base_url, model="openai.gpt-5.6-luna", api_key=REASONING_ONLY_KEY
                    ),
                    system_prompt="You are a retrieval reranker.",
                    user_message=(
                        "Which plane management company did Barry Cohen consider switching to "
                        "from Jet Aviation?"
                    ),
                    images=[],
                    temperature=0,
                    max_tokens=64,
                    context_chunks=[],
                    body_fields={"reasoning": {"effort": "high"}},
                )
            cost = current_trace_payload_fields()["cost_summary"]

    error = raised.value
    assert error.finish_reason == "length"
    assert error.usage is not None
    assert error.usage["completion_tokens_details"]["reasoning_tokens"] == 256

    assert cost is not None, "a billed empty-content reply left no cost summary on the trace"
    assert cost.provider == "LiteLLM" and cost.model == "openai.gpt-5.6-luna"
    assert (cost.input_tokens, cost.output_tokens, cost.total_tokens) == (918, 256, 1174)
    assert cost.estimated_cost_usd == pytest.approx(REASONING_ONLY_COST_USD)
    assert cost.cost_source == "provider" and cost.authoritative is True
    assert len(_GatewayHandler.requests) == 1


@pytest.mark.asyncio
async def test_a_billed_reasoning_only_stream_is_costed_before_the_typed_error() -> None:
    """The streaming transport bills the same way and now fails the same way.

    A stream that carried usage but never a content delta used to raise a bare RuntimeError
    with the tokens dropped on the floor: no cost summary, no usage on the error. It now raises
    the same typed ``GatewayContentMissingError`` the non-streaming transport does, after the
    cost summary is on the trace. The message is unchanged, so
    ``classify_generation_failure`` still reads it as a gateway failure.
    """
    config = TriBridConfig()
    config.tracing.tracing_enabled = True
    config.tracing.tracing_mode = "local"
    config.tracing.otel_export_enabled = False

    with _gateway_server() as base_url:
        with start_request_observation(
            config=config, route_name="chat.stream", path="/api/chat/stream", method="POST"
        ) as observation:
            assert observation is not None, "tracing is off in this config; the test is vacuous"
            with pytest.raises(GatewayContentMissingError) as raised:
                _ = [
                    delta
                    async for delta in stream_chat_text(
                        route=_route(
                            base_url, model="openai.gpt-5.6-luna", api_key=REASONING_ONLY_KEY
                        ),
                        system_prompt="You are a retrieval reranker.",
                        user_message=(
                            "Which plane management company did Barry Cohen consider switching "
                            "to from Jet Aviation?"
                        ),
                        images=[],
                        temperature=0,
                        max_tokens=64,
                        context_chunks=[],
                    )
                ]
            cost = current_trace_payload_fields()["cost_summary"]

    error = raised.value
    assert str(error) == "LiteLLM stream produced no content"
    assert error.finish_reason == "length"
    assert error.usage is not None
    assert error.usage["completion_tokens_details"]["reasoning_tokens"] == 256

    assert cost is not None, "a billed empty stream left no cost summary on the trace"
    assert (cost.input_tokens, cost.output_tokens, cost.total_tokens) == (918, 256, 1174)


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
                        route=_route(base_url, model="openai.gpt-5.6-luna"),
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
                            route=_route(base_url, model="openai.gpt-5.6-luna"),
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
