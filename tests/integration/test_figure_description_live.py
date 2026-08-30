"""One real Apollo figure described through the configured vision alias, end to end into a
figure chunk.

Real question: What does Figure 5-5 show about pitch attitude during powered descent?
The fixture (``apollo11_figure_pages.pdf``) is two consecutive scanned pages of the Apollo 11
Mission Report on which Docling's layout model detects at least one figure. This test proves
the whole live path -- gateway route resolution, Docling picture description through the
configured vision alias, source-map location, and chunk stamping -- by asserting the resulting
figure chunk's description actually answers that question rather than being generic boilerplate.
"""

from __future__ import annotations

import os
import typing

import pytest

from server.api.index import _resolve_figure_route
from server.gateway_catalog import warm_gateway_catalog
from server.indexing.chunker import Chunker
from server.indexing.provenance import stamp_provenance
from server.indexing.text_extractors import extract_text_for_path
from server.models.index import FigureKind
from server.models.tribrid_config_model import TriBridConfig
from tests.fixtures.pdf_builder import apollo_figure_pages

pytestmark = pytest.mark.skipif(
    not os.getenv("RAGWELD_LIVE_GATEWAY"),
    reason="set RAGWELD_LIVE_GATEWAY=1 on LXC100 to run against the real LiteLLM gateway",
)


def test_real_figure_is_described_and_becomes_a_figure_chunk() -> None:
    warm_gateway_catalog()
    cfg = TriBridConfig(indexing={"figures": {"enabled": True}})
    gateway = _resolve_figure_route(cfg)
    assert gateway is not None and gateway.model == cfg.indexing.figures.vision_model

    extracted = extract_text_for_path(
        apollo_figure_pages(), figures=cfg.indexing.figures, gateway=gateway
    )
    assert extracted is not None
    # Docling absorbs a per-picture gateway failure rather than raising, so a non-zero
    # described count is the only proof the vision alias was actually reached.
    assert extracted.figures_described >= 1
    # The JSON reply is parsed into structured fields; it must never leak into the markdown.
    assert '"summary"' not in extracted.text

    figure_spans = [s for s in extracted.spans if s.figure is not None]
    assert figure_spans and figure_spans[0].figure.summary.strip()

    chunks = Chunker(cfg.chunking, cfg.tokenization).chunk_text(
        "apollo11_figure_pages.pdf",
        extracted.text,
        base_char_offset=0,
        base_line=1,
        starting_ordinal=0,
    )
    stamp_provenance(chunks, extraction=extracted.extraction, spans=extracted.spans)
    figure_chunks = [c for c in chunks if c.metadata.get("chunk_kind") == "figure"]
    assert figure_chunks, "the chunk holding the figure block must be a figure chunk"

    fig = figure_chunks[0].metadata["figure"]
    print(f"figures_described={extracted.figures_described}")
    print(f"figure_metadata={fig}")
    print(f"provenance_regions={figure_chunks[0].provenance.regions if figure_chunks[0].provenance else None}")

    assert fig["summary"] and figure_chunks[0].provenance and figure_chunks[0].provenance.regions
    assert fig["kind"] in typing.get_args(FigureKind)

    # A real Apollo question must be answerable from the description: it must mention
    # something about pitch/attitude/descent, not read as generic boilerplate.
    summary_lower = fig["summary"].lower()
    domain_words = ("pitch", "attitude", "descent", "landing", "roll")
    assert any(word in summary_lower for word in domain_words), (
        f"figure summary did not mention any of {domain_words}: {fig['summary']!r}"
    )
