"""Stamp typed provenance onto chunks from an extracted document's source map."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence

from server.indexing.text_extractors import SourceSpan
from server.models.index import Chunk, ChunkProvenance, ExtractionMethod, PageRegion


def regions_for_span(
    spans: Sequence[SourceSpan], starts: Sequence[int], char_start: int, char_end: int
) -> list[PageRegion]:
    """Regions of every source span overlapping [char_start, char_end), in reading order.

    ``spans`` must be sorted by ``char_start`` with non-decreasing ``char_end`` (the extractor
    guarantees this: spans are located with a monotonic cursor). Overlap is half-open:
    ``span.char_start < char_end and span.char_end > char_start``.
    """
    if not spans or char_end <= char_start:
        return []
    hi = bisect_left(starts, char_end)  # spans[:hi] start before the chunk ends
    regions: list[PageRegion] = []
    index = hi - 1
    while index >= 0 and spans[index].char_end > char_start:
        regions.append(spans[index].region)
        index -= 1
    regions.reverse()
    return regions


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
        if isinstance(raw_start, int) and isinstance(raw_end, int):
            regions = regions_for_span(spans, starts, raw_start, raw_end)
        pages = [region.page for region in regions]
        chunk.provenance = ChunkProvenance(
            extraction=extraction,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            regions=regions,
        )
