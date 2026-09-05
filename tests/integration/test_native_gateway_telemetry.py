"""Pinned native OTLP/Prometheus contract, using only owned synthetic services.

RAGWELD_NATIVE_TELEMETRY_TESTS=1 enables Linux containers; no DB or provider keys.
The test uses real HTTP, native callbacks and OTLP protobuf exports, never mocks.
"""
from __future__ import annotations

import asyncio
import contextlib
import gzip
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from prometheus_client.parser import text_string_to_metric_families

from server.gateway_catalog import build_litellm_config, load_catalog
from server.observability.run_census import CensusTransport, RunCensusScope, RunIdentity
from tests.integration.test_native_gateway_policy import _IMAGE, _docker
from tests.service_requirements import _strict_mode

_INPUT = "synthetic-private-input-" + uuid4().hex
_OUTPUT = "synthetic-private-output-" + uuid4().hex
_TRACE = "1" * 32
_PARENT = "2" * 16


@dataclass
class _Telemetry:
    base_url: str
    otlp_host: str = ""
    exports: list[bytes] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    held: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


@pytest.fixture(scope="module")
def native_telemetry(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Telemetry]:
    if os.environ.get("RAGWELD_NATIVE_TELEMETRY_TESTS") != "1":
        if _strict_mode():
            pytest.fail("Strict native telemetry acceptance requires RAGWELD_NATIVE_TELEMETRY_TESTS=1")
        pytest.skip("Native telemetry acceptance requires RAGWELD_NATIVE_TELEMETRY_TESTS=1")
    if sys.platform != "linux" or shutil.which("docker") is None:
        pytest.fail("Native telemetry acceptance requires Linux Docker on the authorized runtime")
    _docker("image", "inspect", _IMAGE)
    state = _Telemetry("")

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP contract
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/api/public/otel/v1/traces":
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                ExportTraceServiceRequest.FromString(raw)
                with state.lock:
                    state.exports.append(raw)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = json.loads(raw)
            with state.lock:
                state.calls.append(body)
            embedding = self.path.endswith("/embeddings")
            assert _INPUT in (body["input"][0] if embedding else body["messages"][0]["content"])
            if body.get("model") == "held":
                state.held.set()
                state.release.wait(10)
            failed = body.get("model") == "failure"
            if embedding:
                encoded = json.dumps({"object": "list", "model": body["model"], "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}], "usage": {"prompt_tokens": 5, "total_tokens": 5}}).encode()
            elif failed:
                encoded = json.dumps({"error": {"message": "Synthetic provider unavailable", "type": "server_error"}}).encode()
            elif body.get("stream"):
                events = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant", "content": _OUTPUT}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                    {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}},
                ]
                encoded = b"".join(("data: " + json.dumps({"id": "chatcmpl-fixture", "object": "chat.completion.chunk", "created": 1, "model": body["model"], **event}) + "\n\n").encode() for event in events) + b"data: [DONE]\n\n"
            else:
                encoded = json.dumps({"id": "chatcmpl-fixture", "object": "chat.completion", "created": 1, "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": _OUTPUT}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}).encode()
            self.send_response(503 if failed else 200)
            self.send_header("Content-Type", "text/event-stream" if body.get("stream") and not failed else "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    directory = tmp_path_factory.mktemp("native-telemetry")
    config = build_litellm_config(load_catalog())
    config["model_list"] = [{"model_name": alias, "model_info": {
        "input_cost_per_token": 0.0 if alias == "zero-cost" else 0.001,
        "output_cost_per_token": 0.0 if alias == "zero-cost" else 0.002,
    }, "litellm_params": {
        "model": "openai/" + model, "api_key": "synthetic-only",
        "api_base": f"http://127.0.0.1:{server.server_port}/v1", "max_retries": 0, "num_retries": 0,
    }} for alias, model in [("openai.gpt-5.4-mini", "gpt-5-mini"), ("zero-cost", "gpt-5-mini"), ("embedding", "text-embedding-3-small"), ("failure", "failure"), ("held", "held")]]
    config_file = directory / "config.json"
    config_file.write_text(json.dumps(config))
    env_file = directory / "gateway.env"
    env_file.write_text(
        "LITELLM_MASTER_KEY=sk-synthetic-telemetry\nLANGFUSE_PUBLIC_KEY=pk-synthetic-only\n"
        "LANGFUSE_SECRET_KEY=sk-synthetic-only\n"
        f"LANGFUSE_OTEL_HOST=http://127.0.0.1:{server.server_port}\n"
        "OTEL_BSP_SCHEDULE_DELAY=200\nOTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false\n"
        "LITELLM_LOCAL_MODEL_COST_MAP=True\nLITELLM_TELEMETRY=False\nDEFAULT_MAX_RETRIES=0\n"
    )
    env_file.chmod(0o600)
    name = "ragweld-native-telemetry-test-" + uuid4().hex[:12]
    state.base_url = f"http://127.0.0.1:{port}"
    state.otlp_host = f"http://127.0.0.1:{server.server_port}"
    try:
        _docker("run", "--detach", "--name", name, "--network", "host", "--memory", "1536m", "--cpus", "1.5",
            "--env-file", str(env_file), "--mount", f"type=bind,src={config_file},dst=/app/telemetry.json,readonly", _IMAGE,
            "--config", "/app/telemetry.json", "--host", "127.0.0.1", "--port", str(port), "--num_workers", "1")
        deadline = time.monotonic() + 90
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    if client.get(state.base_url + "/health/readiness").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                pytest.fail(f"Owned native telemetry gateway did not become ready; inspect {directory / 'gateway.log'}")
        yield state
    finally:
        state.release.set()
        logs = _docker("logs", name, check=False)
        (directory / "gateway.log").write_text(logs.stdout + logs.stderr)
        with state.lock:
            (directory / "exports.pb").write_bytes(b"".join(state.exports))
        _docker("rm", "--force", name, check=False)
        env_file.unlink(missing_ok=True)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_native_generations_join_trace_session_and_export_only_bounded_lane_metrics(native_telemetry: _Telemetry):
    state = native_telemetry
    initial_calls = len(state.calls)
    lanes = ("embedding", "semantic_kg", "figure_description", "schema_proposal")
    sessions = []
    expected_usage = {}
    for lane in lanes:
        if lane == "embedding":
            session = "telemetry-" + uuid4().hex
            sessions.append(session)
            expected_usage[session] = (5, None, 5, 0.005)
            scope = RunCensusScope(RunIdentity(session, "synthetic-corpus", lane), lambda _checkpoint: None,
                trace_headers={"traceparent": f"00-{_TRACE}-{_PARENT}-01"})
            with httpx.Client(transport=CensusTransport(scope), timeout=30, trust_env=False) as client:
                response = client.post(state.base_url + "/v1/embeddings", headers={"Authorization": "Bearer sk-synthetic-telemetry"}, json={"model": "embedding", "input": [_INPUT]})
                assert response.status_code == 200, response.text
                assert response.json()["data"][0]["embedding"] == [0.1, 0.2, 0.3]
            scope.finish_owner()
            assert scope.snapshot().completed_requests == 1
            continue
        for streaming in (False, True):
            session = "telemetry-" + uuid4().hex
            sessions.append(session)
            expected_usage[session] = (5, 3, 8, 0.011)
            scope = RunCensusScope(RunIdentity(session, "synthetic-corpus", lane), lambda _checkpoint: None,
                trace_headers={"traceparent": f"00-{_TRACE}-{_PARENT}-01"})
            with httpx.Client(transport=CensusTransport(scope), timeout=30, trust_env=False) as client:
                body = {"model": "openai.gpt-5.4-mini", "messages": [{"role": "user", "content": _INPUT}], "stream": streaming}
                if streaming:
                    body["stream_options"] = {"include_usage": True}
                response = client.post(state.base_url + "/v1/chat/completions", headers={"Authorization": "Bearer sk-synthetic-telemetry"}, json=body)
                assert response.status_code == 200, response.text
                assert _OUTPUT in response.text
            scope.finish_owner()
            assert scope.snapshot().completed_requests == 1
    zero_session = "telemetry-zero-" + uuid4().hex
    sessions.append(zero_session)
    expected_usage[zero_session] = (5, 3, 8, 0.0)
    scope = RunCensusScope(RunIdentity(zero_session, "synthetic-corpus", "semantic_kg"), lambda _checkpoint: None,
        trace_headers={"traceparent": f"00-{_TRACE}-{_PARENT}-01"})
    with httpx.Client(transport=CensusTransport(scope), timeout=30, trust_env=False) as client:
        response = client.post(state.base_url + "/v1/chat/completions", headers={"Authorization": "Bearer sk-synthetic-telemetry"}, json={"model": "zero-cost", "messages": [{"role": "user", "content": _INPUT}]})
        assert response.status_code == 200
    scope.finish_owner()
    session = "telemetry-failure-" + uuid4().hex
    sessions.append(session)
    scope = RunCensusScope(RunIdentity(session, "synthetic-corpus", "semantic_kg"), lambda _checkpoint: None,
        trace_headers={"traceparent": f"00-{_TRACE}-{_PARENT}-01"})
    with httpx.Client(transport=CensusTransport(scope), timeout=30, trust_env=False) as client:
        response = client.post(state.base_url + "/v1/chat/completions", headers={"Authorization": "Bearer sk-synthetic-telemetry"}, json={"model": "failure", "messages": [{"role": "user", "content": _INPUT}]})
        assert response.status_code == 503
    scope.finish_owner()
    assert scope.snapshot().failed_requests == 1
    deadline = time.monotonic() + 20
    spans = []
    while time.monotonic() < deadline:
        with state.lock:
            exports = list(state.exports)
        spans = [span for raw in exports for resource in ExportTraceServiceRequest.FromString(raw).resource_spans for scoped in resource.scope_spans for span in scoped.spans if span.trace_id.hex() == _TRACE]
        if len(spans) >= len(sessions):
            break
        time.sleep(0.1)
    assert len(spans) == len(sessions), "one native generation per actual request, including failure"
    assert len(state.calls) - initial_calls == len(sessions)
    exported_sessions = []
    for span in spans:
        attributes = {entry.key: entry.value for entry in span.attributes}
        assert span.trace_id.hex() == _TRACE and span.parent_span_id.hex() == _PARENT
        exported_sessions.append(attributes["session.id"].string_value)
        metadata = json.loads(attributes["langfuse.trace.metadata"].string_value)
        assert metadata["lane"] in lanes and metadata["corpus_id"] == "synthetic-corpus"
        assert metadata["run_id"] == attributes["session.id"].string_value
        usage = expected_usage.get(metadata["run_id"])
        if usage is None:
            # Native1.94 reports a zero gateway cost placeholder for failures
            # with no usage. Missing token fields must not become measured zero.
            assert metadata["run_id"] == session
            assert not any(key.startswith("llm.token_count.") for key in attributes)
            assert attributes["llm.cost.total"].double_value == 0.0
        else:
            for key, expected in zip(("prompt", "completion", "total"), usage[:3], strict=True):
                if expected is None:
                    assert f"llm.token_count.{key}" not in attributes
                else:
                    assert attributes[f"llm.token_count.{key}"].int_value == expected
            assert attributes["llm.cost.total"].double_value == pytest.approx(usage[3])
            assert attributes["llm.response.cost"].double_value == pytest.approx(usage[3])
    assert sorted(exported_sessions) == sorted(sessions)
    raw_exports = b"".join(exports)
    assert _INPUT.encode() not in raw_exports and _OUTPUT.encode() not in raw_exports
    with httpx.Client(timeout=5, follow_redirects=True, trust_env=False) as client:
        response = client.get(state.base_url + "/metrics")
        response.raise_for_status()
    metrics = response.text
    native_totals = [sample for family in text_string_to_metric_families(metrics) for sample in family.samples if sample.name == "litellm_proxy_total_requests_metric_total"]
    for lane in lanes:
        assert any(sample.labels.get("metadata_lane") == lane and sample.value > 0 for sample in native_totals), lane
    samples = [line for line in metrics.splitlines() if not line.startswith("#")]
    assert all("metadata_run_id=" not in line and "metadata_corpus_id=" not in line for line in samples)
    assert all(session not in metrics for session in sessions)


def test_pinned_proxy_failure_metrics_do_not_supply_lane_attribution(native_telemetry: _Telemetry):
    """A failure-only model cannot borrow successful samples to prove lane coverage.

    Native1.94's proxy failure/total hooks omit custom metadata labels. This is
    an explicit upstream limitation; use native spend rows/traces for attribution.
    """
    state = native_telemetry
    session = "failure-only-" + uuid4().hex
    scope = RunCensusScope(RunIdentity(session, "synthetic-corpus", "schema_proposal"), lambda _checkpoint: None)
    with httpx.Client(transport=CensusTransport(scope), timeout=30, trust_env=False) as client:
        response = client.post(state.base_url + "/v1/chat/completions", headers={"Authorization": "Bearer sk-synthetic-telemetry"}, json={"model": "failure", "messages": [{"role": "user", "content": _INPUT}]})
        assert response.status_code == 503
    scope.finish_owner()
    with httpx.Client(timeout=5, follow_redirects=True, trust_env=False) as client:
        response = client.get(state.base_url + "/metrics")
        response.raise_for_status()
    samples = [sample for family in text_string_to_metric_families(response.text) for sample in family.samples]
    for name in ("litellm_proxy_failed_requests_metric_total", "litellm_proxy_total_requests_metric_total"):
        failures = [sample for sample in samples if sample.name == name and sample.labels.get("requested_model") == "failure" and sample.value > 0]
        assert failures, name
        assert all(sample.labels.get("metadata_lane") in (None, "", "None") for sample in failures)


@pytest.mark.asyncio
async def test_cancelled_caller_keeps_native_trace_until_held_provider_settles(native_telemetry: _Telemetry):
    from server.observability.run_census import CensusAsyncTransport

    state = native_telemetry
    session = "cancelled-" + uuid4().hex
    trace_id = "3" * 32
    scope = RunCensusScope(RunIdentity(session, "synthetic-corpus", "semantic_kg"), lambda _checkpoint: None,
        trace_headers={"traceparent": f"00-{trace_id}-{_PARENT}-01"})
    async with httpx.AsyncClient(transport=CensusAsyncTransport(scope), timeout=20, trust_env=False) as client:
        task = asyncio.create_task(client.post(state.base_url + "/v1/chat/completions", headers={"Authorization": "Bearer sk-synthetic-telemetry"}, json={"model": "held", "messages": [{"role": "user", "content": _INPUT}]}))
        assert await asyncio.to_thread(state.held.wait, 5)
        assert scope.snapshot().inflight == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        scope.finish_owner()
        assert scope.snapshot().uncertain_requests == 1
        state.release.set()
    deadline = time.monotonic() + 20
    matched = []
    while time.monotonic() < deadline:
        with state.lock:
            exports = list(state.exports)
        matched = [span for raw in exports for resource in ExportTraceServiceRequest.FromString(raw).resource_spans for scoped in resource.scope_spans for span in scoped.spans if span.trace_id.hex() == trace_id]
        if matched:
            break
        await asyncio.sleep(0.1)
    assert len(matched) == 1
    attrs = {entry.key: entry.value for entry in matched[0].attributes}
    assert attrs["session.id"].string_value == session
    assert matched[0].parent_span_id.hex() == _PARENT
    assert _INPUT.encode() not in matched[0].SerializeToString()
    assert _OUTPUT.encode() not in matched[0].SerializeToString()
    assert attrs["llm.token_count.prompt"].int_value == 5
    assert attrs["llm.token_count.completion"].int_value == 3
    assert attrs["llm.token_count.total"].int_value == 8
    assert attrs["llm.cost.total"].double_value == pytest.approx(0.011)


def test_app_sdk_and_native_gateway_export_one_generation_per_request(native_telemetry: _Telemetry):
    state = native_telemetry
    program = r'''
import asyncio, json, sys
from server.chat.generation import generate_chat_text, stream_chat_text
from server.chat.provider_router import ProviderRoute
from server.gateway_catalog import warm_gateway_catalog
from server.models.tribrid_config_model import TriBridConfig
from server.observability.runtime import start_request_observation
warm_gateway_catalog()
cfg=TriBridConfig()
cfg.tracing.tracing_mode="local"
cfg.tracing.otel_export_enabled=True
cfg.tracing.otlp_endpoint=sys.argv[2]+"/api/public/otel/v1/traces"
cfg.tracing.langfuse_enabled=True
cfg.tracing.langfuse_base_url=sys.argv[2]
cfg.tracing.langfuse_public_base_url=sys.argv[2]
cfg.tracing.langfuse_project="fixture-project"
route=ProviderRoute(kind="litellm",provider_name="LiteLLM",model="openai.gpt-5.4-mini",base_url=sys.argv[1]+"/v1",api_key="sk-synthetic-telemetry")
async def main():
 traces=[]
 for stream in (False, True):
  with start_request_observation(config=cfg,route_name="telemetry.fixture",path="/fixture",method="POST",run_id="app-native-fixture",repo_id="synthetic-corpus") as obs:
   assert obs is not None and obs.manager.langfuse_client is not None
   kw=dict(route=route,system_prompt=sys.argv[3],user_message="Synthetic telemetry request",images=[],temperature=1.0,max_tokens=32,context_chunks=[])
   text="".join([part async for part in stream_chat_text(**kw)]) if stream else (await generate_chat_text(**kw)).text
   assert text==sys.argv[4] and obs.cost_summary is not None
   assert any(link.kind=="langfuse" and link.url.endswith(obs.trace_id) for link in obs.links)
   traces.append(obs.trace_id)
  obs.manager.tracer_provider.force_flush()
  obs.manager.langfuse_client.flush()
 print(json.dumps(traces))
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, "-c", program, state.base_url, state.otlp_host, _INPUT, _OUTPUT],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "LANGFUSE_PUBLIC_KEY": "pk-synthetic-only", "LANGFUSE_SECRET_KEY": "sk-synthetic-only",
            "RAGWELD_LOAD_DOTENV": "0", "LANGFUSE_TRACING_ENABLED": "true"},
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    trace_ids = json.loads(result.stdout.splitlines()[-1])
    deadline = time.monotonic() + 20
    matched = []
    while time.monotonic() < deadline:
        with state.lock:
            exports = list(state.exports)
        matched = [span for raw in exports for resource in ExportTraceServiceRequest.FromString(raw).resource_spans for scoped in resource.scope_spans for span in scoped.spans if span.trace_id.hex() in trace_ids]
        if len(matched) >= 6:
            break
        time.sleep(0.1)
    for trace_id in trace_ids:
        joined = [span for span in matched if span.trace_id.hex() == trace_id]
        assert len(joined) == 3, "one request root, one transport stage, one native generation"
        assert sum(any(attr.key == "llm.model_name" for attr in span.attributes) for span in joined) == 1
        native = next(span for span in joined if any(attr.key == "llm.model_name" for attr in span.attributes))
        attrs = {entry.key: entry.value for entry in native.attributes}
        assert attrs["llm.token_count.prompt"].int_value == 5
        assert attrs["llm.token_count.completion"].int_value == 3
        assert attrs["llm.token_count.total"].int_value == 8
        assert attrs["llm.cost.total"].double_value == pytest.approx(0.011)
    serialized = b"".join(span.SerializeToString() for span in matched)
    assert _INPUT.encode() not in serialized and _OUTPUT.encode() not in serialized
