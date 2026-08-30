"""A streaming route's span must survive the hand-off into the response task.

`StreamingResponse` iterates its body in its own anyio task with a COPY of the context
(uvicorn advertises ASGI `spec_version` 2.3, so Starlette takes the task-group branch, and
`httpx.ASGITransport` sends no spec_version at all, which takes the same branch). The
streaming endpoints entered the request observation in the endpoint coroutine and left it
from inside the generator, so every streamed request logged

    ERROR Failed to detach context
    ValueError: <Token var=<ContextVar name='current_context' ...>> was created in a
                different Context

from `opentelemetry/context/__init__.py`. `context.detach` swallows the `ValueError` after
logging it, so the span itself still ended -- the damage is an ERROR-level traceback per
streamed request on an entirely successful code path, which is what made `journalctl` on
LXC100 unreadable and buries the failures an operator is actually looking for.

The first test is the defect. The second pins what the fix must not break while moving the
attach/detach: the span still ends exactly once and still parents the retrieval stages.

Both drive the real ASGI app over the real Starlette/anyio hand-off with the real
OpenTelemetry SDK and the real `logging` module. Nothing is stubbed: the span is read back
from an in-memory exporter attached to the tracer provider the endpoint actually uses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any, cast

import pytest
from httpx import AsyncClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig
from server.observability.runtime import (
    get_observability_manager,
    stage_span_detached,
    start_streaming_observation,
)
from server.retrieval.qdrant_store import QdrantChunkStore

# The service markers are per test, not on the module: the last test is a pure
# asyncio/OpenTelemetry probe and must run wherever the suite runs, services or not.

OTEL_CONTEXT_LOGGER = "opentelemetry.context"
DETACH_FAILURE = "Failed to detach context"


def _traced_local_config() -> TriBridConfig:
    """Tracing on, exporters off: a real tracer and real spans, no network."""
    cfg = load_config()
    cfg.tracing.tracing_enabled = True
    cfg.tracing.tracing_mode = "local"
    cfg.tracing.otel_export_enabled = False
    cfg.tracing.langfuse_enabled = False
    # No provider routing, so the stream is retrieval-only and costs nothing.
    cfg.chat.litellm.enabled = False
    return cfg


@pytest.fixture
def exported_spans() -> Iterator[InMemorySpanExporter]:
    """Read spans back off the very tracer provider the endpoint will use."""
    manager = get_observability_manager(_traced_local_config())
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    manager.tracer_provider.add_span_processor(processor)
    try:
        yield exporter
    finally:
        processor.shutdown()


async def _seed_corpus(pg: PostgresClient, repo_id: str, cfg: TriBridConfig) -> None:
    await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
    await pg.upsert_corpus_config_json(repo_id, cfg.model_dump(mode="serialization"))
    chunk = Chunk(
        chunk_id="c1",
        content="login controller handles authentication",
        file_path="src/auth/login_controller.py",
        start_line=1,
        end_line=1,
        language="python",
        token_count=5,
        embedding=None,
        summary=None,
        metadata={"kind": "unit_test"},
    )
    await pg.upsert_chunks(repo_id, [chunk])
    await QdrantChunkStore(cfg).upsert_chunks(
        repo_id, [chunk], embedding_dim=int(cfg.embedding.embedding_dim), pg=pg
    )


async def _drop_corpus(pg: PostgresClient, repo_id: str, cfg: TriBridConfig) -> None:
    try:
        await QdrantChunkStore(cfg).delete_corpus(repo_id)
    except Exception:
        pass
    try:
        await pg.delete_corpus(repo_id)
    except Exception:
        pass


async def _stream_answer(client: AsyncClient, repo_id: str) -> list[dict[str, object]]:
    response = await client.post(
        "/api/answer/stream",
        json={
            "query": "login controller",
            "repo_id": repo_id,
            "top_k": 5,
            "include_vector": False,
            "include_sparse": True,
            "include_graph": False,
        },
    )
    assert response.status_code == 200, response.text
    payloads: list[dict[str, object]] = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            payloads.append(json.loads(line[len("data: ") :]))
    return payloads


@contextmanager
def request_scope(streaming: object) -> Iterator[None]:
    """Hold the request observation current for this task, without ending its span."""
    with cast(Any, streaming).scope():
        yield


def _root_spans(exporter: InMemorySpanExporter, name: str) -> list[ReadableSpan]:
    return [span for span in exporter.get_finished_spans() if span.name == name]


@pytest.fixture
async def seeded_corpus(exported_spans: InMemorySpanExporter) -> AsyncIterator[str]:
    del exported_spans  # ordering only: the exporter is attached before the request runs
    cfg = _traced_local_config()
    repo_id = f"test_stream_ctx_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await _seed_corpus(pg, repo_id, cfg)
        yield repo_id
    finally:
        await _drop_corpus(pg, repo_id, cfg)


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
async def test_a_streamed_answer_detaches_its_span_context_in_the_task_that_attached_it(
    client: AsyncClient,
    seeded_corpus: str,
    exported_spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reported defect: one `Failed to detach context` per streamed request."""
    with caplog.at_level(logging.ERROR, logger=OTEL_CONTEXT_LOGGER):
        payloads = await _stream_answer(client, seeded_corpus)

    assert payloads, "the stream produced no SSE payloads"

    detach_failures = [
        record
        for record in caplog.records
        if record.name == OTEL_CONTEXT_LOGGER and DETACH_FAILURE in record.getMessage()
    ]
    assert not detach_failures, [record.getMessage() for record in detach_failures]


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
async def test_a_streamed_answer_ends_its_root_span_exactly_once(
    client: AsyncClient,
    seeded_corpus: str,
    exported_spans: InMemorySpanExporter,
) -> None:
    """The regression guard on the fix, not the defect: this already held before it.

    Moving the attach and detach into the task that owns each half of the request must not
    change what reaches Tempo: one root span for the streamed request, ended, carrying the
    route attributes, with the retrieval stages under it rather than beside it.
    """
    await _stream_answer(client, seeded_corpus)

    roots = _root_spans(exported_spans, "ragweld.answer_stream")
    assert len(roots) == 1, [span.name for span in exported_spans.get_finished_spans()]

    root = roots[0]
    assert root.end_time is not None
    assert root.attributes is not None
    assert root.attributes.get("http.route") == "/api/answer/stream"
    assert root.attributes.get("ragweld.route_name") == "answer_stream"
    assert root.attributes.get("ragweld.repo_id") == seeded_corpus

    # The retrieval stages ran under the streamed request, not orphaned beside it: the whole
    # point of keeping one span open across the two tasks.
    children = [
        span
        for span in exported_spans.get_finished_spans()
        if span.parent is not None and span.parent.span_id == root.context.span_id
    ]
    assert children, [span.name for span in exported_spans.get_finished_spans()]


