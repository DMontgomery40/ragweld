"""The dashboard's indexing-cost card knows about figures.

`GET /api/index/status` recomputed its costs from live stats plus config, which between them
know nothing about a figure phase: after the Apollo run described 125 figures the card still
read embedding $0 / total $0. The figure spend lives on the run record (13a), so the cost
assembly has to read it from there.

`_status_costs` is the whole cost block as one pure function, which is what makes the
combinations testable: the total has to stay correct across semantic KG on/off x figures
on/off, and an unpriced component has to poison the total rather than silently count as zero.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime

import pytest

import server.api.index as index_api
from server.api.index import (
    _estimate_embedding_cost_usd,
    _estimate_figure_description_cost_usd,
    _estimate_semantic_kg_cost_usd,
    _flush_run_events_sync,
    _load_latest_run_summary,
    _load_models_json,
    _persist_run_summary,
    _semantic_kg_model_override,
    _status_costs,
)
from server.models.index import IndexRunSummary
from server.models.tribrid_config_model import DashboardIndexCosts, TriBridConfig

FIGURE_ALIAS = "z-ai.glm-5.3-flash"
FIGURE_BUDGET = 2500
# A priced GEN row in data/models.json, so a semantic KG phase costs real money here.
SEMANTIC_ALIAS = "z-ai.glm-5.3-flash"
# The default local lane: a real catalog row priced 0.0/0.0.
LOCAL_ALIAS = "ragweld-local"


@pytest.fixture(autouse=True)
def isolate_index_run_storage(tmp_path) -> Generator[None, None, None]:
    old_runs_dir = index_api._INDEX_RUNS_DIR
    index_api._INDEX_RUNS_DIR = tmp_path
    try:
        yield
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir


def _paid_config(*, semantic_kg: bool) -> TriBridConfig:
    """A config whose embedding lane really costs money, so a $0 total is never trivially right."""
    cfg = TriBridConfig()
    cfg.embedding.embedding_backend = "provider"
    cfg.indexing.skip_dense = False
    cfg.graph_indexing.semantic_kg_enabled = semantic_kg
    cfg.graph_indexing.semantic_kg_llm_model = SEMANTIC_ALIAS
    cfg.indexing.figures.vision_model = FIGURE_ALIAS
    cfg.indexing.figures.max_completion_tokens = FIGURE_BUDGET
    return cfg


def _run(
    *, described: int, cost: float | None, repo_id: str = "costs-corpus", run_id: str = "run-1"
) -> IndexRunSummary:
    return IndexRunSummary(
        run_id=run_id,
        repo_id=repo_id,
        status="complete",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        progress=1.0,
        total_files=2,
        total_chunks=100,
        total_tokens=50_000,
        figures_described=described,
        figures_failed=0,
        figures_undescribed=0,
        figure_description_cost_usd=cost,
    )


def test_status_costs_returns_the_registered_costs_model() -> None:
    costs = _status_costs(
        cfg=_paid_config(semantic_kg=False), total_tokens=0, total_chunks=0, latest_run=None
    )
    assert isinstance(costs, DashboardIndexCosts)


def test_the_costs_model_declares_the_figure_fields_with_descriptions() -> None:
    fields = DashboardIndexCosts.model_fields
    for name in ("figure_description_cost", "figures_described"):
        assert name in fields, f"DashboardIndexCosts is missing {name}"
        assert (fields[name].description or "").strip(), f"{name} needs a Field(description=...)"


@pytest.mark.parametrize("semantic_kg", [False, True])
@pytest.mark.parametrize("figures_described", [0, 10])
def test_the_total_is_the_sum_of_exactly_the_phases_that_ran(
    semantic_kg: bool, figures_described: int
) -> None:
    """The matrix the old code could not get right: it summed embedding and semantic KG and
    stopped there, so a figures run reported a total that omitted its largest component.

    Each component is re-derived here from the same pricing primitives the API uses but through
    an independent call, so this pins the composition rule rather than restating the answer.
    """
    cfg = _paid_config(semantic_kg=semantic_kg)
    figure_cost = (
        _estimate_figure_description_cost_usd(
            alias=FIGURE_ALIAS, figures=figures_described, max_completion_tokens=FIGURE_BUDGET
        )
        if figures_described
        else None
    )
    latest = _run(described=figures_described, cost=figure_cost)

    costs = _status_costs(cfg=cfg, total_tokens=50_000, total_chunks=100, latest_run=latest)

    assert costs.total_tokens == 50_000
    embedding = _estimate_embedding_cost_usd(
        provider=cfg.embedding.embedding_type,
        model=cfg.embedding.effective_model,
        total_tokens=50_000,
    )
    assert embedding is not None and embedding > 0
    assert costs.embedding_cost == pytest.approx(embedding)

    semantic = (
        _estimate_semantic_kg_cost_usd(
            alias=_semantic_kg_model_override(cfg),
            chunks_in_scope=min(100, int(cfg.graph_indexing.semantic_kg_max_chunks or 0)),
            enrich_max_chars=int(cfg.enrichment.enrich_max_chars or 1000),
        )
        if semantic_kg
        else None
    )
    if semantic_kg:
        # A priced alias: the semantic component is a real number, so it is really summed.
        assert semantic is not None and semantic > 0
    assert costs.semantic_kg_cost == semantic

    if figures_described:
        assert costs.figures_described == figures_described
        assert costs.figure_description_cost == pytest.approx(figure_cost)
    else:
        # Nothing was described: no figure line at all, not a $0.0000 one.
        assert costs.figures_described == 0
        assert costs.figure_description_cost is None

    applicable: list[float | None] = [embedding]
    if semantic_kg:
        applicable.append(semantic)
    if figures_described:
        applicable.append(figure_cost)
    if any(component is None for component in applicable):
        assert costs.total_cost is None
    else:
        assert costs.total_cost == pytest.approx(sum(float(c) for c in applicable))  # type: ignore[arg-type]


def test_a_run_that_described_figures_at_an_unpriced_alias_makes_the_total_unknown() -> None:
    """An unknown price is not zero. Summing it as zero would understate the operator's spend,
    which is the same failure as the missing figure component, only quieter.
    """
    costs = _status_costs(
        cfg=_paid_config(semantic_kg=False),
        total_tokens=50_000,
        total_chunks=100,
        latest_run=_run(described=10, cost=None),
    )
    assert costs.figures_described == 10
    assert costs.figure_description_cost is None
    assert costs.total_cost is None


def test_a_deterministic_backend_still_reports_the_figure_spend() -> None:
    """Figures are described through the paid gateway whatever the embedding backend is: a
    local/deterministic embedding lane costs $0 and the run can still have spent real money.
    """
    cfg = _paid_config(semantic_kg=False)
    cfg.embedding.embedding_backend = "deterministic"
    figure_cost = _estimate_figure_description_cost_usd(
        alias=FIGURE_ALIAS, figures=10, max_completion_tokens=FIGURE_BUDGET
    )
    costs = _status_costs(
        cfg=cfg,
        total_tokens=50_000,
        total_chunks=100,
        latest_run=_run(described=10, cost=figure_cost),
    )
    assert costs.embedding_cost == 0.0
    assert costs.figure_description_cost == pytest.approx(figure_cost)
    assert costs.total_cost == pytest.approx(figure_cost)


def test_a_corpus_with_no_persisted_run_reports_no_figure_line() -> None:
    costs = _status_costs(
        cfg=_paid_config(semantic_kg=False), total_tokens=50_000, total_chunks=100, latest_run=None
    )
    assert costs.figures_described == 0
    assert costs.figure_description_cost is None
    assert costs.total_cost == pytest.approx(costs.embedding_cost)


async def test_the_figure_spend_survives_the_round_trip_the_status_read_makes() -> None:
    """End to end over the real persistence seam: the status read loads the latest summary off
    disk exactly like `/runs/latest` does, so the number on the card is the number the run wrote.
    """
    repo_id = "costs-corpus-roundtrip"
    figure_cost = _estimate_figure_description_cost_usd(
        alias=FIGURE_ALIAS, figures=10, max_completion_tokens=FIGURE_BUDGET
    )
    _persist_run_summary(_run(described=10, cost=figure_cost, repo_id=repo_id, run_id="run-rt"))
    await asyncio.to_thread(_flush_run_events_sync)

    latest = await asyncio.to_thread(_load_latest_run_summary, repo_id)
    assert latest is not None and latest.figures_described == 10

    costs = _status_costs(
        cfg=_paid_config(semantic_kg=False),
        total_tokens=50_000,
        total_chunks=100,
        latest_run=latest,
    )
    assert costs.figures_described == 10
    assert costs.figure_description_cost == pytest.approx(figure_cost)
    assert costs.total_cost == pytest.approx(
        float(costs.embedding_cost or 0.0) + float(figure_cost or 0.0)
    )


async def test_a_newer_non_terminal_run_does_not_erase_the_live_index_spend() -> None:
    """The card must price the generation that is actually live, not the newest summary on disk.

    Starting a re-index writes an `indexing` summary immediately, and every summary except the
    one `_publish_complete` writes carries zero figures by design. Reading "the latest run"
    would therefore drop the figure line the moment a re-index starts -- while total_chunks and
    total_tokens still come from Postgres, i.e. still from the completed generation. It would
    self-heal on completion and stay wrong on an error or a cancellation: exactly the "$0 that
    isn't really zero" this whole slice exists to remove.
    """
    repo_id = "costs-corpus-reindexing"
    figure_cost = _estimate_figure_description_cost_usd(
        alias=FIGURE_ALIAS, figures=10, max_completion_tokens=FIGURE_BUDGET
    )
    _persist_run_summary(
        _run(described=10, cost=figure_cost, repo_id=repo_id, run_id="run-complete")
    )
    await asyncio.to_thread(_flush_run_events_sync)

    for status in ("indexing", "error", "cancelled"):
        newer = _run(described=0, cost=None, repo_id=repo_id, run_id=f"run-{status}").model_copy(
            update={"status": status, "completed_at": None}
        )
        _persist_run_summary(newer)
        await asyncio.to_thread(_flush_run_events_sync)

        latest = await asyncio.to_thread(_load_latest_run_summary, repo_id, ("complete",))
        assert latest is not None, f"a {status} run hid the completed one"
        assert latest.run_id == "run-complete"

        costs = _status_costs(
            cfg=_paid_config(semantic_kg=False),
            total_tokens=50_000,
            total_chunks=100,
            latest_run=latest,
        )
        assert costs.figures_described == 10, f"{status} run erased the figure count"
        assert costs.figure_description_cost == pytest.approx(figure_cost)


async def test_the_unfiltered_loader_still_answers_with_the_newest_run() -> None:
    """`/index/{corpus}/runs/latest` must keep reporting the newest run whatever its status --
    an operator looking at "Recent Index Runs" wants to see the failure, not the last success.
    """
    repo_id = "costs-corpus-unfiltered"
    _persist_run_summary(_run(described=4, cost=0.01, repo_id=repo_id, run_id="run-old-complete"))
    await asyncio.to_thread(_flush_run_events_sync)
    _persist_run_summary(
        _run(described=0, cost=None, repo_id=repo_id, run_id="run-new-error").model_copy(
            update={"status": "error", "error": "boom"}
        )
    )
    await asyncio.to_thread(_flush_run_events_sync)

    newest = await asyncio.to_thread(_load_latest_run_summary, repo_id)
    assert newest is not None and newest.run_id == "run-new-error"
    assert newest.status == "error"


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
    chunks, enrich_chars = 200, 1000
    cost = _estimate_semantic_kg_cost_usd(
        alias=SEMANTIC_ALIAS, chunks_in_scope=chunks, enrich_max_chars=enrich_chars
    )
    row = next(
        model
        for model in _load_models_json()
        if str(model.get("gateway_alias") or "") == SEMANTIC_ALIAS
    )
    assert "/" in str(row["model"]), row["model"]  # the id the old lookup demanded
    input_tokens = chunks * (500 + enrich_chars // 4)
    output_tokens = chunks * 100
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
            alias=LOCAL_ALIAS, chunks_in_scope=200, enrich_max_chars=1000
        )
        == 0.0
    )


@pytest.mark.parametrize("alias", ["not-a-gateway-alias", "z-ai/glm-5.3-flash", ""])
def test_an_alias_the_catalog_does_not_serve_has_no_price(alias: str) -> None:
    """Including the catalog `model` id: it is not an alias, and resolving it would price a
    row the gateway would never route to.
    """
    assert (
        _estimate_semantic_kg_cost_usd(alias=alias, chunks_in_scope=200, enrich_max_chars=1000)
        is None
    )


def test_the_status_total_folds_in_the_semantic_kg_spend() -> None:
    """The card's Total Cost has to include the semantic KG phase, not go unknown because of it."""
    cfg = _paid_config(semantic_kg=True)
    costs = _status_costs(cfg=cfg, total_tokens=50_000, total_chunks=100, latest_run=None)
    semantic = _estimate_semantic_kg_cost_usd(
        alias=SEMANTIC_ALIAS,
        chunks_in_scope=min(100, int(cfg.graph_indexing.semantic_kg_max_chunks)),
        enrich_max_chars=int(cfg.enrichment.enrich_max_chars),
    )
    assert semantic is not None and semantic > 0
    assert costs.semantic_kg_cost == pytest.approx(semantic)
    assert costs.embedding_cost is not None
    assert costs.total_cost == pytest.approx(float(costs.embedding_cost) + semantic)
