"""A described figure is one atomic chunk (M-92).

The general chunker windows the serialized markdown by size, which split a figure's
description block across a chunk boundary so a citation landed on a mid-word fragment
(" the following week.\nLabels: …"). ``chunk_document_with_figures`` cuts described figure
blocks out whole; only the text between figures is windowed. These are pure tests: the
figure spans are built directly, no Docling, no mocks.
"""

from __future__ import annotations

from server.indexing.chunker import Chunker
from server.indexing.figure_chunking import chunk_document_with_figures, figure_ranges_from_spans
from server.indexing.provenance import stamp_provenance
from server.indexing.text_extractors import SourceSpan
from server.models.index import FigureAnnotation, PageRegion
from server.models.tribrid_config_model import ChunkingConfig, TokenizationConfig

_REGION = PageRegion(page=73, left=0.1, top=0.1, right=0.9, bottom=0.6)

# The figure block exactly as the serializer emits it: caption/summary head, then section
# headings. The straddle point that motivated M-92 is "... the following week.\nLabels: ...".
# The summary is deliberately long (>100 whitespace tokens with the head) so the section-split
# test can force a split at max_chunk_tokens=100, the config floor.
FIGURE_BLOCK = (
    "Figure (drawing): Landing gear strut and footpad, sheet 2.\n"
    "The probe extends below the footpad and senses the lunar surface, and the descent engine "
    "is commanded off at first contact so the vehicle settles gently onto the regolith, and the "
    "crew reads the blue contact light, and the guidance computer holds attitude while the "
    "struts absorb the touchdown load, and the dust settles around the footpads, and the "
    "commander confirms a stable stance, and the mission timeline then advances toward the "
    "surface excursion that mission control had planned for the following week.\n"
    "Labels: PROBE, FOOTPAD, STRUT\n"
    "Components: strut, footpad, probe\n"
    "Connections: probe -> descent engine cutoff, footpad -> regolith\n"
    "Values: strut stroke 32 in, footpad diameter 37 in\n"
    "References: sheet 2, figure 5-6"
)


def _chunker(**overrides: object) -> Chunker:
    cfg = ChunkingConfig(
        chunking_strategy="fixed_chars",
        chunk_size=200,
        chunk_overlap=40,
        min_chunk_chars=50,
        **overrides,  # type: ignore[arg-type]
    )
    return Chunker(cfg, TokenizationConfig(strategy="whitespace"))


def _doc_with_one_figure() -> tuple[str, tuple[SourceSpan, ...], int, int]:
    prose_before = "A" * 350
    prose_after = "B" * 200
    fig_start = len(prose_before) + 1  # after the joining newline
    fig_end = fig_start + len(FIGURE_BLOCK)
    content = f"{prose_before}\n{FIGURE_BLOCK}\n{prose_after}"
    assert content[fig_start:fig_end] == FIGURE_BLOCK
    span = SourceSpan(
        char_start=fig_start,
        char_end=fig_end,
        region=_REGION,
        figure=FigureAnnotation(
            kind="drawing",
            summary="Landing gear strut and footpad.",
            labels=["PROBE", "FOOTPAD", "STRUT"],
            components=["strut", "footpad", "probe"],
            connections=["probe -> descent engine cutoff", "footpad -> regolith"],
            values=["strut stroke 32 in", "footpad diameter 37 in"],
            references=["sheet 2, figure 5-6"],
        ),
        figure_class="drawing",
    )
    return content, (span,), fig_start, fig_end


def test_the_general_chunker_splits_the_figure_block_across_a_boundary() -> None:
    """RED baseline: the ordinary windowing path fragments the figure block — no single chunk
    holds it whole, and the ``the following week.\\nLabels:`` seam lands mid-chunk. This is the
    defect the atomic path must remove."""
    content, _spans, _s, _e = _doc_with_one_figure()
    chunks = _chunker().chunk_file("apollo.pdf", content)
    assert not any(FIGURE_BLOCK in c.content for c in chunks), (
        "the size windows happen to keep the whole figure block together; pick offsets that straddle"
    )


