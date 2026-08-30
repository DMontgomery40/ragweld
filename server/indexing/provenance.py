"""Stamp typed provenance onto chunks from an extracted document's source map."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence

from server.indexing.text_extractors import SourceSpan
from server.models.index import Chunk, ChunkProvenance, ExtractionMethod, PageRegion


def spans_for_span(
    spans: Sequence[SourceSpan], starts: Sequence[int], char_start: int, char_end: int
) -> list[SourceSpan]:
    """Every source span overlapping [char_start, char_end), in reading order.

    ``spans`` must be sorted by ``char_start`` with non-decreasing ``char_end`` (the extractor
    guarantees this: spans are located with a monotonic cursor). Overlap is half-open:
    ``span.char_start < char_end and span.char_end > char_start``.
    """
    if not spans or char_end <= char_start:
        return []
    hi = bisect_left(starts, char_end)  # spans[:hi] start before the chunk ends
    found: list[SourceSpan] = []
    index = hi - 1
    while index >= 0 and spans[index].char_end > char_start:
        found.append(spans[index])
        index -= 1
    found.reverse()
    return found


def regions_for_span(
    spans: Sequence[SourceSpan], starts: Sequence[int], char_start: int, char_end: int
) -> list[PageRegion]:
    """Regions of every source span overlapping [char_start, char_end), in reading order."""
    return [span.region for span in spans_for_span(spans, starts, char_start, char_end)]


def stamp_provenance(
    chunks: Sequence[Chunk], *, extraction: ExtractionMethod, spans: Sequence[SourceSpan]
) -> None:
    """Set ``chunk.provenance`` on every chunk from its ``metadata.char_start/char_end``.

    A chunk with no overlapping span (direct extraction, or text that sits entirely inside
    serializer delimiters) gets an extraction-only provenance: pages ``None``, no regions.
    """
    starts = [span.char_start for span in spans]
    for chunk in chunks:
        raw_start = chunk.metadata.get("char_start")
        raw_end = chunk.metadata.get("char_end")
        regions: list[PageRegion] = []
        overlapping: list[SourceSpan] = []
        if isinstance(raw_start, int) and isinstance(raw_end, int):
            overlapping = spans_for_span(spans, starts, raw_start, raw_end)
            regions = [span.region for span in overlapping]
        pages = [region.page for region in regions]
        chunk.provenance = ChunkProvenance(
            extraction=extraction,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            regions=regions,
        )
        figure_spans = [span for span in overlapping if span.figure is not None]
        if not figure_spans or not isinstance(raw_start, int) or not isinstance(raw_end, int):
            continue
        # Sum over the DISTINCT char ranges: ``_build_source_map`` emits one span per ``prov``
        # entry of the same item, all carrying that item's single [char_start, char_end) range,
        # so a figure spanning two pages (or two columns) would otherwise be counted twice and
        # push a chunk it barely touches over the 50% bar. Deduplicating the identical ranges
        # is exact for that construction; genuinely different, overlapping figure ranges would
        # still be over-counted, which the source map does not produce today.
        covered = sum(
            max(0, min(end, raw_end) - max(start, raw_start))
            for start, end in {(span.char_start, span.char_end) for span in figure_spans}
        )
        chunk_len = max(1, raw_end - raw_start)
        if covered * 2 >= chunk_len:
            first = figure_spans[0]
            chunk.metadata["figure"] = first.figure.model_dump(mode="json")
            if first.figure_class:
                chunk.metadata["figure_class"] = first.figure_class
            chunk.metadata["chunk_kind"] = "figure"
