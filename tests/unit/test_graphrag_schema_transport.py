from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from server.indexing.graphrag_schema import derive_graph_schema_proposal
from server.models.index import Chunk
from server.models.tribrid_config_model import GraphIndexingConfig


def _schema_content() -> dict[str, Any]:
    return {
        "node_types": [
            {"label": label, "description": "A named domain entity", "properties": [
                {"name": "name", "type": "STRING", "description": "Entity name"},
            ]}
            for label in ("Mission", "Instrument")
        ],
        "relationship_types": [{"label": "USES", "description": "Operates equipment", "properties": []}],
        "patterns": [{"source": "Mission", "relationship": "USES", "target": "Instrument"}],
        "constraints": [],
    }


@contextmanager
def proposal_gateway(scenario: str) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """A real HTTP transport fixture; the official SDK and extractor execute unchanged."""
    requests: list[dict[str, Any]] = []
    state: dict[str, Any] = {"scenario": scenario, "completed": 0, "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _control_response(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler
            if self.path.endswith("/models"):
                self._control_response({"object": "list", "data": [{
                    "id": "openai.gpt-5.6-sol", "object": "model", "created": 1,
                    "owned_by": "transport-fixture",
                }]})
                return
            latest = requests[-1] if requests else {}
            self._control_response({
                "received": len(requests), "completed": state["completed"],
                "last_reasoning_effort": latest.get("reasoning", {}).get("effort"),
                "last_model": latest.get("model"),
            })

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("/__fixture__/scenario"):
                state["scenario"] = payload["scenario"]
                state["release"] = threading.Event()
                self._control_response({"scenario": state["scenario"]})
                return
            if self.path.endswith("/__fixture__/release"):
                state["release"].set()
                self._control_response({"released": True})
                return
            requests.append(payload)
            selected = state["scenario"]
            if selected == "disconnect":
                self.close_connection = True
                state["completed"] += 1
                return
            if selected == "held_valid":
                state["release"].wait(timeout=30)
            elif selected == "slow":
                time.sleep(6)
            status = int(selected) if selected in {"429", "503"} else 200
            schema = _schema_content()
            if selected == "large_valid":
                schema["node_types"][0]["description"] = "Mission operations. " * 8000
            content = json.dumps(schema)
            if selected == "malformed":
                content = '{"node_types":['
            elif selected == "oversized":
                content = '{"node_types":[' + " " * (4 * 1024 * 1024)
            elif selected == "wrong_shape":
                content = '{"node_types":"PRIVATE PROVIDER DETAIL"}'
            elif selected == "empty":
                content = ""
            completion = {
                "id": "proposal-contract-response", "object": "chat.completion", "created": 1,
                "model": "openai.gpt-5.6-sol",
                "choices": [{"index": 0, "finish_reason": "length" if selected == "truncated" else "stop",
                             "message": {"role": "assistant", "content": content,
                                         "refusal": "PRIVATE PROVIDER DETAIL" if selected == "refusal" else None}}],
                "usage": {"prompt_tokens": 18, "completion_tokens": 24, "total_tokens": 42},
            }
            if status != 200:
                completion = {"error": {"message": "PRIVATE PROVIDER DETAIL", "type": "rate_limit"}}
            body = json.dumps(completion).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-litellm-response-cost", "0.00042")
            self.end_headers()
            try:
                if selected == "drip":
                    for byte in body[:30]:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.04)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                state["completed"] += 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        state["release"].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def _proposal(base_url: str, *, timeout_s: float = 2.0, reasoning_effort: str = "low") -> Any:
    return await derive_graph_schema_proposal(
        corpus_id="mission-instruments",
        chunks=[Chunk(chunk_id="mission:1", file_path="mission.md", start_line=1, end_line=2,
                      content="The orbital survey mission uses a radar altimeter.", token_count=12)],
        model_alias="openai.gpt-5.6-sol", route_model="openai.gpt-5.6-sol",
        route_base_url=base_url, route_api_key="transport-fixture-key",
        route_upstream="openrouter/openai/gpt-5.6-sol", reasoning_effort=reasoning_effort,
        input_fingerprint="a" * 64, timeout_s=timeout_s, max_output_tokens=16384,
    )


