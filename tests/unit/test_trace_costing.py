"""Trace cost summaries resolve gateway aliases to catalog pricing."""

from __future__ import annotations

import json

import pytest

from server.gateway_catalog import CATALOG_PATH, warm_gateway_catalog
from server.observability.costing import build_trace_cost_summary


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    {"input": 0, "output": 0, "total": 0},
])
def test_zero_usage_is_known_not_missing(usage: dict) -> None:
    summary = build_trace_cost_summary(provider="LiteLLM", model="ragweld-local", usage=usage, provider_cost_usd=None)
    assert (summary.input_tokens, summary.output_tokens, summary.total_tokens) == (0, 0, 0)
    assert summary.cost_source == "catalog" and summary.estimated_cost_usd == 0


@pytest.mark.parametrize("invalid", [float("inf"), float("nan"), -0.01, True])
def test_invalid_reported_cost_cannot_become_authoritative(invalid: object) -> None:
    from server.observability.costing import extract_provider_cost

    assert extract_provider_cost({"usage": {"cost": invalid}}) is None


@pytest.fixture(autouse=True)
def _warm_catalog_snapshot() -> None:
    warm_gateway_catalog()


def _catalog_row(alias: str) -> dict:
    rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["models"]
    return next(row for row in rows if row.get("gateway_alias") == alias)


def test_gateway_alias_resolves_catalog_pricing_when_gateway_returns_no_cost() -> None:
    row = _catalog_row("openai.gpt-5.4-mini")
    summary = build_trace_cost_summary(
        provider="LiteLLM",
        model="openai.gpt-5.4-mini",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
        provider_cost_usd=None,
    )

    assert summary.cost_source == "catalog"
    assert summary.authoritative is False
    assert summary.input_tokens == 1000 and summary.output_tokens == 500
    expected = row["input_per_1k"] * 1.0 + row["output_per_1k"] * 0.5
    assert summary.estimated_cost_usd == round(expected, 6)


def test_local_vllm_alias_costs_zero_from_catalog() -> None:
    summary = build_trace_cost_summary(
        provider="LiteLLM",
        model="ragweld-local",
        usage={"prompt_tokens": 300, "completion_tokens": 120},
        provider_cost_usd=None,
    )

    assert summary.cost_source == "catalog"
    assert summary.estimated_cost_usd == 0.0


def test_unknown_alias_is_reported_unavailable_not_guessed() -> None:
    summary = build_trace_cost_summary(
        provider="LiteLLM",
        model="hand-added-alias-not-in-catalog",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        provider_cost_usd=None,
    )

    assert summary.cost_source == "unavailable"
    assert summary.estimated_cost_usd is None


def test_gateway_reported_cost_is_authoritative_over_catalog() -> None:
    summary = build_trace_cost_summary(
        provider="LiteLLM",
        model="openai.gpt-5.4-mini",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
        provider_cost_usd=0.0123,
    )

    assert summary.cost_source == "provider"
    assert summary.authoritative is True
    assert summary.estimated_cost_usd == 0.0123
