"""Chat fails closed when no LLM provider is available, and says why when the gateway refuses."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from httpx import AsyncClient

from server.api.chat import set_config, set_fusion
from server.chat.generation_failure import GENERATION_FAILURE_HINTS
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig, TriBridConfig


class _FakeFusion:
    def __init__(self, chunks: list[ChunkMatch]):
        self._chunks = chunks
        self.last_debug = {}

    async def search(
        self,
        corpus_ids: list[str],
        query: str,
        config: FusionConfig,
        *,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
        cache_mode: str = "default",
        cache_namespace: str = "search",
    ) -> list[ChunkMatch]:
        _ = (corpus_ids, query, config, include_vector, include_sparse, include_graph, top_k)
        self.last_debug = {
            "fusion_corpora": list(corpus_ids),
            "fusion_vector_requested": bool(include_vector),
            "fusion_sparse_requested": bool(include_sparse),
            "fusion_graph_requested": bool(include_graph),
            "fusion_vector_enabled": False,
            "fusion_sparse_enabled": True,
            "fusion_graph_enabled": False,
            "fusion_vector_results": 0,
            "fusion_sparse_results": len(self._chunks),
            "fusion_graph_hydrated_chunks": 0,
        }
        return list(self._chunks)


def _disable_all_chat_providers(cfg: TriBridConfig) -> TriBridConfig:
    cfg.chat.litellm.enabled = False
    return cfg


@pytest.fixture
def providerless_chat_config() -> TriBridConfig:
    return _disable_all_chat_providers(TriBridConfig())


@pytest.fixture
def providerless_fusion() -> _FakeFusion:
    return _FakeFusion(
        [
            ChunkMatch(
                chunk_id="c1",
                content="hello world",
                file_path="src/main.py",
                start_line=1,
                end_line=1,
                language="python",
                score=1.0,
                source="sparse",
                metadata={"corpus_id": "test-repo"},
            )
        ]
    )


@pytest.mark.asyncio
async def test_chat_returns_503_without_providers(
    client: AsyncClient,
    providerless_chat_config: TriBridConfig,
    providerless_fusion: _FakeFusion,
) -> None:
    old_litellm = os.environ.pop("LITELLM_API_KEY", None)

    try:
        set_config(providerless_chat_config)
        set_fusion(providerless_fusion)

        response = await client.post(
            "/api/chat",
            json={"message": "hello", "sources": {"corpus_ids": ["test-repo"]}},
        )

        assert response.status_code == 503
        detail = str(response.json().get("detail") or "")
        assert detail
        assert "retrieval-only" not in detail.lower()
    finally:
        set_config(None)
        set_fusion(None)
        if old_litellm is not None:
            os.environ["LITELLM_API_KEY"] = old_litellm
        else:
            os.environ.pop("LITELLM_API_KEY", None)


@pytest.mark.asyncio
async def test_chat_stream_emits_error_event_without_providers(
    client: AsyncClient,
    providerless_chat_config: TriBridConfig,
    providerless_fusion: _FakeFusion,
) -> None:
    old_openai = os.environ.pop("OPENAI_API_KEY", None)
    old_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)

    try:
        set_config(providerless_chat_config)
        set_fusion(providerless_fusion)

        response = await client.post(
            "/api/chat/stream",
            json={
                "message": "hello",
                "stream": True,
                "sources": {"corpus_ids": ["test-repo"]},
            },
        )

        assert response.status_code == 200
        body = (await response.aread()).decode("utf-8")
        events: list[dict[str, object]] = []
        for block in body.split("\n\n"):
            part = block.strip()
            if not part.startswith("data:"):
                continue
            raw = part[len("data:") :].strip()
            if not raw:
                continue
            events.append(json.loads(raw))

        error_event = next((event for event in events if event.get("type") == "error"), None)
        done_event = next((event for event in events if event.get("type") == "done"), None)

        assert error_event is not None
        assert done_event is not None
        assert done_event.get("llm_used") is False
        assert isinstance(done_event.get("llm_error"), str) and str(done_event["llm_error"]).strip()
        assert "retrieval-only" not in body.lower()

        # The in-stream error event carries the typed generation-failure detail
        # so the UI can render a structured error card instead of raw prose.
        error_detail = error_event.get("detail")
        assert isinstance(error_detail, dict), body
        assert error_detail.get("code") == "generation_unavailable"
        assert str(error_detail.get("operator_hint") or "").strip()
        assert str(error_detail.get("operation") or "").strip()
    finally:
        set_config(None)
        set_fusion(None)
        if old_openai is not None:
            os.environ["OPENAI_API_KEY"] = old_openai
        else:
            os.environ.pop("OPENAI_API_KEY", None)
        if old_openrouter is not None:
            os.environ["OPENROUTER_API_KEY"] = old_openrouter
        else:
            os.environ.pop("OPENROUTER_API_KEY", None)


# A real question for the fixture chunk's corpus: placeholder queries are banned (testing.md).
CALIBRATION_QUESTION = "How often is the Aurora salinity sensor array calibrated?"

# The gateway's real answers on LXC100 (2026-09-02): OpenRouter over its weekly limit,
# and `ragweld-local` with no vLLM behind the gateway. The key hash below is not the
# live one; the point is that whatever follows "/keys/" never reaches the card.
_FAKE_KEY_HASH = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
OPENROUTER_LIMIT_MESSAGE = (
    "litellm.APIError: APIError: OpenrouterException - "
    '{"error":{"message":"Key limit exceeded (weekly limit). Manage it using '
    f'https://openrouter.ai/workspaces/default/keys/{_FAKE_KEY_HASH}","code":403}}}}'
    "No fallback model group found for original model_group=openai.gpt-5.6-luna. Fallbacks=[]"
)
LANE_DOWN_MESSAGE = (
    "litellm.InternalServerError: InternalServerError: OpenAIException - Connection error."
    "No fallback model group found for original model_group=ragweld-local. Fallbacks=[]. "
    "Received Model Group=ragweld-local\nAvailable Model Group Fallbacks=None"
)


class _RefusingGatewayHandler(BaseHTTPRequestHandler):
    """A LiteLLM-shaped gateway that answers every completion with one configured refusal."""

    status = 500
    body: dict[str, Any] = {}
    requests_seen = 0

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        type(self).requests_seen += 1
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        encoded = json.dumps(type(self).body).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - http.server API
        return


@contextmanager
def _refusing_gateway(status: int, message: str) -> Iterator[str]:
    """Serve the refusal on a loopback port and point the gateway wiring at it.

    Deployment wiring (`LITELLM_BASE_URL`) wins over persisted config in
    `resolve_litellm_base_url`, so the env is what must point here; a config-only
    base URL would send the request to the box's real gateway.
    """
    _RefusingGatewayHandler.status = status
    _RefusingGatewayHandler.body = {"error": {"message": message, "type": None, "param": None, "code": str(status)}}
    _RefusingGatewayHandler.requests_seen = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RefusingGatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous = {name: os.environ.get(name) for name in ("LITELLM_BASE_URL", "LITELLM_API_KEY")}
    try:
        host, port = server.server_address
        base_url = f"http://{host}:{port}/v1"
        os.environ["LITELLM_BASE_URL"] = base_url
        os.environ["LITELLM_API_KEY"] = previous["LITELLM_API_KEY"] or "sk-test-gateway-client-key-0123456789"
        yield base_url
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _gateway_config(base_url: str | None = None) -> TriBridConfig:
    cfg = TriBridConfig()
    litellm = cfg.chat.litellm.model_copy(update={"enabled": True, **({"base_url": base_url} if base_url else {})})
    recall = cfg.chat.recall.model_copy(update={"enabled": False})
    return cfg.model_copy(
        update={
            "chat": cfg.chat.model_copy(update={"litellm": litellm, "recall": recall}),
            "semantic_cache": cfg.semantic_cache.model_copy(update={"enabled": False}),
        }
    )


def _sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        part = block.strip()
        if part.startswith("data:"):
            raw = part[len("data:") :].strip()
            if raw:
                events.append(json.loads(raw))
    return events


def _assert_classified_detail(detail: Any, *, kind: str, reason_fragment: str, operation: str) -> dict[str, Any]:
    assert isinstance(detail, dict), detail
    assert detail["code"] == "generation_unavailable"
    assert detail["operation"] == operation
    assert detail["retryable"] is True
    assert detail["failure_kind"] == kind
    assert detail["operator_hint"] == GENERATION_FAILURE_HINTS[kind]
    reason = str(detail["gateway_reason"])
    assert reason_fragment in reason, reason
    assert _FAKE_KEY_HASH not in reason
    assert "openrouter.ai" not in reason
    assert "127.0.0.1" not in reason
    assert "\n" not in reason
    return detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message", "kind", "reason_fragment"),
    [
        (403, OPENROUTER_LIMIT_MESSAGE, "spend_limit", "Key limit exceeded (weekly limit)"),
        (500, LANE_DOWN_MESSAGE, "upstream_unreachable", "OpenAIException - Connection error"),
    ],
)
async def test_chat_surfaces_the_classified_gateway_reason_on_both_transports(
    client: AsyncClient,
    providerless_fusion: _FakeFusion,
    status: int,
    message: str,
    kind: str,
    reason_fragment: str,
) -> None:
    payload = {"message": CALIBRATION_QUESTION, "sources": {"corpus_ids": ["test-repo"]}, "cache_mode": "bypass"}
    with _refusing_gateway(status, message) as base_url:
        set_config(_gateway_config(base_url))
        set_fusion(providerless_fusion)
        try:
            response = await client.post("/api/chat", json=payload)
            assert response.status_code == 503, response.text
            http_detail = _assert_classified_detail(
                response.json()["detail"], kind=kind, reason_fragment=reason_fragment, operation="Chat generation"
            )

            stream = await client.post("/api/chat/stream", json={**payload, "stream": True})
            assert stream.status_code == 200
            events = _sse_events((await stream.aread()).decode("utf-8"))
            error_event = next((event for event in events if event.get("type") == "error"), None)
            done_event = next((event for event in events if event.get("type") == "done"), None)
            assert error_event is not None, events
            assert done_event is not None, events
            stream_detail = _assert_classified_detail(
                error_event["detail"], kind=kind, reason_fragment=reason_fragment, operation="Chat stream generation"
            )
            # Both transports classify the same refusal the same way, and the stream's
            # legacy free-text fields carry nothing the typed detail does not.
            assert stream_detail["gateway_reason"] == http_detail["gateway_reason"]
            assert stream_detail["operator_hint"] == http_detail["operator_hint"]
            assert error_event["message"] == stream_detail["gateway_reason"]
            assert done_event["llm_used"] is False
            assert done_event["llm_error"] == stream_detail["gateway_reason"]
            # Both transports really went through the refusing gateway (not the box's own).
            assert _RefusingGatewayHandler.requests_seen == 2
        finally:
            set_config(None)
            set_fusion(None)


@pytest.mark.asyncio
async def test_local_alias_without_a_serving_lane_is_reported_as_lane_down_through_the_live_gateway(
    client: AsyncClient,
    providerless_fusion: _FakeFusion,
) -> None:
    """`ragweld-local` through the real gateway: no vLLM behind it is a free, honest lane-down repro."""
    if not os.environ.get("LITELLM_BASE_URL") or not os.environ.get("LITELLM_API_KEY"):
        pytest.skip("LITELLM_BASE_URL/LITELLM_API_KEY are not set; the live gateway is not configured for this run")
    set_config(_gateway_config())
    set_fusion(providerless_fusion)
    try:
        stream = await client.post(
            "/api/chat/stream",
            json={
                "message": CALIBRATION_QUESTION,
                "stream": True,
                "model_override": "litellm:ragweld-local",
                "sources": {"corpus_ids": ["test-repo"]},
                "cache_mode": "bypass",
            },
        )
        assert stream.status_code == 200, stream.text
        events = _sse_events((await stream.aread()).decode("utf-8"))
        done_event = next((event for event in events if event.get("type") == "done"), None)
        assert done_event is not None, events
        if done_event.get("llm_used") is True:
            pytest.skip("a serving lane answered ragweld-local; the lane-down repro needs no vLLM behind the gateway")
        error_event = next((event for event in events if event.get("type") == "error"), None)
        assert error_event is not None, events
        detail = error_event["detail"]
        assert isinstance(detail, dict), error_event
        if detail.get("failure_kind") == "gateway_unreachable":
            pytest.skip(f"the LiteLLM gateway itself did not answer: {detail.get('gateway_reason')}")
        _assert_classified_detail(
            detail, kind="upstream_unreachable", reason_fragment="Connection error", operation="Chat stream generation"
        )
        assert "ragweld-local" in str(detail["gateway_reason"])
    finally:
        set_config(None)
        set_fusion(None)
