from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.models.eval import EvalDoc, EvalMetrics, EvalResult, EvalRun
from server.models.tribrid_config_model import (
    BenchmarkResult,
    BenchmarkRun,
    TraceCostSummary,
    TraceExternalLink,
    TraceRouteSummary,
    TriBridConfig,
)
from server.services.traces import get_trace_store


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _create_corpus(client: AsyncClient, *, corpus_id: str, path: Path) -> None:
    response = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(path), "description": None},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_observability_status_reports_missing_otlp_endpoint(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "otel"
    cfg["tracing"]["otel_export_enabled"] = True
    cfg["tracing"]["otlp_endpoint"] = ""
    cfg["tracing"]["langfuse_enabled"] = False

    saved = await client.put("/api/config", json=cfg)
    assert saved.status_code == 200

    response = await client.get("/api/observability/status")
    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is False
    assert data["mode"] == "otel"
    assert "OTLP endpoint" in str(data.get("operator_hint") or "")
    otlp = next(component for component in data["components"] if component["id"] == "otlp_export")
    assert otlp["enabled"] is True
    assert otlp["configured"] is False


@pytest.mark.asyncio
async def test_observability_status_reports_otlp_reachability_failures(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "otel"
    cfg["tracing"]["tracing_enabled"] = False
    cfg["tracing"]["otel_export_enabled"] = True
    cfg["tracing"]["otlp_endpoint"] = "http://127.0.0.1:9/v1/traces"
    cfg["tracing"]["langfuse_enabled"] = False

    saved = await client.put("/api/config", json=cfg)
    assert saved.status_code == 200

    response = await client.get("/api/observability/status")
    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is False
    otlp = next(component for component in data["components"] if component["id"] == "otlp_export")
    assert otlp["enabled"] is True
    assert otlp["configured"] is True
    assert otlp["reachable"] is False
    assert "OTLP export" in str(data.get("operator_hint") or "")


@pytest.mark.asyncio
async def test_observability_status_reports_langfuse_key_and_reachability_failures(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "otel_langfuse"
    cfg["tracing"]["otel_export_enabled"] = False
    cfg["tracing"]["langfuse_enabled"] = True
    cfg["tracing"]["langfuse_base_url"] = "http://127.0.0.1:9"

    old_public = os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    old_secret = os.environ.pop("LANGFUSE_SECRET_KEY", None)
    try:
        saved = await client.put("/api/config", json=cfg)
        assert saved.status_code == 200

        response = await client.get("/api/observability/status")
        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is False
        assert data["mode"] == "otel_langfuse"
        assert "LANGFUSE_PUBLIC_KEY" in str(data.get("operator_hint") or "")
        langfuse = next(component for component in data["components"] if component["id"] == "langfuse")
        assert langfuse["enabled"] is True
        # A URL alone is not "configured": without ingestion keys this process
        # would silently drop generations while the web UI stays green.
        assert langfuse["configured"] is False
        assert langfuse["reachable"] is False
        assert "LANGFUSE_PUBLIC_KEY" in str(langfuse.get("detail") or "")
    finally:
        if old_public is not None:
            os.environ["LANGFUSE_PUBLIC_KEY"] = old_public
        if old_secret is not None:
            os.environ["LANGFUSE_SECRET_KEY"] = old_secret


@pytest.mark.asyncio
async def test_observability_status_uses_public_langfuse_url_for_operator_links(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "otel_langfuse"
    cfg["tracing"]["langfuse_enabled"] = True
    cfg["tracing"]["langfuse_base_url"] = "http://127.0.0.1:9"
    cfg["tracing"]["langfuse_public_base_url"] = "https://langfuse.ragweld.com"

    old_public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    old_secret = os.environ.get("LANGFUSE_SECRET_KEY")
    os.environ["LANGFUSE_PUBLIC_KEY"] = old_public or "pk-test"
    os.environ["LANGFUSE_SECRET_KEY"] = old_secret or "sk-test"
    try:
        saved = await client.put("/api/config", json=cfg)
        assert saved.status_code == 200

        response = await client.get("/api/observability/status")
        assert response.status_code == 200
        data = response.json()
    finally:
        if old_public is None:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        else:
            os.environ["LANGFUSE_PUBLIC_KEY"] = old_public
        if old_secret is None:
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
        else:
            os.environ["LANGFUSE_SECRET_KEY"] = old_secret

    langfuse = next(component for component in data["components"] if component["id"] == "langfuse")
    assert langfuse["configured"] is True
    assert langfuse["reachable"] is False
    assert langfuse["url"] == "https://langfuse.ragweld.com"
    assert any(
        link["label"] == "Langfuse" and link["url"] == "https://langfuse.ragweld.com"
        for link in langfuse["links"]
    )


@pytest.mark.asyncio
async def test_generic_api_endpoint_emits_canonical_observability_headers(client: AsyncClient) -> None:
    response = await client.get("/api/config", headers={"X-Correlation-ID": "corr-observe-test"})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "corr-observe-test"
    assert str(response.headers.get("X-Trace-ID") or "").strip()
    assert str(response.headers.get("X-Root-Span-ID") or "").strip()


@pytest.mark.asyncio
async def test_observability_status_includes_gateway_and_workflow_control_plane_components(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "local"
    cfg["chat"]["litellm"]["enabled"] = True
    cfg["chat"]["litellm"]["base_url"] = "http://127.0.0.1:9/v1"
    cfg["chat"]["vllm"]["enabled"] = True
    cfg["chat"]["vllm"]["base_url"] = "http://127.0.0.1:9/v1"
    cfg["training"]["ragweld_agent_workflow_backend"] = "flyte"
    cfg["training"]["ragweld_agent_tracking_backend"] = "mlflow"
    cfg["training"]["ragweld_agent_backend"] = "unsloth"
    cfg["training"]["ragweld_agent_flyte_admin_base_url"] = "http://127.0.0.1:9/flyte"
    cfg["training"]["ragweld_agent_flyte_console_base_url"] = "http://127.0.0.1:9/console"
    cfg["training"]["ragweld_agent_flyte_project"] = "ragweld"
    cfg["training"]["ragweld_agent_flyte_domain"] = "development"
    cfg["training"]["ragweld_agent_flyte_launchplan"] = "learning-agent-train"
    cfg["training"]["ragweld_agent_mlflow_tracking_url"] = "http://127.0.0.1:9/mlflow"
    cfg["training"]["ragweld_agent_mlflow_console_base_url"] = "https://mlflow.ragweld.com"
    cfg["training"]["ragweld_agent_mlflow_experiment_name"] = "ragweld-learning-agent"
    cfg["training"]["ragweld_agent_unsloth_image"] = "ghcr.io/ragweld/unsloth:latest"

    old_litellm_url = os.environ.get("LITELLM_BASE_URL")
    old_vllm_url = os.environ.get("VLLM_BASE_URL")
    os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:7/v1"
    os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:8/v1"
    try:
        saved = await client.put("/api/config", json=cfg)
        assert saved.status_code == 200

        response = await client.get("/api/observability/status")
        assert response.status_code == 200
        data = response.json()
        components = {component["id"]: component for component in data["components"]}
    finally:
        if old_litellm_url is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = old_litellm_url
        if old_vllm_url is None:
            os.environ.pop("VLLM_BASE_URL", None)
        else:
            os.environ["VLLM_BASE_URL"] = old_vllm_url

    assert components["litellm"]["enabled"] is True
    assert components["litellm"]["configured"] is True
    assert components["litellm"]["reachable"] is False
    assert components["litellm"]["url"] == "http://127.0.0.1:7/v1"
    assert components["vllm"]["enabled"] is True
    assert components["vllm"]["configured"] is True
    assert components["vllm"]["reachable"] is False
    assert components["vllm"]["url"] == "http://127.0.0.1:8/v1"
    assert components["flyte"]["enabled"] is True
    assert components["mlflow"]["enabled"] is True
    assert components["unsloth"]["enabled"] is True
    labels = {link["label"] for link in data["links"]}
    assert "LiteLLM Gateway" in labels
    assert "Flyte Console" in labels
    assert "MLflow Tracking" in labels


@pytest.mark.asyncio
async def test_observability_status_and_catalog_include_enterprise_stack_components(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["mimir_base_url"] = "http://127.0.0.1:9/mimir"
    cfg["tracing"]["pyroscope_base_url"] = "http://127.0.0.1:9/pyroscope"
    cfg["tracing"]["faro_base_url"] = "http://127.0.0.1:9/faro"
    cfg["tracing"]["opencost_base_url"] = "http://127.0.0.1:9/opencost"
    cfg["tracing"]["alertmanager_base_url"] = "http://127.0.0.1:9/alertmanager"

    saved = await client.put("/api/config", json=cfg)
    assert saved.status_code == 200

    status_response = await client.get("/api/observability/status")
    assert status_response.status_code == 200
    status_data = status_response.json()
    components = {component["id"]: component for component in status_data["components"]}

    assert components["mimir"]["configured"] is True
    assert components["pyroscope"]["configured"] is True
    assert components["faro"]["configured"] is True
    assert components["opencost"]["configured"] is True
    assert components["alertmanager"]["configured"] is True
    assert status_data["severity"] in {"warning", "critical"}

    catalog_response = await client.get("/api/observability/catalog")
    assert catalog_response.status_code == 200
    catalog_data = catalog_response.json()
    dashboard_ids = {dashboard["id"] for dashboard in catalog_data["dashboards"]}
    assert {
        "oncall_overview",
        "gateway_serving",
        "retrieval_indexing_graph",
        "training_workflow",
        "eval_benchmark_prompt_regressions",
        "cost_capacity",
        "frontend_rum",
    }.issubset(dashboard_ids)
    variables = {
        variable["id"]
        for dashboard in catalog_data["dashboards"]
        for variable in dashboard.get("variables", [])
    }
    assert {"corpus_id", "run_id", "model", "provider", "prompt_set", "workflow_id"}.issubset(variables)


@pytest.mark.asyncio
async def test_traces_latest_returns_extended_observability_fields(client: AsyncClient) -> None:
    cfg = TriBridConfig()
    cfg.tracing.tracing_mode = "otel_langfuse"
    store = get_trace_store()
    run_id = "observability-trace-test"

    started = await store.start(run_id=run_id, repo_id="repo-observe", started_at_ms=123, config=cfg)
    assert started is True
    await store.annotate(
        run_id,
        trace_id="trace-abc",
        root_span_id="span-def",
        correlation_id="corr-ghi",
        route_summary=TraceRouteSummary(
            route_name="search",
            path="/api/search",
            method="POST",
            corpus_ids=["repo-observe"],
            include_vector=True,
            include_sparse=True,
            include_graph=False,
            vector_results=4,
            sparse_results=2,
            final_results=5,
            llm_used=False,
        ),
        external_links=[
            TraceExternalLink(
                label="Langfuse trace",
                kind="langfuse",
                url="http://langfuse.local/trace/trace-abc",
            )
        ],
        cost_summary=TraceCostSummary(
            provider="litellm",
            model="openai/gpt-4.1-mini",
            total_tokens=25,
            estimated_cost_usd=0.0042,
            cost_source="catalog",
            authoritative=False,
        ),
    )
    await store.end(run_id, ended_at_ms=456)

    response = await client.get(f"/api/traces/latest?run_id={run_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["run_id"] == run_id
    assert data["trace"]["trace_id"] == "trace-abc"
    assert data["trace"]["root_span_id"] == "span-def"
    assert data["trace"]["correlation_id"] == "corr-ghi"
    assert data["trace"]["route_summary"]["route_name"] == "search"
    assert data["trace"]["route_summary"]["vector_results"] == 4
    assert data["trace"]["external_links"][0]["kind"] == "langfuse"
    assert data["trace"]["cost_summary"]["estimated_cost_usd"] == 0.0042


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_observability_summaries_and_incidents_correlate_eval_benchmark_and_prompt_changes(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    corpus_id = f"pytest_observe_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    root = _repo_root()
    eval_dir = root / "data" / "eval_runs"
    benchmark_dir = root / "data" / "benchmarks"
    eval_dir.mkdir(parents=True, exist_ok=True)
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    eval_previous_path = eval_dir / f"{corpus_id}__20260325_010101.json"
    eval_latest_path = eval_dir / f"{corpus_id}__20260325_020202.json"
    benchmark_previous_path = benchmark_dir / f"{corpus_id}__benchmark_prev.json"
    benchmark_latest_path = benchmark_dir / f"{corpus_id}__benchmark_latest.json"

    try:
        bundle_response = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert bundle_response.status_code == 200
        base_bundle = bundle_response.json()
        base_bundle_id = str(base_bundle["bundle_id"])

        previous_eval = EvalRun(
            run_id=f"{corpus_id}__20260325_010101",
            repo_id=corpus_id,
            dataset_id="default",
            config_snapshot={},
            config={},
            total=2,
            top1_hits=2,
            topk_hits=2,
            top1_accuracy=1.0,
            topk_accuracy=1.0,
            duration_secs=4.0,
            metrics=EvalMetrics(
                mrr=1.0,
                recall_at_5=1.0,
                recall_at_10=1.0,
                recall_at_20=1.0,
                precision_at_5=0.4,
                ndcg_at_10=1.0,
                latency_p50_ms=100.0,
                latency_p95_ms=120.0,
            ),
            results=[
                EvalResult(
                    entry_id="q1",
                    question="Question 1",
                    retrieved_paths=["src/a.py"],
                    expected_paths=["src/a.py"],
                    top_paths=["src/a.py"],
                    top1_path=["src/a.py"],
                    top1_hit=True,
                    topk_hit=True,
                    reciprocal_rank=1.0,
                    recall=1.0,
                    latency_ms=100.0,
                    duration_secs=0.1,
                    docs=[EvalDoc(file_path="src/a.py", start_line=1, score=1.0, source="vector")],
                    debug={},
                ),
                EvalResult(
                    entry_id="q2",
                    question="Question 2",
                    retrieved_paths=["src/b.py"],
                    expected_paths=["src/b.py"],
                    top_paths=["src/b.py"],
                    top1_path=["src/b.py"],
                    top1_hit=True,
                    topk_hit=True,
                    reciprocal_rank=1.0,
                    recall=1.0,
                    latency_ms=110.0,
                    duration_secs=0.11,
                    docs=[EvalDoc(file_path="src/b.py", start_line=1, score=1.0, source="vector")],
                    debug={},
                ),
            ],
            started_at=datetime(2026, 3, 25, 1, 1, 1, tzinfo=UTC),
            completed_at=datetime(2026, 3, 25, 1, 5, 1, tzinfo=UTC),
            bundle_id=base_bundle_id,
        )
        latest_eval = EvalRun(
            run_id=f"{corpus_id}__20260325_020202",
            repo_id=corpus_id,
            dataset_id="default",
            config_snapshot={},
            config={},
            total=2,
            top1_hits=0,
            topk_hits=1,
            top1_accuracy=0.0,
            topk_accuracy=0.5,
            duration_secs=5.0,
            metrics=EvalMetrics(
                mrr=0.25,
                recall_at_5=0.5,
                recall_at_10=0.5,
                recall_at_20=0.5,
                precision_at_5=0.1,
                ndcg_at_10=0.4,
                latency_p50_ms=180.0,
                latency_p95_ms=220.0,
            ),
            results=[
                EvalResult(
                    entry_id="q1",
                    question="Question 1",
                    retrieved_paths=["src/c.py", "src/a.py"],
                    expected_paths=["src/a.py"],
                    top_paths=["src/c.py", "src/a.py"],
                    top1_path=["src/c.py"],
                    top1_hit=False,
                    topk_hit=True,
                    reciprocal_rank=0.5,
                    recall=1.0,
                    latency_ms=180.0,
                    duration_secs=0.18,
                    docs=[EvalDoc(file_path="src/c.py", start_line=1, score=0.9, source="vector")],
                    debug={},
                ),
                EvalResult(
                    entry_id="q2",
                    question="Question 2",
                    retrieved_paths=["src/d.py"],
                    expected_paths=["src/b.py"],
                    top_paths=["src/d.py"],
                    top1_path=["src/d.py"],
                    top1_hit=False,
                    topk_hit=False,
                    reciprocal_rank=0.0,
                    recall=0.0,
                    latency_ms=220.0,
                    duration_secs=0.22,
                    docs=[EvalDoc(file_path="src/d.py", start_line=1, score=0.7, source="vector")],
                    debug={},
                ),
            ],
            started_at=datetime(2026, 3, 25, 2, 2, 2, tzinfo=UTC),
            completed_at=datetime(2026, 3, 25, 2, 7, 2, tzinfo=UTC),
            bundle_id=base_bundle_id,
        )

        eval_previous_path.write_text(previous_eval.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        eval_latest_path.write_text(latest_eval.model_dump_json(by_alias=True, indent=2), encoding="utf-8")

        previous_benchmark = BenchmarkRun(
            run_id=f"{corpus_id}__benchmark_prev",
            repo_id=corpus_id,
            prompt="ping",
            models=["litellm:ragweld-local", "litellm:quality-review"],
            started_at_ms=1_742_873_100_000,
            ended_at_ms=1_742_873_101_000,
            results=[
                BenchmarkResult(model="litellm:ragweld-local", response="ok", latency_ms=100.0, breakdown_ms={"generate": 100.0}),
                BenchmarkResult(model="litellm:openai/gpt-4.1-mini", response="ok", latency_ms=120.0, breakdown_ms={"generate": 120.0}),
            ],
            bundle_id=base_bundle_id,
        )
        latest_benchmark = BenchmarkRun(
            run_id=f"{corpus_id}__benchmark_latest",
            repo_id=corpus_id,
            prompt="ping",
            models=["litellm:ragweld-local", "litellm:quality-review"],
            started_at_ms=1_742_873_200_000,
            ended_at_ms=1_742_873_201_000,
            results=[
                BenchmarkResult(model="litellm:ragweld-local", response="still ok", latency_ms=650.0, breakdown_ms={"generate": 650.0}),
                BenchmarkResult(
                    model="litellm:openai/gpt-4.1-mini",
                    response="",
                    latency_ms=820.0,
                    breakdown_ms={"generate": 820.0},
                    error="gateway timeout",
                ),
            ],
            bundle_id=base_bundle_id,
        )

        benchmark_previous_path.write_text(previous_benchmark.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        benchmark_latest_path.write_text(latest_benchmark.model_dump_json(by_alias=True, indent=2), encoding="utf-8")

        prompts_before = await client.get("/api/prompts", params={"corpus_id": corpus_id})
        assert prompts_before.status_code == 200
        original_prompt = str(prompts_before.json()["prompts"]["query_rewrite"])

        prompt_update = await client.put(
            "/api/prompts/query_rewrite",
            params={"corpus_id": corpus_id},
            json={"value": original_prompt + "\n\n# observability regression"},
        )
        assert prompt_update.status_code == 200

        eval_summary_response = await client.get("/api/eval/observability/summary", params={"corpus_id": corpus_id})
        assert eval_summary_response.status_code == 200
        eval_summary = eval_summary_response.json()
        assert eval_summary["latest_run_id"] == latest_eval.run_id
        assert eval_summary["regressed_count"] >= 1
        assert float(eval_summary["top1_accuracy"]["absolute_delta"]) < 0

        benchmark_summary_response = await client.get(
            "/api/benchmark/observability/summary",
            params={"corpus_id": corpus_id},
        )
        assert benchmark_summary_response.status_code == 200
        benchmark_summary = benchmark_summary_response.json()
        assert benchmark_summary["latest_run_id"] == latest_benchmark.run_id
        assert float(benchmark_summary["average_latency_ms"]["absolute_delta"]) > 0
        assert benchmark_summary["latest_error_count"] == 1

        prompt_summary_response = await client.get(
            "/api/prompts/observability/summary",
            params={"corpus_id": corpus_id},
        )
        assert prompt_summary_response.status_code == 200
        prompt_summary = prompt_summary_response.json()
        assert prompt_summary["changed_since_latest_eval"] is True
        assert prompt_summary["changed_since_latest_benchmark"] is True
        assert prompt_summary["pending_verification"] is True
        assert prompt_summary["eval_regression_suspected"] is True
        assert prompt_summary["benchmark_regression_suspected"] is True

        incidents_response = await client.get("/api/observability/incidents", params={"corpus_id": corpus_id})
        assert incidents_response.status_code == 200
        incidents = incidents_response.json()["incidents"]
        sources = {incident["source"] for incident in incidents}
        assert {"eval", "benchmark", "prompt_regression"}.issubset(sources)
    finally:
        for path in (eval_previous_path, eval_latest_path, benchmark_previous_path, benchmark_latest_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        await client.delete(f"/api/corpora/{corpus_id}")