@pytest.mark.asyncio
async def test_proposal_gateway_serves_native_model_discovery_and_separate_control_state() -> None:
    with proposal_gateway("valid") as (url, requests):
        async with AsyncClient() as client:
            models = await client.get(f"{url}/models")
            state = await client.get(f"{url}/__fixture__/state")
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "openai.gpt-5.6-sol"
    assert state.json() == {"received": 0, "completed": 0, "last_reasoning_effort": None, "last_model": None}
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["valid", "large_valid"])
async def test_official_proposal_transport_bounds_output_and_preserves_valid_schema(scenario: str) -> None:
    with proposal_gateway(scenario) as (url, requests):
        proposal = await _proposal(url)
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 16384
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[0]["response_format"]["json_schema"]["strict"] is True
    assert requests[0]["reasoning"] == {"effort": "low"}
    assert proposal.schema_payload["patterns"] == [{"source": "Mission", "relationship": "USES", "target": "Instrument"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["malformed", "wrong_shape", "empty", "oversized", "truncated", "refusal", "429", "503", "disconnect"])
async def test_official_proposal_transport_rejects_bad_responses_once_without_exposing_content(scenario: str) -> None:
    with proposal_gateway(scenario) as (url, requests):
        with pytest.raises(Exception) as error:
            await _proposal(url)
    assert type(error.value).__name__ == "GraphSchemaProposalError"
    assert error.value.code == "graph_schema_generation_failed"
    assert "PRIVATE PROVIDER DETAIL" not in str(error.value)
    assert len(str(error.value)) < 300
    assert len(requests) == 1, "SDK and GraphRAG retry loops must both be disabled"
    if scenario in {"truncated", "refusal"}:
        assert error.value.usage.total_tokens == 42
        assert error.value.gateway_cost_usd == 0.00042


@pytest.mark.asyncio
async def test_official_proposal_transport_deadline_stops_continuously_dripping_output() -> None:
    with proposal_gateway("drip") as (url, requests):
        started = asyncio.get_running_loop().time()
        with pytest.raises(Exception) as error:
            await _proposal(url, timeout_s=0.2)
        elapsed = asyncio.get_running_loop().time() - started
    assert type(error.value).__name__ == "GraphSchemaProposalError"
    assert error.value.code == "graph_schema_deadline_exceeded"
    assert elapsed < 0.8, "an idle-read timeout must not replace a whole-operation deadline"
    assert len(requests) == 1


@pytest.mark.parametrize(("field", "value"), [
    ("schema_proposal_timeout_s", 4), ("schema_proposal_timeout_s", 81),
    ("schema_proposal_max_output_tokens", 255), ("schema_proposal_max_output_tokens", 32769),
])
def test_proposal_budget_constraints(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        GraphIndexingConfig.model_validate({field: value})


def test_proposal_budget_defaults_are_separate_from_chunk_extraction() -> None:
    config = GraphIndexingConfig(semantic_kg_llm_timeout_s=600, semantic_kg_reasoning_effort="high")
    assert getattr(config, "schema_proposal_timeout_s", None) == 60
    assert getattr(config, "schema_proposal_max_output_tokens", None) == 16384
    assert getattr(config, "schema_proposal_reasoning_effort", None) == "low"
    assert config.semantic_kg_reasoning_effort == "high"
    assert GraphIndexingConfig().semantic_kg_reasoning_effort == "medium"


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high", "xhigh"])
def test_proposal_reasoning_effort_round_trips_without_changing_extraction(effort: str) -> None:
    config = GraphIndexingConfig.model_validate({"schema_proposal_reasoning_effort": effort})
    restored = GraphIndexingConfig.model_validate_json(config.model_dump_json())
    assert getattr(restored, "schema_proposal_reasoning_effort", None) == effort
    assert restored.semantic_kg_reasoning_effort == "medium"


@pytest.mark.parametrize("effort", [None, "", "none", "max", "ultra", "LOW", 1])
def test_proposal_reasoning_effort_rejects_unsupported_values(effort: object) -> None:
    with pytest.raises(ValidationError):
        GraphIndexingConfig.model_validate({"schema_proposal_reasoning_effort": effort})


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high", "xhigh"])
async def test_official_proposal_transport_preserves_each_reasoning_effort(effort: str) -> None:
    with proposal_gateway("valid") as (url, requests):
        await _proposal(url, reasoning_effort=effort)
    assert len(requests) == 1
    assert requests[0]["reasoning"] == {"effort": effort}
