"""Historical indexing costs are saved observations or frozen quotes, never repriced."""
from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime

import pytest

import server.api.index as index_api
from server.api.index import _estimate_semantic_kg_cost_usd, _load_models_json, _status_costs
from server.indexing.run_records import write_run_summary
from server.models.index import IndexRunSummary
from server.models.run_accounting import IndexCostEstimateSnapshot, IndexRunAccounting
from server.models.tribrid_config_model import DashboardIndexCosts, TriBridConfig

SEMANTIC_ALIAS = "z-ai.glm-5.3-flash"
LOCAL_ALIAS = "ragweld-local"

@pytest.fixture(autouse=True)
def isolate_index_run_storage(tmp_path) -> Generator[None, None, None]:
    old = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        yield
    finally:
        index_api._INDEX_RUNS_DIR = old


def _run(*, quote: IndexCostEstimateSnapshot | None = None, legacy_figure_ceiling: float | None = None) -> IndexRunSummary:
    now = datetime.now(UTC)
    return IndexRunSummary(
        run_id="saved", repo_id="costs", status="complete", started_at=now,
        completed_at=now, figures_described=10, figure_description_cost_usd=legacy_figure_ceiling,
        accounting=None if quote is None else IndexRunAccounting(
            session_id="saved", corpus_id="costs", started_at=now,
            config_fingerprint="a"*64, estimate=quote,
        ),
    )


def _quote(*, semantic: float | None, figure: float | None, total: float | None) -> IndexCostEstimateSnapshot:
    return IndexCostEstimateSnapshot(
        captured_at=datetime.now(UTC), embedding_usd=0.25, semantic_kg_usd=semantic,
        figure_description_usd=figure, total_usd=total, estimated_chunks=100,
        estimated_tokens=50_000, detail="Saved estimate before this run dispatched requests.",
    )


@pytest.mark.parametrize("semantic", [None, 0.0, 0.50])
@pytest.mark.parametrize("figure", [None, 0.0, 1.25])
@pytest.mark.parametrize("current_backend", ["provider", "deterministic"])
def test_saved_quote_survives_config_changes_and_store_counts(semantic, figure, current_backend) -> None:
    quote = _quote(semantic=semantic, figure=figure, total=0.25+(semantic or 0)+(figure or 0))
    run = _run(quote=quote)
    cfg = TriBridConfig()
    cfg.embedding.embedding_backend = current_backend
    cfg.graph_indexing.enabled = False
    cfg.indexing.figures.enabled = False
    costs = _status_costs(cfg=cfg,graph_policy="off",total_tokens=2,total_chunks=1,latest_run=run)
    assert isinstance(costs, DashboardIndexCosts)
    assert costs.total_tokens == 2
    assert costs.embedding_cost == 0.25
    assert costs.semantic_kg_cost == semantic
    assert costs.figure_description_cost == figure
    assert costs.total_cost == quote.total_usd
    assert costs.accounting.estimate == quote
    assert costs.accounting.costs is None


@pytest.mark.parametrize("legacy_ceiling", [None, 0.0, 2.50])
@pytest.mark.parametrize("semantic_policy", ["off", "semantic"])
def test_legacy_run_preserves_figure_ceiling_but_total_and_actual_remain_unknown(legacy_ceiling, semantic_policy) -> None:
    costs = _status_costs(cfg=TriBridConfig(),graph_policy=semantic_policy,total_tokens=100,total_chunks=5,latest_run=_run(legacy_figure_ceiling=legacy_ceiling))
    assert costs.accounting is None
    assert costs.embedding_cost is costs.semantic_kg_cost is costs.total_cost is None
    assert costs.figure_description_cost == legacy_ceiling
    assert costs.figures_described == 10


def test_absent_run_is_unmeasured_even_if_current_configuration_is_local() -> None:
    cfg = TriBridConfig()
    cfg.embedding.embedding_backend = "deterministic"
    costs = _status_costs(cfg=cfg,graph_policy="off",total_tokens=200,total_chunks=5,latest_run=None)
    assert costs.total_cost is costs.embedding_cost is costs.accounting is None
    assert costs.figure_description_cost is None and costs.figures_described == 0