def test_a_described_figure_is_one_whole_chunk() -> None:
    content, spans, fig_start, fig_end = _doc_with_one_figure()
    chunker = _chunker()
    chunks = chunk_document_with_figures(chunker, "apollo.pdf", content, spans)

    whole = [c for c in chunks if c.content == FIGURE_BLOCK]
    assert len(whole) == 1, "the figure block must appear whole in exactly one chunk"
    fig = whole[0]
    assert fig.metadata["char_start"] == fig_start
    assert fig.metadata["char_end"] == fig_end

    # stamp_provenance is the authority for chunk_kind/metadata.figure; the whole-figure chunk
    # is 100% covered by the figure span, so it is marked.
    stamp_provenance(chunks, extraction="docling", spans=spans)
    figure_chunks = [c for c in chunks if c.metadata.get("chunk_kind") == "figure"]
    assert len(figure_chunks) == 1 and figure_chunks[0].content == FIGURE_BLOCK
    assert figure_chunks[0].metadata["figure"]["labels"] == ["PROBE", "FOOTPAD", "STRUT"]

    # Both directions: no OTHER chunk holds any part of the figure block. The exact M-92 seam
    # ("the following week.\nLabels: PROBE") appears once, and no text chunk carries a heading.
    seam = "the following week.\nLabels: PROBE"
    assert sum(seam in c.content for c in chunks) == 1
    text_chunks = [c for c in chunks if c.metadata.get("chunk_kind") != "figure"]
    assert all("Labels:" not in c.content and "Components:" not in c.content for c in text_chunks)
    assert all("figure" not in c.metadata for c in text_chunks)


def test_ordinals_stay_contiguous_across_gap_and_figure() -> None:
    content, spans, _s, _e = _doc_with_one_figure()
    chunker = _chunker(emit_chunk_ordinal=True)
    chunks = chunk_document_with_figures(chunker, "apollo.pdf", content, spans)
    ordinals = [c.metadata["chunk_ordinal"] for c in chunks]
    assert ordinals == list(range(len(chunks))), "chunk_ordinal must be a contiguous 0..n sequence"


def test_no_figures_is_identical_to_chunk_file() -> None:
    content = "prose paragraph one.\n\n" + ("word " * 300)
    chunker = _chunker()
    via_document = chunker.chunk_document("doc.md", content, figure_ranges=[])
    via_file = chunker.chunk_file("doc.md", content)
    assert [(c.chunk_id, c.content) for c in via_document] == [
        (c.chunk_id, c.content) for c in via_file
    ]


def test_a_multi_prov_figure_yields_one_chunk_not_two() -> None:
    """A figure spanning two pages contributes one span per prov entry over the SAME char
    range; the atomic chunker must emit it once, not once per prov."""
    content, (span,), _s, _e = _doc_with_one_figure()
    two_prov = (
        span,
        SourceSpan(
            char_start=span.char_start,
            char_end=span.char_end,
            region=PageRegion(page=74, left=0.1, top=0.1, right=0.9, bottom=0.6),
            figure=span.figure,
            figure_class=span.figure_class,
        ),
    )
    assert figure_ranges_from_spans(two_prov) == [(span.char_start, span.char_end)]
    chunks = chunk_document_with_figures(_chunker(), "apollo.pdf", content, two_prov)
    assert sum(c.content == FIGURE_BLOCK for c in chunks) == 1


def test_an_oversized_figure_splits_only_at_section_headings() -> None:
    """Over ``max_chunk_tokens`` a figure is cut ONLY at Labels/Components/… headings, never
    mid-word; every piece stays a figure chunk and the pieces reconstruct the block."""
    content, spans, fig_start, fig_end = _doc_with_one_figure()
    # 100 is the config floor for max_chunk_tokens; the block is authored just past it so a
    # split is forced without a mock.
    chunker = _chunker(max_chunk_tokens=100)
    chunks = chunk_document_with_figures(chunker, "apollo.pdf", content, spans)
    stamp_provenance(chunks, extraction="docling", spans=spans)

    pieces = [c for c in chunks if c.metadata.get("chunk_kind") == "figure"]
    assert len(pieces) >= 2, "the block must actually be split at this token budget"
    pieces.sort(key=lambda c: c.metadata["char_start"])
    # The reconstruction is exact and gapless: cuts fall on line boundaries only.
    assert "".join(c.content for c in pieces) == FIGURE_BLOCK
    for c in pieces[:-1]:
        assert c.content.endswith("\n"), "a cut fell mid-line — figures split only at headings"
    for c in pieces[1:]:
        head = c.content.lstrip()
        assert head.startswith(("Labels:", "Components:", "Connections:", "Values:", "References:"))
    # No word is broken across a boundary: every piece is whole lines of the block.
    assert all(c.metadata["figure"]["labels"] == ["PROBE", "FOOTPAD", "STRUT"] for c in pieces)
