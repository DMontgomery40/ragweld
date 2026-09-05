"""Real HTTP/SDK contracts for generation and benchmark token/cost accounting."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from server.chat.benchmark_runner import run_benchmark
from server.chat.generation import GatewayContentMissingError, generate_chat_text, stream_chat_text
from server.chat.provider_router import ProviderRoute
from server.gateway_catalog import warm_gateway_catalog
from server.models.tribrid_config_model import TriBridConfig
from server.observability.runtime import start_request_observation

QUESTION = "How often is the salinity sensor calibrated?"
USAGE = {
    "prompt_tokens": 100,
    "completion_tokens": 20,
    "total_tokens": 120,
    "prompt_tokens_details": {"cached_tokens": 80},
    "completion_tokens_details": {"reasoning_tokens": 12},
}
COST = 0.0000001234


@contextmanager
def accounting_gateway(mode: str) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            usage = dict(USAGE)
            billed = mode not in {"missing", "mixed", "provisional"} or request["model"] == "openai.gpt-5.6-luna"
            if mode == "failed" and request["model"] != "openai.gpt-5.6-luna":
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if billed and mode != "header":
                usage["cost"] = 0.0 if mode == "zero" else COST
            content = None if mode == "reasoning" else "The salinity sensor is calibrated every 30 days."
            if request["stream"]:
                chunks = [
                    {"choices": [{"delta": {"content": content}, "finish_reason": "length" if content is None else "stop"}]},
                    {"choices": [], "usage": usage},
                    # A final event without a cost must not erase the reported value.
                    {"choices": [], "usage": dict(USAGE)},
                ]
                if mode == "provisional":
                    chunks.insert(0, {"choices": [{"delta": {"role": "assistant"}}], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cost": 42.0}})
                body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
            else:
                body = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "length" if content is None else "stop"}], "usage": usage}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if request["stream"] else "application/json")
            if mode in {"header", "misleading_header"}:
                self.send_header("x-litellm-response-cost", str(COST if mode == "header" else 42.0))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def accounting_config() -> TriBridConfig:
    warm_gateway_catalog()
    cfg = TriBridConfig()
    cfg.tracing.tracing_enabled = True
    cfg.tracing.tracing_mode = "local"
    cfg.tracing.otel_export_enabled = False
    cfg.tracing.langfuse_enabled = False
    cfg.chat.litellm.enabled = True
    cfg.chat.benchmark.max_concurrent_models = 2
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("mode", ["usage", "header", "misleading_header", "provisional", "zero", "missing", "reasoning"])
async def test_generation_preserves_reported_cost_and_counts_tokens_once(accounting_config: TriBridConfig, stream: bool, mode: str) -> None:
    exporter = InMemorySpanExporter()
    with start_request_observation(config=accounting_config, route_name="accounting", path="/accounting", method="POST") as obs:
        assert obs is not None
        previous_client = obs.manager.langfuse_client
        client = Langfuse(public_key=f"pk-accounting-{uuid.uuid4().hex}", secret_key="sk-accounting", tracer_provider=obs.manager.tracer_provider, span_exporter=exporter)
        obs.manager.langfuse_client = client
        try:
            with accounting_gateway(mode) as base_url:
                kwargs = dict(route=ProviderRoute(kind="litellm", provider_name="LiteLLM", base_url=base_url, model="ragweld-local", api_key="accounting-key"), system_prompt="Answer from the sensor calibration manual.", user_message=QUESTION, images=[], temperature=0, max_tokens=64, context_chunks=[])
                error = None
                try:
                    if stream:
                        assert "salinity" in "".join([part async for part in stream_chat_text(**kwargs)])
                    else:
                        result = await generate_chat_text(**kwargs)
                        assert result.usage is not None and result.usage["total_tokens"] == 120
                except GatewayContentMissingError as exc:
                    error = exc
                assert (error is not None) == (mode == "reasoning")
                summary = obs.cost_summary
                assert summary is not None
                assert (summary.input_tokens, summary.output_tokens, summary.total_tokens) == (100, 20, 120)
                # Streaming headers precede inference completion. Only a terminal
                # body charge is evidence of the completed stream's actual cost.
                estimated = mode in {"missing", "provisional"} or (stream and mode == "header")
                assert summary.cost_source == ("catalog" if estimated else "provider")
                assert summary.authoritative is not estimated
                assert summary.estimated_cost_usd == (0.0 if estimated or mode == "zero" else COST)
                if error:
                    assert error.cost_summary == summary
            client.flush()
            spans = [span for span in exporter.get_finished_spans() if span.attributes and span.attributes.get("langfuse.observation.type") == "generation"]
            assert len(spans) == 1
            attrs = spans[0].attributes
            assert attrs is not None
            assert json.loads(str(attrs["langfuse.observation.usage_details"])) == {"input": 100, "output": 20, "total": 120}
            assert json.loads(str(attrs["langfuse.observation.cost_details"])) == {"total": summary.estimated_cost_usd}
        finally:
            obs.manager.langfuse_client = previous_client
            client.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["usage", "mixed", "failed", "reasoning"])
@pytest.mark.parametrize("corpus_scoped", [False, True])
async def test_benchmark_persists_each_call_and_aggregates_without_last_writer_winning(accounting_config: TriBridConfig, tmp_path: Path, mode: str, corpus_scoped: bool) -> None:
    cfg = accounting_config
    cfg.chat.benchmark.save_results = True
    cfg.chat.benchmark.results_path = str(tmp_path)
    env_keys = ("LITELLM_API_KEY", "LITELLM_BASE_URL")
    previous = {key: os.environ.get(key) for key in env_keys}
    try:
        with accounting_gateway(mode) as base_url, start_request_observation(config=cfg, route_name="benchmark", path="/api/benchmark/run", method="POST") as obs:
            os.environ.update(LITELLM_API_KEY="accounting-key", LITELLM_BASE_URL=base_url)
            result = await run_benchmark(prompt=QUESTION, models=["openai.gpt-5.6-luna", "openai.gpt-5.4-mini"], config=cfg, repo_id="accounting-corpus" if corpus_scoped else None)
            assert obs is not None
            first, second = result.results
            assert first.usage is not None and first.usage["total_tokens"] == 120
            assert first.cost_summary is not None and first.cost_summary.estimated_cost_usd == COST
            aggregate = result.cost_summary
            assert aggregate is not None
            assert result.cost_scope == "generation"
            assert "Answer generation only" in str(aggregate.detail)
            if corpus_scoped:
                assert obs.cost_summary is not None
                assert obs.cost_summary.estimated_cost_usd is None
                assert obs.cost_summary.total_tokens is None
                assert obs.cost_summary.cost_source == "unavailable"
                assert not obs.cost_summary.authoritative
                assert "shared retrieval lacks complete accounting" in str(obs.cost_summary.detail)
            else:
                assert obs.cost_summary == aggregate
            if mode == "failed":
                assert second.error and second.cost_summary is None and second.usage is None
                assert aggregate.estimated_cost_usd is None and aggregate.cost_source == "unavailable"
                assert aggregate.total_tokens is None
            else:
                assert second.cost_summary is not None
                assert aggregate.total_tokens == 240
                assert aggregate.estimated_cost_usd == pytest.approx(COST + second.cost_summary.estimated_cost_usd)
                assert aggregate.authoritative == (mode != "mixed")
                assert aggregate.cost_source == ("catalog" if mode == "mixed" else "provider")
                assert bool(second.error) == (mode == "reasoning")
            saved = json.loads((tmp_path / f"{result.run_id}.json").read_text())
            assert saved["cost_scope"] == "generation"
            assert saved["cost_summary"] == aggregate.model_dump(mode="json")
            assert saved["results"][0]["usage"]["total_tokens"] == 120
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