def test_unknown_component_in_frozen_quote_keeps_quoted_total_unknown() -> None:
    quote = _quote(semantic=None, figure=1.25, total=None)
    costs = _status_costs(cfg=TriBridConfig(),graph_policy="semantic",total_tokens=100,total_chunks=5,latest_run=_run(quote=quote))
    assert costs.total_cost is None
    assert costs.embedding_cost == 0.25 and costs.figure_description_cost == 1.25


async def test_saved_quote_round_trips_through_existing_run_summary() -> None:
    run = _run(quote=_quote(semantic=0.50, figure=1.25, total=2.0))
    write_run_summary(index_api._run_summary_path("costs", "saved"), run)
    loaded = await asyncio.to_thread(index_api._load_latest_run_summary, "costs")
    costs = _status_costs(cfg=TriBridConfig(),graph_policy="off",total_tokens=100,total_chunks=5,latest_run=loaded)
    assert costs.accounting == run.accounting
    assert costs.total_cost == 2.0


def test_the_semantic_kg_cost_prices_the_gateway_alias_the_run_would_actually_use() -> None:
    """Semantic KG was structurally unpriced, and nothing said so.

    It used to look the model up by a catalog row's `model` id -- every priced GEN row's id
    carries a slash (`z-ai/glm-5.3-flash`) -- while the semantic-KG model is a LiteLLM alias,
    which the config validator forbids from containing one (`z-ai.glm-5.3-flash`). Zero rows
    could ever match, so `semantic_kg_cost_usd` was None for every corpus, and a None
    component makes Total Cost unknown: a corpus with semantic KG on showed no total at all.

    The expected price is derived here from the catalog row itself, found by the alias, so
    this pins the resolution rather than restating whatever the helper resolved.
    """
    input_tokens, output_tokens = 1_600_000, 120_000
    cost = _estimate_semantic_kg_cost_usd(
        alias=SEMANTIC_ALIAS, input_tokens=input_tokens, output_tokens=output_tokens,
    )
    row = next(
        model
        for model in _load_models_json()
        if str(model.get("gateway_alias") or "") == SEMANTIC_ALIAS
    )
    assert "/" in str(row["model"]), row["model"]  # the id the old lookup demanded
    expected = (input_tokens / 1000.0) * float(row["input_per_1k"]) + (
        output_tokens / 1000.0
    ) * float(row["output_per_1k"])
    assert cost is not None
    assert cost > 0
    assert cost == pytest.approx(expected)


def test_the_default_local_alias_is_priced_at_zero_rather_than_unknown() -> None:
    """`ragweld-local` is a real catalog row priced 0.0/0.0. Free is a price; unknown is not,
    and a None here would make Total Cost unknown for every default-config corpus.
    """
    assert (
        _estimate_semantic_kg_cost_usd(
            alias=LOCAL_ALIAS, input_tokens=1_600_000, output_tokens=None,
        )
        == 0.0
    )


@pytest.mark.parametrize("alias", ["not-a-gateway-alias", "z-ai/glm-5.3-flash", ""])
def test_an_alias_the_catalog_does_not_serve_has_no_price(alias: str) -> None:
    """Including the catalog `model` id: it is not an alias, and resolving it would price a
    row the gateway would never route to.
    """
    assert (
        _estimate_semantic_kg_cost_usd(alias=alias, input_tokens=1_600_000, output_tokens=120_000)
        is None
    )


@pytest.mark.parametrize("input_tokens", [1, 100_000, 1_600_000])
def test_unknown_output_usage_keeps_paid_total_unknown(input_tokens: int) -> None:
    assert _estimate_semantic_kg_cost_usd(
        alias=SEMANTIC_ALIAS, input_tokens=input_tokens, output_tokens=None,
    ) is None


@pytest.mark.parametrize("input_tokens,output_tokens", [(-1, 20), (10, -1), (10, float("nan")), (10, float("inf"))])
def test_invalid_token_forecasts_are_rejected(input_tokens, output_tokens) -> None:
    with pytest.raises(ValueError):
        _estimate_semantic_kg_cost_usd(
            alias=SEMANTIC_ALIAS, input_tokens=input_tokens, output_tokens=output_tokens,
        )