@pytest.mark.asyncio
async def test_a_detached_stage_span_survives_a_generator_resuming_in_another_task(
    exported_spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The second half of the defect, in isolation: `generation.gateway_stream`.

    That block stays open across a `yield`, and the streamed generator is primed by the
    endpoint coroutine and then driven by the response's own task. Both tasks are real here
    and the second one gets a real copy of the first one's context, exactly as anyio's
    `start_soon` hands one over.
    """
    streaming = start_streaming_observation(
        config=_traced_local_config(),
        route_name="stage_span_probe",
        path="/api/answer/stream",
        method="POST",
    )
    assert streaming.observation is not None

    async def _emit() -> AsyncIterator[str]:
        with stage_span_detached("generation.gateway_stream", model="probe"):
            yield "first"
            yield "second"

    with caplog.at_level(logging.ERROR, logger=OTEL_CONTEXT_LOGGER):
        with request_scope(streaming):
            generator = _emit()
            primed = await anext(generator)

            async def _drain() -> list[str]:
                return [chunk async for chunk in generator]

            # A fresh task, so its context is a COPY: a token attached above cannot be reset
            # here. Swapping `stage_span_detached` back for `stage_span` fails right here.
            rest = await asyncio.create_task(_drain())

    streaming.finish()

    detach_failures = [
        record
        for record in caplog.records
        if record.name == OTEL_CONTEXT_LOGGER and DETACH_FAILURE in record.getMessage()
    ]
    assert not detach_failures, [record.getMessage() for record in detach_failures]
    assert [primed, *rest] == ["first", "second"]
    stage = [span for span in exported_spans.get_finished_spans() if span.name == "generation.gateway_stream"]
    assert len(stage) == 1, [span.name for span in exported_spans.get_finished_spans()]
    assert stage[0].parent is not None
    assert stage[0].parent.span_id == streaming.observation.span.get_span_context().span_id
