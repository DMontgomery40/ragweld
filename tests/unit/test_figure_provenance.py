"""A described figure's chunk carries its region, the parsed JSON and a figure chunk kind."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from docling.document_converter import DocumentConverter
from docling_core.types.doc import PictureItem
from docling_core.types.doc.document import (
    DescriptionAnnotation,
    DescriptionMetaField,
    PictureClassificationMetaField,
    PictureClassificationPrediction,
    PictureMeta,
)

from server.indexing.chunker import Chunker
from server.indexing.figure_chunking import chunk_document_with_figures
from server.indexing.figure_serializer import make_markdown_serializer
from server.indexing.provenance import stamp_provenance
from server.indexing.text_extractors import (
    ExtractedDocument,
    SourceSpan,
    _build_source_map,
    _read_with_docling,
)
from server.models.index import Chunk, FigureAnnotation, PageRegion
from server.models.tribrid_config_model import ChunkingConfig, TokenizationConfig, TriBridConfig
from tests.fixtures.pdf_builder import apollo_figure_pages

REPLY = json.dumps({"kind": "drawing", "summary": "Landing gear strut and footpad with the lunar surface sensing probe.", "labels": ["PROBE", "FOOTPAD"], "components": ["strut", "footpad"], "connections": ["strut -> footpad"], "values": [], "references": []})


@pytest.fixture(scope="module")
def described_doc():
    doc = DocumentConverter().convert(str(apollo_figure_pages())).document
    pic = next(p for p, _ in doc.iterate_items() if isinstance(p, PictureItem) and p.prov)
    # Baseline: how many items are unlocated in this scanned fixture with no description at
    # all. Real-world OCR noise on a scanned page can leave non-figure items unlocated
    # independent of anything this task does; that baseline isolates figure-specific breakage
    # from pre-existing extraction noise.
    baseline_serializer = make_markdown_serializer(doc)
    baseline_full = baseline_serializer.serialize().text
    _, baseline_unlocated = _build_source_map(doc, baseline_serializer, baseline_full)

    pic.meta = PictureMeta(
        description=DescriptionMetaField(text=REPLY, created_by="test"),
        classification=PictureClassificationMetaField(
            predictions=[PictureClassificationPrediction(class_name="drawing", confidence=0.9)]
        ),
    )
    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    spans, unlocated = _build_source_map(doc, serializer, full)
    return doc, pic, full, spans, unlocated, baseline_unlocated


def test_source_map_attaches_the_figure_to_the_pictures_span(described_doc) -> None:
    doc, pic, full, spans, unlocated, baseline_unlocated = described_doc
    figure_spans = [s for s in spans if s.figure is not None]
    assert len(figure_spans) == len(pic.prov)
    span = figure_spans[0]
    assert span.figure.components == ["strut", "footpad"]
    assert full[span.char_start:span.char_end].startswith("Figure")
    assert span.region.page == pic.prov[0].page_no
    assert 0.0 <= span.region.left < span.region.right <= 1.0
    # Every figure span must be located, and describing the figure must not introduce any
    # *new* unlocated items beyond whatever OCR noise the scanned fixture already has.
    assert unlocated == baseline_unlocated


def test_stamp_provenance_marks_the_figure_chunk(described_doc) -> None:
    doc, pic, full, spans, _, _ = described_doc
    figure_span = next(s for s in spans if s.figure is not None)
    assert figure_span.figure_class == "drawing"
    cfg = TriBridConfig()
    chunks = Chunker(cfg.chunking, cfg.tokenization).chunk_text(
        "apollo11_figure_pages.pdf", full, base_char_offset=0, base_line=1, starting_ordinal=0
    )
    stamp_provenance(chunks, extraction="docling", spans=spans)
    figure_chunks = [c for c in chunks if c.metadata.get("chunk_kind") == "figure"]
    assert figure_chunks, "the chunk holding the figure block must be a figure chunk"
    chunk = figure_chunks[0]
    assert chunk.metadata["figure"]["labels"] == ["PROBE", "FOOTPAD"]
    assert chunk.metadata["figure_class"] == "drawing"
    assert chunk.provenance is not None and figure_span.region in chunk.provenance.regions
    text_chunks = [c for c in chunks if c.metadata.get("chunk_kind") != "figure"]
    assert all("figure" not in c.metadata for c in text_chunks)


def test_atomic_figure_chunk_from_the_real_apollo_fixture(described_doc) -> None:
    """End-to-end on the two-page Apollo fixture (M-92): the figure-aware path keeps the whole
    described block in ONE chunk_kind=figure chunk even under a tight window that would otherwise
    straddle it, and no other chunk holds a fragment of the description."""
    _doc, _pic, full, spans, _unlocated, _baseline = described_doc
    figure_span = next(s for s in spans if s.figure is not None)
    fig_text = full[figure_span.char_start : figure_span.char_end]

    cfg = ChunkingConfig(
        chunking_strategy="fixed_chars", chunk_size=200, chunk_overlap=40, min_chunk_chars=50
    )
    chunker = Chunker(cfg, TokenizationConfig(strategy="whitespace"))
    chunks = chunk_document_with_figures(chunker, "apollo11_figure_pages.pdf", full, spans)
    stamp_provenance(chunks, extraction="docling", spans=spans)

    whole = [c for c in chunks if c.content == fig_text]
    assert len(whole) == 1, "the described figure block must be one atomic chunk"
    figure_chunks = [c for c in chunks if c.metadata.get("chunk_kind") == "figure"]
    assert figure_chunks == whole, "the atomic block is exactly the figure chunk"
    assert figure_chunks[0].metadata["figure"]["labels"] == ["PROBE", "FOOTPAD"]
    # No other chunk holds the block's structured heading -- the M-92 fragment cannot recur.
    assert sum("Labels: PROBE, FOOTPAD" in c.content for c in chunks) == 1
    text_chunks = [c for c in chunks if c.metadata.get("chunk_kind") != "figure"]
    assert all("Labels: PROBE, FOOTPAD" not in c.content for c in text_chunks)


def test_figure_chunk_with_no_resolved_class_gets_no_figure_class_key() -> None:
    """``figure_class`` is only set when the picture serializer actually resolved a class name;
    a described-but-unclassified figure must not get a stray ``figure_class`` key backed by
    nothing.
    """
    region = PageRegion(page=1, left=0.1, top=0.1, right=0.9, bottom=0.5)
    full = "Figure: A short drawing."
    spans = (
        SourceSpan(
            char_start=0,
            char_end=len(full),
            region=region,
            figure=FigureAnnotation(summary="A short drawing."),
            figure_class=None,
        ),
    )
    chunk = Chunk(chunk_id="f:1-1:0", content=full, file_path="f", start_line=1, end_line=1, metadata={"char_start": 0, "char_end": len(full)})
    stamp_provenance([chunk], extraction="docling", spans=spans)
    assert chunk.metadata.get("chunk_kind") == "figure"
    assert chunk.metadata.get("figure") is not None
    assert "figure_class" not in chunk.metadata


def test_a_chunk_that_only_brushes_a_figure_stays_a_text_chunk() -> None:
    region = PageRegion(page=1, left=0.1, top=0.1, right=0.9, bottom=0.5)
    fig_text = "Figure: A\nshort."
    prose = "x" * 400
    full = prose + "\n" + fig_text
    spans = (
        SourceSpan(
            char_start=len(prose) + 1,
            char_end=len(full),
            region=region,
            figure=FigureAnnotation(summary="short."),
        ),
    )
    chunk = Chunk(chunk_id="f:1-1:0", content=full, file_path="f", start_line=1, end_line=1, metadata={"char_start": 0, "char_end": len(full)})
    stamp_provenance([chunk], extraction="docling", spans=spans)
    assert chunk.provenance is not None and chunk.provenance.regions == [region]
    assert chunk.metadata.get("chunk_kind") != "figure" and "figure" not in chunk.metadata


def test_a_multi_prov_figure_does_not_double_count_its_own_coverage() -> None:
    """``_build_source_map`` emits one span per ``prov`` entry, all carrying that item's single
    [char_start, char_end) range, so a figure that spans two pages (or two columns) produces
    two spans over the SAME characters. Summing them naively double-counts the coverage and
    can push a chunk the figure barely touches over the 50% "this is a figure chunk" bar.
    """
    fig_text = "Figure: A short caption." + "y" * 96  # 120 chars = 30% of the chunk
    prose = "x" * 280
    full = prose + fig_text
    assert len(full) == 400 and len(fig_text) == 120
    figure = FigureAnnotation(summary="A short caption.")
    # One item, two prov entries -> two spans, identical char range, different pages.
    spans = tuple(
        SourceSpan(
            char_start=len(prose),
            char_end=len(full),
            region=PageRegion(page=page, left=0.1, top=0.1, right=0.9, bottom=0.5),
            figure=figure,
        )
        for page in (1, 2)
    )
    chunk = Chunk(chunk_id="f:1-1:0", content=full, file_path="f", start_line=1, end_line=1, metadata={"char_start": 0, "char_end": len(full)})
    stamp_provenance([chunk], extraction="docling", spans=spans)
    assert chunk.provenance is not None
    assert [r.page for r in chunk.provenance.regions] == [1, 2], "both prov regions still land"
    assert chunk.metadata.get("chunk_kind") != "figure", (
        "120 of 400 chars is 30% coverage, under the 50% bar -- counting the duplicated span "
        "twice would read as 60% and wrongly mark a mostly-prose chunk as a figure chunk"
    )
    assert "figure" not in chunk.metadata and "figure_class" not in chunk.metadata


def test_extracted_document_counts_default_to_zero() -> None:
    doc = ExtractedDocument(text="x", extraction="direct", kind="text")
    assert (doc.figures_described, doc.figures_failed, doc.figures_skipped) == (0, 0, 0)


def test_blank_meta_description_falls_back_to_a_non_blank_annotation() -> None:
    """``_read_with_docling``'s triage must mirror the serializer's exact fallback order (meta
    text first, a non-blank legacy annotation only when the meta text is blank) so the counts
    and the spans can never disagree: a picture whose meta description is blank but whose
    legacy ``DescriptionAnnotation`` carries real text must be counted as described, not
    failed, and its span must carry the resulting ``FigureAnnotation``.
    """
    doc = DocumentConverter().convert(str(apollo_figure_pages())).document
    pictures = [p for p, _ in doc.iterate_items() if isinstance(p, PictureItem) and p.prov]
    pic = pictures[0]
    pic.meta = PictureMeta(description=DescriptionMetaField(text="", created_by="test"))
    pic.annotations.append(
        DescriptionAnnotation(
            text="A real fallback description of the landing gear strut and footpad.",
            provenance="test",
        )
    )

    class _FixedDocConverter:
        """Hands back the already-converted (and mutated) document instead of reconverting."""

        def convert(self, _path: str) -> Any:
            return SimpleNamespace(document=doc)

    extracted = _read_with_docling(apollo_figure_pages(), converter=_FixedDocConverter())
    assert extracted is not None
    assert extracted.figures_described == 1, "the non-blank legacy annotation must count as described"
    assert extracted.figures_failed == 0
    assert extracted.figures_skipped == len(pictures) - 1, "the other, untouched picture stays skipped"
    figure_spans = [s for s in extracted.spans if s.figure is not None]
    assert figure_spans and "landing gear strut" in figure_spans[0].figure.summary
