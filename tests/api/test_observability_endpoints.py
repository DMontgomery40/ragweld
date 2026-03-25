from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

from server.models.tribrid_config_model import TraceCostSummary, TraceExternalLink, TraceRouteSummary, TriBridConfig
from server.services.traces import get_trace_store


@pytest.mark.asyncio
async def test_observability_status_reports_missing_otlp_endpoint(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "otel"
    cfg["tracing"]["otel_export_enabled"] = 1
    cfg["tracing"]["otlp_endpoint"] = ""
    cfg["tracing"]["langfuse_enabled"] = 0

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
async def test_observability_status_reports_langfuse_key_and_reachability_failures(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "otel_langfuse"
    cfg["tracing"]["otel_export_enabled"] = 0
    cfg["tracing"]["langfuse_enabled"] = 1
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
        assert langfuse["configured"] is True
        assert langfuse["reachable"] is False
    finally:
        if old_public is not None:
            os.environ["LANGFUSE_PUBLIC_KEY"] = old_public
        if old_secret is not None:
            os.environ["LANGFUSE_SECRET_KEY"] = old_secret


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
