"""Figures are part of the run record.

Before this, a run that described 125 figures persisted a summary that mentioned none of it:
the operator could read the figure counts once, in the live terminal, and never again. The
dashboard's cost card, the "recent runs" list and any later audit all read the persisted
summary, so the counts and the priced ceiling have to survive the run, not just the stream.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime

import pytest

import server.api.index as index_api
from server.api.index import (
    FigureRunTotals,
    _estimate_figure_description_cost_usd,
    _figure_run_totals,
    _flush_run_events_sync,
    _load_latest_run_summary,
    _publish_complete,
)
from server.models.index import IndexRunSummary, IndexStats
from server.models.tribrid_config_model import TriBridConfig


@pytest.fixture(autouse=True)
def isolate_index_run_storage(tmp_path) -> Generator[None, None, None]:
    """Runs land under tmp_path, never in the operator's data/index_runs/."""
    old_runs_dir = index_api._INDEX_RUNS_DIR
    old_status = dict(index_api._STATUS)
    old_stats = dict(index_api._STATS)
    old_status_run_id = dict(index_api._STATUS_RUN_ID)

    index_api._INDEX_RUNS_DIR = tmp_path
    index_api._STATUS.clear()
    index_api._STATS.clear()
    index_api._STATUS_RUN_ID.clear()
    try:
        yield
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir
        index_api._STATUS.clear()
        index_api._STATUS.update(old_status)
        index_api._STATS.clear()
        index_api._STATS.update(old_stats)
        index_api._STATUS_RUN_ID.clear()
        index_api._STATUS_RUN_ID.update(old_status_run_id)


def _stats(repo_id: str) -> IndexStats:
    return IndexStats(
        repo_id=repo_id,
        total_files=3,
        total_chunks=42,
        total_tokens=9000,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        last_indexed=datetime.now(UTC),
        file_breakdown={".pdf": 3},
    )


def test_run_summary_declares_the_four_figure_fields_with_descriptions() -> None:
    fields = IndexRunSummary.model_fields
    for name in (
        "figures_described",
        "figures_failed",
        "figures_undescribed",
        "figure_description_cost_usd",
    ):
        assert name in fields, f"IndexRunSummary is missing {name}"
        assert (fields[name].description or "").strip(), f"{name} needs a Field(description=...)"
    # Counts default to zero (a run that described nothing still reports zero, not null);
    # the price defaults to None (unknown alias pricing is not "free").
    assert fields["figures_described"].default == 0
    assert fields["figures_failed"].default == 0
    assert fields["figures_undescribed"].default == 0
    assert fields["figure_description_cost_usd"].default is None


def test_priced_totals_charge_the_run_alias_ceiling_for_what_was_described() -> None:
    """The run record quotes the same ceiling the pre-run estimate does, so the two numbers
    are comparable: the estimate prices a guessed figure count, the record prices the real one.
    """
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = True
    cfg.indexing.figures.vision_model = "z-ai.glm-5.3-flash"
    cfg.indexing.figures.max_completion_tokens = 2500

    totals = _figure_run_totals(cfg, described=125, failed=2, undescribed=17)
    assert totals.described == 125
    assert totals.failed == 2
    assert totals.undescribed == 17
    expected = _estimate_figure_description_cost_usd(
        alias="z-ai.glm-5.3-flash", figures=127, max_completion_tokens=2500
    )
    assert expected is not None and expected > 0
    assert totals.cost_usd == expected


def test_a_run_that_described_nothing_carries_no_price() -> None:
    """A run without attempted descriptions has no ceiling; skipped figures alone
    do not prove any provider charge. Failed calls are covered by the attempt matrix.
    """
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    totals = _figure_run_totals(cfg, described=0, failed=0, undescribed=8)
    assert totals.described == 0
    assert totals.failed == 0
    assert totals.undescribed == 8
    assert totals.cost_usd is None


def test_an_unpriceable_alias_leaves_the_cost_unknown_not_zero() -> None:
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.vision_model = "nope.not-a-model"
    assert _figure_run_totals(cfg, described=5, failed=0, undescribed=0).cost_usd is None


async def test_the_completing_summary_round_trips_the_figure_totals() -> None:
    """`_publish_complete` is the only writer of a `complete` summary; what it writes is what
    `/api/index/{corpus}/runs/latest` and the dashboard cost card read back.
    """
    repo_id = "figures-run-record"
    run_id = "run-figs-1"
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=64)
    totals = FigureRunTotals(described=125, failed=2, undescribed=17, cost_usd=0.1234)

    _publish_complete(
        repo_id=repo_id,
        run_id=run_id,
        started_at=datetime.now(UTC),
        stats=_stats(repo_id),
        queue=queue,
        figures=totals,
    )
    await asyncio.to_thread(_flush_run_events_sync)

    loaded = await asyncio.to_thread(_load_latest_run_summary, repo_id)
    assert loaded is not None
    assert loaded.status == "complete"
    assert loaded.total_chunks == 42
    assert loaded.figures_described == 125
    assert loaded.figures_failed == 2
    assert loaded.figures_undescribed == 17
    assert loaded.figure_description_cost_usd == pytest.approx(0.1234)


async def test_a_run_with_no_figure_phase_persists_zero_counts_and_no_price() -> None:
    repo_id = "figures-run-record-off"
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=64)

    _publish_complete(
        repo_id=repo_id,
        run_id="run-nofigs-1",
        started_at=datetime.now(UTC),
        stats=_stats(repo_id),
        queue=queue,
        figures=None,
    )
    await asyncio.to_thread(_flush_run_events_sync)

    loaded = await asyncio.to_thread(_load_latest_run_summary, repo_id)
    assert loaded is not None
    counts = (loaded.figures_described, loaded.figures_failed, loaded.figures_undescribed)
    assert counts == (0, 0, 0)
    assert loaded.figure_description_cost_usd is None
