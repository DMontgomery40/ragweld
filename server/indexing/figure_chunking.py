"""Figure-aware document chunking: keep each described figure block atomic.

The general chunker windows the serialized markdown by size, which can split a figure's
description block across a chunk boundary so a citation lands on a mid-word fragment
(" the following week.\nLabels: …") instead of the whole figure. This adapter turns the
extractor's source map into the figure ``[char_start, char_end)`` ranges the chunker needs
to cut those blocks out whole, then delegates to ``Chunker.chunk_document``.

Only DESCRIBED figures are made atomic: a classified-but-undescribed picture is a single
header line with no description block to fragment, so it is left to the ordinary windowing.
"""

from __future__ import annotations

from collections.abc import Sequence

from server.indexing.chunker import Chunker
from server.indexing.text_extractors import SourceSpan
from server.models.index import Chunk


def figure_ranges_from_spans(spans: Sequence[SourceSpan]) -> list[tuple[int, int]]:
    """Distinct ``[char_start, char_end)`` ranges of every described figure, sorted.

    ``_build_source_map`` emits one span per ``prov`` entry, so a figure spanning two pages
    contributes several spans over the SAME char range; the set collapses those to one range.
    ``Chunker._normalize_figure_ranges`` clamps and merges further, but de-duplicating here
    keeps the contract of this function honest on its own.
    """
    return sorted({(span.char_start, span.char_end) for span in spans if span.figure is not None})


def chunk_document_with_figures(
    chunker: Chunker, file_path: str, content: str, spans: Sequence[SourceSpan]
) -> list[Chunk]:
    """Chunk ``content`` keeping described-figure blocks atomic; identical to ``chunk_file``
    when the document has no described figures."""
    return chunker.chunk_document(
        file_path, content, figure_ranges=figure_ranges_from_spans(spans)
    )
