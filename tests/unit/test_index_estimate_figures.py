"""The estimate itemises figure description when figures are enabled and only then."""

from __future__ import annotations

from pathlib import Path

from server.api.index import (
    _count_pdf_pages,
    _estimate_figure_description_cost_usd,
    _estimate_figures,
)
from server.models.index import IndexEstimate
from server.models.tribrid_config_model import TriBridConfig
from tests.fixtures.pdf_builder import apollo_figure_pages


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


def test_estimate_figures_counts_pages_and_prices_when_enabled() -> None:
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = True
    pdf_paths = [Path(apollo_figure_pages())]
    estimated_figures, figure_cost = _estimate_figures(cfg, pdf_paths)
    # apollo_figure_pages() is a real 2-page PDF; heuristic is 0.6 figures/page.
    assert estimated_figures == 1
    assert figure_cost is not None and figure_cost > 0


def test_estimate_figures_is_none_when_describe_is_off_or_no_pdfs() -> None:
    cfg = TriBridConfig()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = False
    assert _estimate_figures(cfg, [Path(apollo_figure_pages())]) == (None, None)

    cfg2 = TriBridConfig()
    cfg2.indexing.figures.enabled = True
    assert _estimate_figures(cfg2, []) == (None, None)
