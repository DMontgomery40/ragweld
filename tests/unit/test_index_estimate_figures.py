"""The estimate itemises figure description when figures are enabled and only then."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.api.index import (
    _EST_OVERHEAD_SECONDS,
    _EST_RANGE_HIGH_MULT,
    _EST_RANGE_LOW_MULT,
    _FIGURE_INPUT_TOKENS,
    _FIGURE_SECONDS_PER_CALL,
    _FIGURES_PER_PAGE_HEURISTIC,
    _count_pdf_pages,
    _estimate_figure_description_cost_usd,
    _estimate_figure_seconds,
    _estimate_figures,
    _figure_seconds_assumption,
    _index_time_model,
)
from server.models.index import IndexEstimate
from server.models.tribrid_config_model import TriBridConfig
from tests.fixtures.pdf_builder import apollo_figure_pages, build_pdf


def test_cost_uses_catalog_prices_for_the_alias() -> None:
    cost = _estimate_figure_description_cost_usd(alias="z-ai.glm-5.3-flash", figures=100, max_completion_tokens=600)
    assert cost is not None and cost > 0
    # input 1200 tokens/figure at $0.000075/1k + output 600 at $0.00025/1k, for 100 figures
    assert abs(cost - (100 * (1.2 * 0.000075 + 0.6 * 0.00025))) < 1e-9


def test_cost_is_zero_for_no_figures_and_none_for_unknown_alias() -> None:
    assert _estimate_figure_description_cost_usd(alias="z-ai.glm-5.3-flash", figures=0, max_completion_tokens=600) == 0.0
    assert _estimate_figure_description_cost_usd(alias="nope.not-a-model", figures=5, max_completion_tokens=600) is None


def test_pdf_page_count_reads_real_pages() -> None:
    assert _count_pdf_pages([Path(apollo_figure_pages())]) == 2
    assert _count_pdf_pages([Path("/nonexistent/x.pdf")]) == 0


def test_estimate_model_carries_figure_fields() -> None:
    fields = IndexEstimate.model_fields
    assert "estimated_figures" in fields and "figure_description_cost_usd" in fields


def test_estimate_figures_is_none_when_figures_are_disabled() -> None:
    cfg = TriBridConfig()
    assert cfg.indexing.figures.enabled is False
    pdf_paths = [Path(apollo_figure_pages())]
    assert _estimate_figures(cfg, pdf_paths) == (None, None)


def test_the_per_page_heuristic_is_the_measured_one() -> None:
    """Pins the recalibration itself, not just its rounded output.

    The Phase 1 run on the Apollo 11 Mission Report detected 140 pictures across 359 scanned
    pages (0.39/page); the original 0.6 overshot the figure count by 54%. ``round(2 * 0.4)``
    and ``round(2 * 0.6)`` are both 1, so the two-page fixture below cannot tell the two
    constants apart -- this assertion is the only thing in the suite that can.
    """
    assert _FIGURES_PER_PAGE_HEURISTIC == 0.4
    assert _FIGURE_INPUT_TOKENS == 1200


def test_estimate_figures_counts_pages_and_prices_when_enabled() -> None:
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = True
    pdf_paths = [Path(apollo_figure_pages())]
    estimated_figures, figure_cost = _estimate_figures(cfg, pdf_paths)
    # apollo_figure_pages() is a real 2-page PDF; heuristic is 0.4 figures/page -> round(0.8).
    assert estimated_figures == round(2 * _FIGURES_PER_PAGE_HEURISTIC) == 1
    assert figure_cost is not None and figure_cost > 0


def test_the_priced_figure_cost_is_a_ceiling_on_the_full_completion_budget() -> None:
    """The estimate charges the whole ``max_completion_tokens`` budget as output for every
    figure, so the quoted number is an upper bound rather than a forecast: a real reply spends
    only part of that budget (the measured run cost a third of its estimate). The UI says
    "Figures <= $x" for exactly this reason.
    """
    budget = 2500
    ceiling = _estimate_figure_description_cost_usd(
        alias="z-ai.glm-5.3-flash", figures=10, max_completion_tokens=budget
    )
    half = _estimate_figure_description_cost_usd(
        alias="z-ai.glm-5.3-flash", figures=10, max_completion_tokens=budget // 2
    )
    assert ceiling is not None and half is not None
    assert ceiling > half, "output pricing must scale with the full budget, not a fixed guess"


def test_a_pdf_too_short_to_round_up_to_one_figure_omits_the_line(tmp_path) -> None:
    """A zero figure count must omit the line, not quote $0.00.

    At 0.4 figures/page a one- or two-page document rounds to zero figures, and a short PDF
    plainly can still contain a figure. Returning ``(0, 0.0)`` would render "Figures <= $0.00
    (~0)" -- exactly the "$0 figure cost that isn't really zero" that ``_estimate_figures``
    documents itself as avoiding. This case only became reachable when the heuristic was
    recalibrated from 0.6 to 0.4, so it is pinned here.
    """
    one_pager = tmp_path / "one-page.pdf"
    one_pager.write_bytes(build_pdf([["A single page that may well carry one figure."]]))
    assert _count_pdf_pages([one_pager]) == 1
    assert round(1 * _FIGURES_PER_PAGE_HEURISTIC) == 0

    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = True
    assert _estimate_figures(cfg, [one_pager]) == (None, None)


def test_estimate_figures_is_none_when_describe_is_off_or_no_pdfs() -> None:
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = False
    assert _estimate_figures(cfg, [Path(apollo_figure_pages())]) == (None, None)

    cfg2 = TriBridConfig()
    cfg2.indexing.figures.enabled = True
    assert _estimate_figures(cfg2, []) == (None, None)


def test_the_per_call_figure_duration_is_the_measured_one() -> None:
    """Pins the calibration, not just its arithmetic.

    Measured on the Apollo 11 run: about 140 figures added roughly 12 minutes of wall clock at
    ``concurrency=4``, i.e. ~5.1 s per figure of wall time, so ~20 s per vision call. Before
    this the dialog quoted 6m51s-21m29s for a run that took 32 minutes, about 12 of them
    vision calls -- the figure phase was simply absent from the time estimate.
    """
    assert _FIGURE_SECONDS_PER_CALL == 20.0


def test_figure_seconds_divide_the_calls_across_the_configured_concurrency() -> None:
    # The two-page fixture rounds to one figure; one 20 s call, four in flight -> 5 s.
    assert _estimate_figure_seconds(figures=1, concurrency=4) == 5.0
    assert _estimate_figure_seconds(figures=140, concurrency=4) == 700.0
    # Serial description is the full per-call cost.
    assert _estimate_figure_seconds(figures=3, concurrency=1) == 60.0


def test_no_figures_takes_no_time_and_a_broken_concurrency_never_divides_by_zero() -> None:
    assert _estimate_figure_seconds(figures=0, concurrency=4) == 0.0
    assert _estimate_figure_seconds(figures=-5, concurrency=4) == 0.0
    assert _estimate_figure_seconds(figures=2, concurrency=0) == 40.0


def test_the_figure_time_assumption_names_the_count_the_rate_and_the_concurrency() -> None:
    """The dialog's assumptions are the only place the operator can see WHY the estimate moved
    when they turned figures on, so all three inputs have to appear.
    """
    line = _figure_seconds_assumption(figures=140, concurrency=4)
    assert "140" in line
    assert "20" in line
    assert "4" in line


def test_the_estimate_model_carries_the_figure_time_field() -> None:
    fields = IndexEstimate.model_fields
    assert "estimated_seconds_figures" in fields
    assert (fields["estimated_seconds_figures"].description or "").strip()
    assert fields["estimated_seconds_figures"].default is None


def test_the_two_page_fixture_prices_and_times_one_figure_together() -> None:
    """The count that drives the cost is the count that drives the time: one heuristic, both
    numbers, so the dialog can never quote a figure price for a run it says takes no longer.
    """
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = True
    cfg.indexing.figures.concurrency = 4
    estimated_figures, figure_cost = _estimate_figures(cfg, [Path(apollo_figure_pages())])
    assert estimated_figures == 1 and figure_cost is not None and figure_cost > 0
    assert (
        _estimate_figure_seconds(
            figures=estimated_figures, concurrency=cfg.indexing.figures.concurrency
        )
        == 5.0
    )


def test_the_time_range_and_the_breakdown_come_from_one_model() -> None:
    """The dialog quoted a range whose own breakdown did not fit inside it.

    "Time (est): 14m 3s-44m 17s" printed next to "Embed ~17m 10s + Figures ~12m 0s": the
    embed leg alone exceeded the lower bound, and the parts summed to ~29m, which is neither
    endpoint nor the midpoint. The range came from ``total x 0.6 / x 1.9`` while the
    breakdown derived embed as ``midpoint - other phases``, and that midpoint is
    ``1.25 x total + overhead`` -- so the embed leg was inflated by a quarter of the run.
    """
    model = _index_time_model(
        embedding_seconds=1030.0, semantic_kg_seconds=0.0, figure_seconds=720.0
    )

    assert model.parts_total == pytest.approx(model.seconds)
    assert model.low <= model.seconds <= model.high
    assert model.embedding <= model.seconds
    # Every phase fits inside the range that is quoted beside it.
    assert model.embedding + model.semantic_kg + model.figures <= model.high


def test_the_old_two_model_breakdown_would_have_failed_that_invariant() -> None:
    """Not a vacuous assertion: the arithmetic this replaced breaks it on the drive's numbers."""
    phases = 1030.0 + 720.0
    old_low = phases * _EST_RANGE_LOW_MULT + _EST_OVERHEAD_SECONDS
    old_high = phases * _EST_RANGE_HIGH_MULT + _EST_OVERHEAD_SECONDS * 2.0
    old_embed_leg = (old_low + old_high) / 2 - 720.0

    assert old_embed_leg > old_low, "the old embed leg exceeded the range's own lower bound"


def test_a_zero_length_run_still_has_a_coherent_model() -> None:
    model = _index_time_model(embedding_seconds=0.0, semantic_kg_seconds=0.0, figure_seconds=0.0)

    assert model.seconds == pytest.approx(_EST_OVERHEAD_SECONDS)
    assert model.parts_total == pytest.approx(model.seconds)
    assert model.low <= model.seconds <= model.high


def test_the_estimate_model_carries_the_point_estimate_and_its_phases() -> None:
    fields = IndexEstimate.model_fields
    for name in (
        "estimated_seconds",
        "estimated_seconds_embedding",
        "estimated_seconds_overhead",
        "estimated_seconds_low",
        "estimated_seconds_high",
    ):
        assert name in fields
