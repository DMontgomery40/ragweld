"""The semantic KG time estimate is per gateway round-trip, calibrated from the last run.

Task 8 drive finding D13: the Start-indexing dialog quoted "~12 min" for the Epstein rebuild
(3,126 chunks, 4 workers) whose previous execution took 2 h 07 min. The estimator modelled one
extraction call per second per worker; Luna at medium effort answers one chunk in roughly ten
seconds through the gateway. Two things fix that for good: a measured rate carried on the run
record (worker-seconds spent inside the extraction calls, divided by the chunks they covered)
that the next estimate for the same alias reuses, and a default that reflects a reasoning
model's real round-trip when no measurement exists.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import threading
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import permutations
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from neo4j_graphrag.components.schema import GraphSchema, NodeType, PropertyType
from neo4j_graphrag.components.types import Neo4jGraph

import server.api.index as index_api
from server.api.index import (
    _SEMANTIC_KG_SECONDS_PER_CHUNK_DEFAULT,
    _estimate_semantic_kg_seconds,
    _measured_semantic_kg_seconds_per_chunk,
    _semantic_kg_seconds_assumption,
)
from server.chat.prompt_budget import count_tokens
from server.gateway_catalog import warm_gateway_catalog
from server.models.index import (
    GraphExtractionTelemetry,
    GraphGenerationMetadata,
    GraphResolutionTelemetry,
    IndexRunSummary,
)
from server.models.run_accounting import IndexRunAccounting, RunCostIdentity, RunRequestCensus
from server.models.tribrid_config_model import TriBridConfig
from server.observability.gateway_costs import NativeSpendRow

EPSTEIN_CHUNKS = 3126
EPSTEIN_WORKERS = 4
EPSTEIN_WALL_SECONDS = 7654.0  # run ca5b8d92: 21:46:27 -> 23:54:01 UTC
LUNA = "openai.gpt-5.6-luna"


def _run(
    *,
    policy: str = "semantic",
    alias: str = LUNA,
    worker_seconds: float = 31_260.0,
    succeeded: int = EPSTEIN_CHUNKS,
    status: str = "complete",
) -> IndexRunSummary:
    extraction = GraphExtractionTelemetry(
        selected_chunks=succeeded,
        attempted_chunks=succeeded,
        succeeded_chunks=succeeded,
        failed_chunks=0,
        truncated_chunks=0,
        extracted_entities=10,
        semantic_relationships=5,
        from_chunk_relationships=10,
        llm_model_alias=alias,
        workers=EPSTEIN_WORKERS,
        worker_seconds=worker_seconds,
    )
    return IndexRunSummary(
        run_id="ca5b8d92938f4f00a9e0b5ff8f63ce22",
        repo_id="epstein-files-public",
        status=status,  # type: ignore[arg-type]
        started_at=datetime(2026, 9, 1, 21, 46, 27, tzinfo=UTC),
        completed_at=datetime(2026, 9, 1, 23, 54, 1, tzinfo=UTC),
        progress=1.0,
        total_chunks=succeeded,
        graph_metadata=GraphGenerationMetadata(
            policy=policy,  # type: ignore[arg-type]
            extraction=extraction,
            resolution=GraphResolutionTelemetry(
                candidate_nodes=10, resolved_nodes=10, merged_nodes=0, unresolved_duplicate_groups=0
            ),
        ),
    )


def test_telemetry_carries_the_measurement_and_defaults_to_unmeasured() -> None:
    bare = GraphExtractionTelemetry(
        selected_chunks=0,
        attempted_chunks=0,
        succeeded_chunks=0,
        failed_chunks=0,
        truncated_chunks=0,
        extracted_entities=0,
        semantic_relationships=0,
        from_chunk_relationships=0,
    )
    assert bare.llm_model_alias == ""
    assert bare.workers == 0
    assert bare.worker_seconds == 0.0


def test_default_rate_reflects_a_reasoning_models_round_trip_not_one_call_per_second() -> None:
    seconds = _estimate_semantic_kg_seconds(
        chunks_in_scope=EPSTEIN_CHUNKS,
        indexing_workers=EPSTEIN_WORKERS,
        seconds_per_chunk=_SEMANTIC_KG_SECONDS_PER_CHUNK_DEFAULT,
    )
    # Within a factor of 1.5 of the measured 2 h 07 min run, not the 12 minutes it quoted.
    assert EPSTEIN_WALL_SECONDS / 1.5 <= seconds <= EPSTEIN_WALL_SECONDS * 1.5
    assert seconds > 60 * 60


def test_estimate_divides_by_the_workers_that_run_in_parallel() -> None:
    one = _estimate_semantic_kg_seconds(chunks_in_scope=100, indexing_workers=1, seconds_per_chunk=10.0)
    four = _estimate_semantic_kg_seconds(chunks_in_scope=100, indexing_workers=4, seconds_per_chunk=10.0)
    sixteen = _estimate_semantic_kg_seconds(chunks_in_scope=100, indexing_workers=16, seconds_per_chunk=10.0)
    assert one == 1000.0
    assert four == 250.0
    # The runtime never fans out beyond eight concurrent extraction calls.
    assert sixteen == 125.0
    assert _estimate_semantic_kg_seconds(chunks_in_scope=0, indexing_workers=4, seconds_per_chunk=10.0) == 0.0


def test_measured_rate_comes_from_the_last_complete_semantic_run_for_the_same_alias() -> None:
    measured = _measured_semantic_kg_seconds_per_chunk(_run(), alias=LUNA)
    assert measured == 31_260.0 / EPSTEIN_CHUNKS  # 10 s per chunk per worker
    seconds = _estimate_semantic_kg_seconds(
        chunks_in_scope=EPSTEIN_CHUNKS, indexing_workers=EPSTEIN_WORKERS, seconds_per_chunk=measured
    )
    assert abs(seconds - 7815.0) < 1e-6


def test_measurement_is_ignored_when_it_cannot_speak_for_this_run() -> None:
    assert _measured_semantic_kg_seconds_per_chunk(None, alias=LUNA) is None
    # A different model: its latency says nothing about this alias.
    assert _measured_semantic_kg_seconds_per_chunk(_run(alias="deepseek.deepseek-v4-flash"), alias=LUNA) is None
    # A code-policy run never called the extraction LLM.
    assert _measured_semantic_kg_seconds_per_chunk(_run(policy="code"), alias=LUNA) is None
    # A run recorded before the measurement existed carries zero worker-seconds.
    assert _measured_semantic_kg_seconds_per_chunk(_run(worker_seconds=0.0), alias=LUNA) is None
    # No succeeded chunks: nothing to divide by.
    assert _measured_semantic_kg_seconds_per_chunk(_run(succeeded=0), alias=LUNA) is None


def test_assumption_names_the_source_of_the_rate() -> None:
    measured = _semantic_kg_seconds_assumption(
        chunks=EPSTEIN_CHUNKS,
        workers=EPSTEIN_WORKERS,
        seconds_per_chunk=10.0,
        measured_run=_run(),
    )
    assert "3,126 chunks" in measured
    assert "10.0s per chunk per worker" in measured
    assert "measured on run ca5b8d92" in measured
    assert "4 in parallel" in measured
    default = _semantic_kg_seconds_assumption(
        chunks=EPSTEIN_CHUNKS, workers=EPSTEIN_WORKERS, seconds_per_chunk=10.0, measured_run=None
    )
    assert "default" in default and "no completed run" in default


def _cost_schema(nodes: int = 1) -> GraphSchema:
    return GraphSchema(node_types=[
        NodeType(label=f"MissionEntity{i}", properties=[
            PropertyType(name="name", type="STRING", description="Canonical mission entity name"),
        ]) for i in range(nodes)
    ])


@pytest.mark.parametrize("nodes", [1, 30])
@pytest.mark.parametrize("template", [
    "Extract the graph. Schema: {schema}\nExamples: {examples}\nText: {text}",
    "Extract named mission entities with supporting evidence. " * 400 + "{schema}\n{text}",
    "{schema}\n{text}\nRepeat: {text}\nAgain: {text}",
    "{schema}\n{text}\nQuoted: {text!r}\nASCII: {text!a}\n{{literal braces}} {examples!r}",
], ids=["ordinary", "long_instructions", "repeated_text", "conversions_and_escaping"])
def test_semantic_input_prices_every_rendered_schema_prompt_and_output_schema(nodes, template) -> None:
    """The old750-token overhead ignored the paid repeated schema and structured format."""
    from server.indexing.graphrag_pipeline import extraction_prompt_template
    from server.indexing.graphrag_schema import closed_graph_schema

    schema = closed_graph_schema(_cost_schema(nodes))
    texts = ["月面通信\n'quoted' \\ telemetry" * 40, "orbittrajectory" * 100]
    prompts = [extraction_prompt_template(template).format(
        schema=schema.model_dump(exclude_none=True), text=text, examples="",
    ) for text in texts]
    response_format = {"type": "json_schema", "json_schema": {
        "name": "Neo4jGraph", "strict": True, "schema": Neo4jGraph.model_json_schema(),
    }}
    from server.chat.prompt_budget import TEMPLATE_MARGIN_TOKENS, TEXT_FACTOR_BY_PROVIDER

    expected = sum(math.ceil((count_tokens(prompt) + count_tokens(json.dumps(response_format))
                             + TEMPLATE_MARGIN_TOKENS) * TEXT_FACTOR_BY_PROVIDER["openai"])
                   for prompt in prompts)
    tokens = index_api._semantic_kg_input_tokens(
        texts, alias=LUNA,
        schema=schema, prompt_template=template,
    )
    assert tokens == expected
    doubled = index_api._semantic_kg_input_tokens(
        texts * 2, alias=LUNA,
        schema=schema, prompt_template=template,
    )
    assert doubled == 2 * tokens


def _usage_run(*, status="error", alias=LUNA, corpus="cost-corpus", schema_hash="a" * 64):
    run = _run(status=status, alias=alias, succeeded=1002).model_copy(deep=True)
    run.repo_id = corpus
    run.graph_metadata.schema_hash = schema_hash
    run.accounting = IndexRunAccounting(
        session_id=run.run_id, corpus_id=corpus, started_at=run.started_at,
        ended_at=run.completed_at, config_fingerprint="b" * 64,
        gateway_base_url="http://127.0.0.1:54000", models={"semantic_kg": alias},
        processed_chunks=1002, processed_tokens=182260,
        census={"semantic_kg": RunRequestCensus(
            identity=RunCostIdentity(session_id=run.run_id, corpus_id=corpus, lane="semantic_kg"),
            revision=5, started_requests=3, completed_requests=3, failed_requests=0,
            uncertain_requests=1, inflight=0, active_producers=0, owner_finished=True,
            dispatch_enabled=False, state="closed",
        )},
    )
    return run


def _usage_row(name="request-1", *, output=40, reasoning=10, **changes):
    run = _usage_run()
    payload = {
        "request_id": name, "call_type": "acompletion", "session_id": run.run_id,
        "model": "openrouter/openai/gpt-5.6-luna", "custom_llm_provider": "openrouter",
        "startTime": run.started_at.isoformat(),
        "endTime": (run.started_at + timedelta(seconds=1)).isoformat(),
        "spend": 0.01, "status": "success", "cache_hit": "False",
        "metadata": {
            "litellm_call_id": f"call-{name}",
            "spend_logs_metadata": {
                "run_id": run.run_id, "corpus_id": run.repo_id, "lane": "semantic_kg",
            },
            "usage_object": {
                "prompt_tokens": 100, "completion_tokens": output, "total_tokens": 100 + output,
                "completion_tokens_details": {"reasoning_tokens": reasoning},
            },
        },
    }
    payload.update(changes)
    return NativeSpendRow.model_validate(payload)


def _sample(rows, run=None, **changes):
    args = dict(run=run or _usage_run(), corpus_id="cost-corpus", alias=LUNA,
                upstream="openrouter/openai/gpt-5.6-luna", schema_hash="a" * 64)
    args.update(changes)
    return index_api._semantic_kg_usage_sample(rows, **args)


@contextmanager
def _native_output_history():
    """Serve the real native v2 wire contract, keyed by requested run identity."""
    warm_gateway_catalog()
    pages = {}
    requested = []
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_GET(self):  # noqa: N802 - stdlib HTTP handler
            query = urlsplit(self.path)
            assert query.path == "/spend/logs/v2"
            assert self.headers.get("Authorization") == "Bearer synthetic-only"
            run_id = parse_qs(query.query)["session_id"][0]
            requested.append(run_id)
            status = 503 if pages[run_id] == "unavailable" else 200
            held = pages[run_id] == "held"
            if held:
                assert release.wait(15)
            rows = [] if status == 503 or held else pages[run_id]
            payload = json.dumps({
                "data": [row.model_dump(mode="json") for row in rows],
                "total": len(rows), "page": 1, "page_size": 100,
                "total_pages": int(bool(rows)), "total_is_capped": False,
            }).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    keys = ("LITELLM_API_KEY", "LITELLM_BASE_URL")
    previous = {key: os.environ.pop(key, None) for key in keys}
    os.environ["LITELLM_API_KEY"] = "synthetic-only"
    try:
        yield f"http://127.0.0.1:{server.server_port}", pages, requested
    finally:
        release.set()
        for key, value in previous.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _persist_output_history_run(root: Path, gateway: str, ordinal: int, *, output=40):
    run = _usage_run()
    run.run_id = f"{ordinal:032x}"
    run.started_at += timedelta(days=ordinal)
    run.completed_at += timedelta(days=ordinal)
    run.accounting.session_id = run.run_id
    run.accounting.started_at = run.started_at
    run.accounting.ended_at = run.completed_at
    run.accounting.gateway_base_url = gateway
    census = run.accounting.census["semantic_kg"].model_dump()
    census["identity"]["session_id"] = run.run_id
    run.accounting.census["semantic_kg"] = RunRequestCensus.model_validate(census)
    row = _usage_row(f"request-{ordinal}", output=output)
    row.session_id = run.run_id
    row.startTime = run.started_at
    row.endTime = run.started_at + timedelta(seconds=1)
    row.metadata.spend_logs_metadata.run_id = run.run_id
    path = root / run.repo_id / run.run_id / "summary.json"
    path.parent.mkdir(parents=True)
    path.write_text(run.model_dump_json())
    return run, row, path


@pytest.mark.asyncio
@pytest.mark.parametrize("unusable", [
    "failed", "cached", "conflicted", "not_ingested", "wrong_upstream",
    "wrong_native_corpus", "wrong_native_lane", "wrong_time", "invalid_usage",
    "over_census", "native_read_error", "wrong_gateway", "wrong_alias", "wrong_schema", "wrong_policy",
    "wrong_corpus", "wrong_accounting_session", "not_settled",
])
async def test_output_history_searches_past_unusable_newer_runs(tmp_path: Path, unusable: str) -> None:
    previous_root = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        with _native_output_history() as (gateway, pages, requested):
            old, old_row, _ = _persist_output_history_run(tmp_path, gateway, 1, output=60)
            new, new_row, path = _persist_output_history_run(tmp_path, gateway, 2, output=90)
            pages[old.run_id] = [old_row]
            pages[new.run_id] = [new_row]
            if unusable == "failed":
                new_row.status = "failure"
            elif unusable == "cached":
                new_row.cache_hit = "True"
            elif unusable == "conflicted":
                variant = new_row.model_copy(deep=True)
                variant.spend = 1.0
                pages[new.run_id].append(variant)
            elif unusable == "not_ingested":
                pages[new.run_id] = []
            elif unusable == "wrong_upstream":
                new_row.model = "openrouter/openai/gpt-5.6-sol"
            elif unusable == "wrong_native_corpus":
                new_row.metadata.spend_logs_metadata.corpus_id = "another-corpus"
            elif unusable == "wrong_native_lane":
                new_row.metadata.spend_logs_metadata.lane = "schema_proposal"
            elif unusable == "wrong_time":
                new_row.startTime = old.started_at
            elif unusable == "invalid_usage":
                new_row.metadata.usage_object.total_tokens = 1
            elif unusable == "over_census":
                pages[new.run_id] = [new_row.model_copy(update={"request_id": f"excess-{i}"}, deep=True) for i in range(4)]
                for i, row in enumerate(pages[new.run_id]):
                    row.metadata.litellm_call_id = f"excess-call-{i}"
            elif unusable == "native_read_error":
                pages[new.run_id] = "unavailable"
            elif unusable == "wrong_gateway":
                new.accounting.gateway_base_url = "http://127.0.0.1:1"
            elif unusable == "wrong_alias":
                new.accounting.models["semantic_kg"] = "openai.gpt-5.6-sol"
            elif unusable == "wrong_schema":
                new.graph_metadata.schema_hash = "c" * 64
            elif unusable == "wrong_policy":
                new.graph_metadata.policy = "code"
            elif unusable == "wrong_corpus":
                new.repo_id = "another-corpus"
            elif unusable == "wrong_accounting_session":
                new.accounting.session_id = old.run_id
            else:
                census = new.accounting.census["semantic_kg"].model_dump()
                census.update(owner_finished=False, state="open")
                new.accounting.census["semantic_kg"] = RunRequestCensus.model_validate(census)
            path.write_text(new.model_dump_json())
            cfg = TriBridConfig()
            cfg.chat.litellm.base_url = f"{gateway}/v1"
            cfg.graph_indexing.semantic_kg_llm_model = LUNA
            result = await index_api._read_semantic_kg_usage(cfg, old.repo_id, "a" * 64)
            assert result is not None, unusable
            assert result.run_id == old.run_id
            assert result.mean_output_tokens == 60
            prefiltered = {"wrong_gateway", "wrong_alias", "wrong_schema", "wrong_policy", "wrong_corpus", "wrong_accounting_session", "not_settled"}
            assert requested == ([old.run_id] if unusable in prefiltered else [new.run_id, old.run_id])
    finally:
        index_api._INDEX_RUNS_DIR = previous_root


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_output_history_shares_one_transport_budget_and_preserves_cancellation(tmp_path: Path, cancel: bool) -> None:
    previous_root = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    pending = None
    try:
        with _native_output_history() as (gateway, pages, requested):
            runs = [_persist_output_history_run(tmp_path, gateway, ordinal)[0] for ordinal in range(1, 4)]
            for run in runs:
                pages[run.run_id] = "held"
            cfg = TriBridConfig()
            cfg.chat.litellm.base_url = f"{gateway}/v1"
            cfg.graph_indexing.semantic_kg_llm_model = LUNA
            started = asyncio.get_running_loop().time()
            pending = asyncio.create_task(index_api._read_semantic_kg_usage(cfg, runs[0].repo_id, "a" * 64))
            if cancel:
                async with asyncio.timeout(2):
                    while not requested:
                        await asyncio.sleep(0.01)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                assert requested == [runs[-1].run_id]
            else:
                assert await asyncio.wait_for(pending, 8) is None
                elapsed = asyncio.get_running_loop().time() - started
                assert 5.5 <= elapsed < 7.5
                assert requested == [runs[2].run_id, runs[1].run_id]
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        index_api._INDEX_RUNS_DIR = previous_root


@pytest.mark.asyncio
@pytest.mark.parametrize("usable", [False, True])
async def test_output_history_uses_the_newest_usable_sample_without_combining_runs(tmp_path: Path, usable: bool) -> None:
    previous_root = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        with _native_output_history() as (gateway, pages, requested):
            old, old_row, _ = _persist_output_history_run(tmp_path, gateway, 1, output=60)
            new, new_row, _ = _persist_output_history_run(tmp_path, gateway, 2, output=90)
            pages[old.run_id] = [old_row] if usable else []
            pages[new.run_id] = [new_row] if usable else []
            cfg = TriBridConfig()
            cfg.chat.litellm.base_url = f"{gateway}/v1"
            cfg.graph_indexing.semantic_kg_llm_model = LUNA
            result = await index_api._read_semantic_kg_usage(cfg, old.repo_id, "a" * 64)
            if usable:
                assert result.run_id == new.run_id
                assert result.requests == 1 and result.mean_output_tokens == 90
                assert requested == [new.run_id]
            else:
                assert result is None
                assert requested == [new.run_id, old.run_id]
    finally:
        index_api._INDEX_RUNS_DIR = previous_root


@pytest.mark.parametrize("status", ["complete", "error", "cancelled"])
def test_successful_native_outputs_in_failed_runs_are_samples_not_completed_corpora(status) -> None:
    run = _usage_run(status=status)
    sample = _sample([_usage_row(output=40), _usage_row("request-2", output=60)], run)
    assert sample is not None
    assert sample.requests == 2
    assert sample.output_tokens == 100  # Includes reasoning already; never adds it twice.
    assert sample.mean_output_tokens == 50
    assert sample.processed_chunks == 1002 and sample.dispatched_requests == 3
    assert sample.run_status == status


@pytest.mark.parametrize("field,value", [
    ("corpus_id", "another-corpus"), ("alias", "openai.gpt-5.6-sol"),
    ("upstream", "openrouter/openai/gpt-5.6-sol"), ("schema_hash", "c" * 64),
])
def test_output_evidence_cannot_cross_current_run_contract(field, value) -> None:
    assert _sample([_usage_row()], **{field: value}) is None


@pytest.mark.parametrize("field,value", [
    ("session_id", "other-run"), ("model", "openrouter/openai/gpt-5.6-sol"),
    ("status", "failure"), ("cache_hit", "True"), ("call_type", "embedding"),
])
def test_only_actual_successful_matching_generation_rows_inform_output(field, value) -> None:
    assert _sample([_usage_row(**{field: value})]) is None


@pytest.mark.parametrize("field,value", [
    ("run_id", "other-run"), ("corpus_id", "other-corpus"), ("lane", "schema_proposal"),
])
def test_output_evidence_requires_exact_native_metadata(field, value) -> None:
    payload = _usage_row().model_dump(mode="json")
    payload["metadata"]["spend_logs_metadata"][field] = value
    assert _sample([NativeSpendRow.model_validate(payload)]) is None


@pytest.mark.parametrize("change", ["missing_usage", "missing_input", "missing_output", "bad_total", "reasoning_exceeds_output"])
def test_missing_and_inconsistent_native_usage_is_not_silently_zero(change) -> None:
    payload = _usage_row().model_dump(mode="json")
    usage = payload["metadata"]["usage_object"]
    if change == "missing_usage":
        payload["metadata"]["usage_object"] = None
    elif change == "missing_input":
        usage["prompt_tokens"] = None
    elif change == "missing_output":
        usage["completion_tokens"] = None
    elif change == "bad_total":
        usage["total_tokens"] = 1
    else:
        usage["completion_tokens_details"]["reasoning_tokens"] = 1000
    assert _sample([NativeSpendRow.model_validate(payload)]) is None


def test_duplicate_native_pages_do_not_reweight_outputs_and_conflicts_are_excluded() -> None:
    first = _usage_row(output=40)
    second = _usage_row("request-2", output=60)
    sample = _sample([first, first, second])
    assert sample.requests == 2 and sample.mean_output_tokens == 50
    conflict = _usage_row(output=80)
    sample = _sample([first, conflict, second])
    assert sample.requests == 1 and sample.mean_output_tokens == 60
    collision = second.model_copy(deep=True)
    collision.metadata.litellm_call_id = first.metadata.litellm_call_id
    assert _sample([first, collision]) is None


def test_forecast_names_sampled_requests_failed_run_and_output_uncertainty() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = LUNA
    sample = _sample([_usage_row(output=40), _usage_row("request-2", output=60)])
    forecast = index_api._semantic_kg_forecast(
        cfg=cfg, chunks=1315, input_tokens=1_500_000,
        chunks_low=855, chunks_high=1776, tokens_low=975_000, tokens_high=2_025_000,
        usage=sample,
    )
    assert forecast.cost_usd is not None and forecast.cost_usd > 0
    detail = " ".join(forecast.assumptions)
    assert "2 successful native requests" in detail
    assert "1,002" in detail and "1,315" in detail
    assert "error" in detail and sample.run_id[:8] in detail
    assert "reasoning" in detail and "not a spending limit" in detail
    assert "configuration differs" in detail


def test_cold_output_history_does_not_fabricate_a_hundred_token_total() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = LUNA
    forecast = index_api._semantic_kg_forecast(
        cfg=cfg, chunks=1002, input_tokens=1_200_000,
        chunks_low=651, chunks_high=1353, tokens_low=118469, tokens_high=246051,
        usage=None,
    )
    assert forecast.cost_usd is None
    assert "output-token evidence unavailable" in " ".join(forecast.assumptions)


def test_unreliable_generation_sample_refuses_semantic_price_even_with_measured_output() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = LUNA
    forecast = index_api._semantic_kg_forecast(
        cfg=cfg, chunks=1002, input_tokens=1_200_000,
        chunks_low=651, chunks_high=1353, tokens_low=780_000, tokens_high=1_620_000,
        usage=_sample([_usage_row()]), generation_insufficient_reason="generation-token error band exceeds ceiling",
    )
    assert forecast.cost_usd is None
    assert "generation-token" in " ".join(forecast.assumptions)


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_output_history_rejects_compound_native_identity_conflicts(order) -> None:
    first = _usage_row("r1")
    variant = first.model_copy(deep=True)
    variant.metadata.litellm_call_id = "c2"
    neighbor = variant.model_copy(update={"request_id": "r2"}, deep=True)
    raw = [first, variant, neighbor]
    assert _sample([raw[index] for index in order]) is None


@pytest.mark.parametrize("last_status", ["success", "failure"])
def test_output_history_rejects_native_request_census_overcoverage(last_status) -> None:
    rows = [_usage_row(f"request-{index}") for index in range(4)]
    rows[-1] = rows[-1].model_copy(update={"status": last_status})
    assert _sample(rows) is None
    assert _sample(rows[:3]).requests == 3
    assert _sample([*rows[:3], rows[0]]).requests == 3


@pytest.mark.asyncio
@pytest.mark.requires_postgres
@pytest.mark.parametrize("proposal_case", [
    "approved", "unapproved", "stale_approval", "stale_proposal", "absent", "invalid_record",
])
@pytest.mark.parametrize("exclusion", ["directory", "suffix"])
async def test_semantic_estimate_endpoint_preserves_exclusions_and_approved_schema_contract(
    client, tmp_path, proposal_case: str, exclusion: str,
) -> None:
    """Real persisted proposals, including a validation failure; no LLM or indexing call."""
    import asyncio
    from uuid import uuid4

    from server.config import load_config
    from server.db.postgres import PostgresClient
    from server.indexing.chunker import Chunker
    from server.indexing.estimate import warm_sampler
    from server.indexing.graphrag_schema import canonical_schema_dict, graph_schema_hash
    from server.models.index import GraphSchemaProposal, GraphSchemaSample, IndexRequest
    from server.services import config_store

    corpus_id = f"pytest_estimate_schema_{uuid4().hex[:8]}"
    body = "月面探査通信記録" * 50
    (tmp_path / "mission.txt").write_text(body)
    if exclusion == "directory":
        private_dir = tmp_path / "excluded"
        private_dir.mkdir()
        private_document = private_dir / "private.txt"
        pattern = "excluded/"
    else:
        private_document = tmp_path / "notes.private.txt"
        pattern = "*.private.txt"
    private_document.write_text("Excluded operator notes.\n" * 100)
    cfg = load_config().model_copy(deep=True)
    cfg.graph_indexing.enabled = True
    cfg.graph_indexing.build_code_graph = False
    cfg.graph_indexing.semantic_kg_llm_model = LUNA
    cfg.indexing.skip_dense = True
    cfg.indexing.figures.enabled = False
    cfg.tokenization.strategy = "tiktoken"
    cfg.tokenization.estimate_only = False
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        await pg.upsert_corpus(corpus_id, corpus_id, str(tmp_path), meta={"exclude_paths": [pattern]})
        await config_store.save_config(cfg, repo_id=corpus_id)
        corpus, cfg = await index_api.load_corpus_and_scoped_config(corpus_id)
        schema = canonical_schema_dict(_cost_schema())
        proposal = GraphSchemaProposal(
            corpus_id=corpus_id, policy="semantic", schema=schema,
            schema_hash=graph_schema_hash(schema),
            input_fingerprint=await index_api.graph_schema_input_fingerprint(corpus, cfg),
            sample=GraphSchemaSample(chunk_ids=[], chunk_hashes=[]),
            model_alias=LUNA, created_at=datetime.now(UTC),
        )
        if proposal_case == "invalid_record":
            await pg.patch_corpus_meta_locked(corpus_id, {"graph_schema_proposal": {"schema": {}}})
        elif proposal_case != "absent":
            if proposal_case == "stale_proposal":
                proposal.input_fingerprint = "f" * 64
            await pg.set_graph_schema_proposal(corpus_id, proposal)
        approved_hash = None if proposal_case == "unapproved" else (
            "0" * 64 if proposal_case == "stale_approval" else proposal.schema_hash
        )
        request = IndexRequest(corpus_id=corpus_id, repo_path=str(tmp_path),
                               approved_graph_schema_hash=approved_hash)
        await asyncio.to_thread(warm_sampler, Chunker(cfg.chunking, cfg.tokenization))

        response = await client.post("/api/index/estimate", json=request.model_dump(mode="json"))

        assert response.status_code == 200, response.text
        estimate = response.json()
        assert estimate["total_files"] == 1
        assert estimate["total_size_bytes"] == (tmp_path / "mission.txt").stat().st_size
        assert estimate["embedding_cost_usd"] == 0
        assert estimate["semantic_kg_cost_usd"] is None and estimate["total_cost_usd"] is None
        details = " ".join(estimate["assumptions"])
        if proposal_case in {"approved", "unapproved"}:
            assert "input tokens include the full extraction prompt" in details
            assert "output-token evidence unavailable" in details
            chunks = Chunker(cfg.chunking, cfg.tokenization).chunk_file("mission.txt", body)
            generation_tokens = sum(count_tokens(chunk.content) for chunk in chunks)
            assert generation_tokens != estimate["estimated_total_tokens"]
            expected_input = index_api._semantic_kg_input_tokens(
                [chunk.content for chunk in chunks], alias=LUNA,
                schema=_cost_schema(), prompt_template=cfg.system_prompts.semantic_kg_extraction,
            )
            assert f"{expected_input:,} input tokens include" in details
        else:
            assert "current schema" in details
        assert corpus_id not in index_api._TASKS
    finally:
        await pg.delete_corpus(corpus_id)
        await pg.disconnect()
        config_store.get_config_store().clear_cache(corpus_id)


@pytest.mark.asyncio
@pytest.mark.requires_postgres
@pytest.mark.parametrize("template", [
    "Extract everything from {text}",
    "{schema}\n{text}\n{unsupported_field}",
    "{schema}\n{text}\n{",
    "{schema}\n{text}\n{text!invalid}",
    "{{schema}}\n{text}",
    "{schema}\n{{text}}",
    "{{schema}}\n{{text}}",
    "{schema}\n{examples:{text}}",
    "{schema!r}\n{text!s}",
    "{schema!s:{examples}}\n{text:{examples}}",
    "{schema}\n{text:}",
    "{schema!s:.0}\n{text}",
    "{{text}}\n{schema}\n{text!s:.0}",
    "{schema!s:{examples}.0}\n{text}",
    "{{text}}\n{schema}\n{text:{examples}}",
], ids=["missing_schema", "unknown_field", "unclosed_brace", "bad_conversion",
        "escaped_schema", "escaped_text", "both_escaped", "nested_text_only",
        "unsupported_conversion_only", "unsupported_nested_only", "unsupported_empty_spec",
        "erased_schema", "erased_text", "dynamic_erased_schema", "nested_text_no_full_occurrence"])
async def test_invalid_saved_prompt_has_the_same_typed_estimate_and_start_refusal(
    client, tmp_path, template: str,
) -> None:
    from uuid import uuid4

    from server.db.postgres import PostgresClient
    from server.indexing.graphrag_schema import canonical_schema_dict, graph_schema_hash
    from server.models.index import GraphSchemaProposal, GraphSchemaSample
    from server.services import config_store

    corpus_id = f"pytest_estimate_prompt_{uuid4().hex[:8]}"
    (tmp_path / "mission.txt").write_text("Mission telemetry describes the lunar orbit.")
    created = await client.post("/api/corpora", json={
        "corpus_id": corpus_id, "name": corpus_id, "path": str(tmp_path),
    })
    assert created.status_code in (200, 201), created.text
    corpus, cfg = await index_api.load_corpus_and_scoped_config(corpus_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        cfg.graph_indexing.enabled = True
        cfg.graph_indexing.build_code_graph = False
        cfg.graph_indexing.semantic_kg_llm_model = LUNA
        cfg.system_prompts.semantic_kg_extraction = template
        await config_store.save_config(cfg, repo_id=corpus_id)
        schema = canonical_schema_dict(_cost_schema())
        proposal = GraphSchemaProposal(
            corpus_id=corpus_id, policy="semantic", schema=schema, schema_hash=graph_schema_hash(schema),
            input_fingerprint=await index_api.graph_schema_input_fingerprint(corpus, cfg),
            sample=GraphSchemaSample(chunk_ids=[], chunk_hashes=[]), model_alias=LUNA,
            created_at=datetime.now(UTC),
        )
        await pg.set_graph_schema_proposal(corpus_id, proposal)
        payload = {"corpus_id": corpus_id, "repo_path": str(tmp_path),
                   "approved_graph_schema_hash": proposal.schema_hash}
        estimate = await client.post("/api/index/estimate", json=payload)
        # On the RED baseline an incorrectly accepted estimate must not start paid work.
        assert estimate.status_code == 422, estimate.text
        start = await client.post("/api/index", json=payload)
        assert estimate.status_code == start.status_code == 422
        assert estimate.json()["detail"] == start.json()["detail"]
        assert estimate.json()["detail"]["code"] == "graph_extraction_prompt_invalid"
        assert corpus_id not in index_api._TASKS
    finally:
        await pg.delete_corpus(corpus_id)
        await pg.disconnect()
        config_store.get_config_store().clear_cache(corpus_id)
