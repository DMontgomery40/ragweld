from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from neo4j_graphrag.components.schema import GraphSchema, NodeType, PropertyType
from neo4j_graphrag.components.types import TextChunk, TextChunks
from neo4j_graphrag.exceptions import LLMGenerationError

from server.indexing.graphrag_pipeline import (
    SemanticPipeline,
    semantic_entity_relation_extractor,
    semantic_extraction_llm,
)
from server.indexing.graphrag_schema import derive_graph_schema_proposal
from server.models.index import Chunk
from server.models.run_accounting import RunRequestCensus
from server.observability.run_census import RunCensusScope, RunIdentity


@pytest.fixture
def census_gateway():
    received: list[dict] = []
    second_arrival = threading.Event()
    held = threading.Event()
    failed = threading.Event()
    release_failure = threading.Event()
    release = threading.Event()
    state = {"mode": "valid"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append({"payload": payload, "headers": dict(self.headers)})
            if len(received) >= 2:
                second_arrival.set()
            text = json.dumps(payload)
            status = 200
            if state["mode"].startswith("recover-") and len(received) == 1:
                status = int(state["mode"].removeprefix("recover-"))
            if state["mode"] == "failure-held":
                if "chunk-fail" in text:
                    failed.set()
                    release_failure.wait(5)
                    status = 400
                else:
                    held.set()
                    release.wait(5)
            if state["mode"] == "held":
                held.set()
                release.wait(5)
            if state["mode"] == "timeout" and len(received) == 1:
                held.set()
                release.wait(5)
            content = {"nodes": [{"id": "thing", "label": "Thing", "properties": {"name": "Thing"}}], "relationships": []}
            if state["mode"] == "schema":
                content = {"node_types": [{"label": "Thing", "properties": [{"name": "name", "type": "STRING"}]}], "relationship_types": [{"label": "CONNECTS"}], "patterns": [{"source": "Thing", "relationship": "CONNECTS", "target": "Thing"}], "constraints": []}
            body = json.dumps({"id": "fixture", "object": "chat.completion", "created": 1,
                "model": "openai.gpt-5.6-sol", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 6, "total_tokens": 14}}
                if status == 200 else {"error": {"message": "synthetic rejection", "type": "rate_limit"}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("retry-after", "0.01")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", received, state, held, failed, release_failure, second_arrival
    finally:
        release.set()
        release_failure.set()
        server.shutdown()
        server.server_close()
        thread.join(5)


def scope_for(lane="semantic_kg"):
    history = []

    def persist(checkpoint):
        history.append(RunRequestCensus.model_validate(asdict(checkpoint)))

    return RunCensusScope(RunIdentity("a" * 32, "synthetic", lane), persist), history


def route(base):
    return dict(route_model="openai.gpt-5.6-sol", route_base_url=base,
                route_api_key="synthetic-only", route_upstream="openrouter/openai/gpt-5.6-sol",
                reasoning_effort="low")


def assert_headers(received, lane):
    for row in received:
        headers = row["headers"]
        assert headers["x-litellm-session-id"] == "a" * 32
        assert headers["x-litellm-trace-id"] == "a" * 32
        assert json.loads(headers["x-litellm-spend-logs-metadata"]) == {
            "run_id": "a" * 32, "corpus_id": "synthetic", "lane": lane,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["sync", "async"])
@pytest.mark.parametrize("with_census", [False, True])
@pytest.mark.parametrize(
    "mode",
    ["valid", "recover-408", "recover-409", "recover-429", "recover-500", "recover-502", "recover-503", "recover-504", "timeout"],
)
async def test_official_kg_clients_count_actual_sync_async_and_sdk_retry_attempts(
    census_gateway, mode, method, with_census,
):
    """One invocation dispatches once, including transient failures and unknown timeout outcomes."""
    base, received, state, *_ = census_gateway
    state["mode"] = mode
    scope, history = scope_for()
    llm = semantic_extraction_llm(
        **route(base), llm_timeout_s=1 if mode == "timeout" else 3,
        census_scope=scope if with_census else None,
    )
    prompt = "Extract the observatory sensor and its calibration relationship."
    try:
        if mode == "valid":
            if method == "sync":
                result = await asyncio.to_thread(llm.invoke, prompt)
            else:
                result = await llm.ainvoke(prompt)
            assert "Thing" in result.content
        else:
            # The server would succeed on a second dispatch. Neither the SDK
            # nor Neo4j's separate rate-limit handler may hide this first error.
            with pytest.raises(LLMGenerationError):
                if method == "sync":
                    await asyncio.to_thread(llm.invoke, prompt)
                else:
                    await llm.ainvoke(prompt)
    finally:
        await llm.aclose()
        scope.finish_owner()
    assert len(received) == 1
    checkpoint = history[-1]
    assert checkpoint.state == "closed"
    assert checkpoint.active_producers == checkpoint.inflight == 0
    assert checkpoint.started_requests == checkpoint.completed_requests == int(with_census)
    assert checkpoint.failed_requests == int(with_census and mode.startswith("recover-"))
    assert checkpoint.uncertain_requests == int(with_census and mode == "timeout")
    assert llm.client.is_closed() and llm.async_client.is_closed()
    if with_census:
        assert_headers(received, "semantic_kg")
    else:
        assert all("x-litellm-session-id" not in row["headers"] for row in received)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["failure-held", "held", "close"])
async def test_kg_failure_and_cancellation_drain_held_and_queued_extraction(census_gateway, mode):
    from server.indexing.graphrag_pipeline import close_semantic_pipeline

    base, received, state, held, failed, release_failure, second_arrival = census_gateway
    state["mode"] = "held" if mode == "close" else mode
    scope, history = scope_for()
    llm = semantic_extraction_llm(**route(base), llm_timeout_s=3, census_scope=scope)
    extractor = semantic_entity_relation_extractor(
        llm=llm, max_concurrency=2, prompt_template="{schema}\n{text}\n{examples}",
        census_scope=scope,
    )
    pipeline = SemanticPipeline(llm, extractor)
    chunks = TextChunks(chunks=[TextChunk(index=i, text=text) for i, text in enumerate(["chunk-held", "chunk-fail", "chunk-queued"])])
    schema = GraphSchema(node_types=(NodeType(label="Thing", properties=(PropertyType(name="name", type="STRING"),)),))
    task = asyncio.create_task(extractor.run(chunks=chunks, schema=schema))
    try:
        assert await asyncio.to_thread(held.wait, 5)
        # Two running requests and one queued chunk are the scenario under test.
        # One server arrival alone does not establish that the second was sent.
        assert await asyncio.to_thread(second_arrival.wait, 5)
        if mode == "failure-held":
            assert await asyncio.to_thread(failed.wait, 5)
        scope.finish_owner()
        assert history[-1].state == "open" and history[-1].active_producers > 0
        if mode == "failure-held":
            release_failure.set()
            with pytest.raises(LLMGenerationError):
                await asyncio.wait_for(task, 3)
        else:
            if mode == "close":
                await close_semantic_pipeline(pipeline)
            else:
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await close_semantic_pipeline(pipeline)
        checkpoint = history[-1]
        assert checkpoint.state == "closed"
        assert checkpoint.active_producers == checkpoint.inflight == 0
        assert checkpoint.started_requests == checkpoint.completed_requests
        assert checkpoint.started_requests >= len(received) >= 2
        assert checkpoint.uncertain_requests >= 1
        assert checkpoint.failed_requests == (1 if mode == "failure-held" else 0)
        assert extractor.llm.client.is_closed() and extractor.llm.async_client.is_closed()
        assert_headers(received, "semantic_kg")
    finally:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        await close_semantic_pipeline(pipeline)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_schema_dispatch_keeps_budget_and_retains_producer_until_cleanup(census_gateway, cancel):
    base, received, state, held, *_ = census_gateway
    state["mode"] = "held" if cancel else "schema"
    scope, history = scope_for("schema_proposal")
    task = asyncio.create_task(derive_graph_schema_proposal(
        corpus_id="synthetic", chunks=[Chunk(chunk_id="c", file_path="x.md", start_line=1,
            end_line=1, content="A synthetic thing.", token_count=4)],
        model_alias="openai.gpt-5.6-sol", **route(base), input_fingerprint="b" * 64,
        timeout_s=3, max_output_tokens=128, census_scope=scope))
    if cancel:
        assert await asyncio.to_thread(held.wait, 5)
        scope.finish_owner()
        assert history[-1].active_producers > 0 and history[-1].state == "open"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result.corpus_id == "synthetic"
        scope.finish_owner()
    checkpoint = history[-1]
    assert checkpoint.state == "closed"
    assert checkpoint.active_producers == checkpoint.inflight == 0
    assert checkpoint.started_requests == checkpoint.completed_requests == len(received) == 1
    assert checkpoint.uncertain_requests == int(cancel)
    assert_headers(received, "schema_proposal")
    assert received[0]["payload"]["max_tokens"] == 128


@pytest.mark.asyncio
@pytest.mark.parametrize("with_census", [False, True])
async def test_official_extractor_reuses_clients_across_files_and_closes_explicitly(census_gateway, with_census):
    from server.indexing.graphrag_pipeline import close_semantic_pipeline

    base, received, *_ = census_gateway
    scope, history = scope_for()
    llm = semantic_extraction_llm(**route(base), llm_timeout_s=3,
                                  census_scope=scope if with_census else None)
    extractor = semantic_entity_relation_extractor(
        llm=llm, max_concurrency=1, prompt_template="{schema}\n{text}",
        census_scope=scope if with_census else None,
    )
    pipeline = SemanticPipeline(llm, extractor)
    schema = GraphSchema(node_types=(NodeType(label="Thing", properties=(PropertyType(name="name", type="STRING"),)),))
    try:
        for index in range(2):
            result = await extractor.run(chunks=TextChunks(chunks=[TextChunk(index=index, text="Synthetic thing")]), schema=schema)
            assert any(node.label == "Thing" for node in result.nodes)
            assert not llm.async_client.is_closed()
            if with_census:
                assert history[-1].active_producers == history[-1].inflight == 0
                assert history[-1].state == "open"
    finally:
        await close_semantic_pipeline(pipeline)
    scope.finish_owner()
    assert llm.client.is_closed() and llm.async_client.is_closed()
    assert len(received) == 2
    assert history[-1].started_requests == (2 if with_census else 0)
    if with_census:
        assert_headers(received, "semantic_kg")
    else:
        assert all("x-litellm-session-id" not in row["headers"] for row in received)
    with pytest.raises(RuntimeError, match="closed"):
        await extractor.run(chunks=TextChunks(chunks=[]), schema=schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("component", ["kg", "schema"])
@pytest.mark.parametrize("mismatch", ["corpus", "lane", "session"])
async def test_census_identity_is_checked_before_graph_driver_or_gateway_use(census_gateway, component, mismatch):
    from server.indexing.graphrag_pipeline import build_semantic_pipeline

    base, received, *_ = census_gateway
    expected_lane = "semantic_kg" if component == "kg" else "schema_proposal"
    identity = RunIdentity(
        "b" * 32 if mismatch == "session" else "a" * 32,
        "other" if mismatch == "corpus" else "synthetic",
        "embedding" if mismatch == "lane" else expected_lane,
    )
    scope = RunCensusScope(identity, lambda _checkpoint: None)
    if component == "kg":
        with pytest.raises(ValueError, match="census"):
            build_semantic_pipeline(
                driver=object(), neo4j_database="neo4j",
                repo_id="__staging__synthetic__" + "a" * 32, run_id="a" * 32,
                **route(base), max_concurrency=1, llm_timeout_s=3,
                prompt_template="{schema} {text}", census_scope=scope,
            )
    elif mismatch != "session":
        # Proposal functions have no independent run-id argument; the caller owns
        # that identity. Corpus and lane remain independently checkable here.
        with pytest.raises(ValueError, match="census"):
            await derive_graph_schema_proposal(
                corpus_id="synthetic", chunks=[], model_alias="openai.gpt-5.6-sol",
                **route(base), input_fingerprint="b" * 64, timeout_s=3,
                max_output_tokens=128, census_scope=scope,
            )
    else:
        with pytest.raises(ValueError, match="nonempty chunk"):
            await derive_graph_schema_proposal(
                corpus_id="synthetic", chunks=[], model_alias="openai.gpt-5.6-sol",
                **route(base), input_fingerprint="b" * 64, timeout_s=3,
                max_output_tokens=128, census_scope=scope,
            )
    assert received == []
