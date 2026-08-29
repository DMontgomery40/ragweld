"""Chunk provenance stamping from an extracted document's source map."""

from __future__ import annotations

from server.indexing.chunker import Chunker
from server.indexing.provenance import regions_for_span, stamp_provenance
from server.indexing.text_extractors import SourceSpan, extract_text_for_path
from server.models.index import Chunk, PageRegion
from server.models.tribrid_config_model import ChunkingConfig
from tests.fixtures.pdf_builder import AURORA_REPORT_PDF, PAGE_TWO_SENTENCE


def _span(start: int, end: int, page: int, top: float = 0.1) -> SourceSpan:
    return SourceSpan(
        start, end, PageRegion(page=page, left=0.1, top=top, right=0.9, bottom=top + 0.05)
    )


def _chunk(start: int, end: int) -> Chunk:
    return Chunk(
        chunk_id=f"f.pdf:1-1:{start}",
        content="x",
        file_path="f.pdf",
        start_line=1,
        end_line=1,
        metadata={"char_start": start, "char_end": end},
    )


SPANS = (
    _span(0, 30, 1, 0.10),  # item A, page 1
    _span(32, 80, 1, 0.20),  # item B, page 1
    _span(82, 120, 2, 0.10),  # item C, page 2
    _span(82, 120, 3, 0.10),  # item C continues on page 3 (second prov entry)
    _span(122, 150, 3, 0.20),  # item D, page 3
)
STARTS = [s.char_start for s in SPANS]


def test_chunk_inside_one_item() -> None:
    regions = regions_for_span(SPANS, STARTS, 5, 20)
    assert [r.page for r in regions] == [1] and regions[0].top == 0.10


def test_chunk_straddling_items_and_pages() -> None:
    chunk = _chunk(70, 100)
    stamp_provenance([chunk], extraction="docling", spans=SPANS)
    prov = chunk.provenance
    assert prov is not None
    assert prov.extraction == "docling"
    assert prov.page_start == 1 and prov.page_end == 3
    assert [r.page for r in prov.regions] == [1, 2, 3]


def test_item_with_two_prov_entries_emits_two_regions() -> None:
    regions = regions_for_span(SPANS, STARTS, 90, 100)
    assert [r.page for r in regions] == [2, 3]


def test_chunk_inside_delimiter_gap_has_no_regions() -> None:
    chunk = _chunk(30, 32)
    stamp_provenance([chunk], extraction="docling", spans=SPANS)
    assert chunk.provenance is not None
    assert chunk.provenance.regions == []
    assert chunk.provenance.page_start is None and chunk.provenance.page_end is None


def test_partial_overlap_includes_whole_item_box() -> None:
    regions = regions_for_span(SPANS, STARTS, 28, 34)  # touches end of A and start of B
    assert [r.top for r in regions] == [0.10, 0.20]


def test_direct_extraction_stamps_extraction_only() -> None:
    chunk = _chunk(0, 10)
    stamp_provenance([chunk], extraction="direct", spans=())
    assert chunk.provenance is not None
    assert chunk.provenance.extraction == "direct"
    assert chunk.provenance.regions == [] and chunk.provenance.page_start is None


def test_chunk_without_offsets_gets_extraction_only() -> None:
    chunk = Chunk(chunk_id="c", content="x", file_path="f", start_line=1, end_line=1)
    stamp_provenance([chunk], extraction="docling", spans=SPANS)
    assert chunk.provenance is not None and chunk.provenance.regions == []


def test_real_chunker_over_fixture_pdf_maps_every_chunk_to_pages() -> None:
    doc = extract_text_for_path(AURORA_REPORT_PDF)
    assert doc is not None and doc.spans
    chunker = Chunker(
        ChunkingConfig(chunking_strategy="fixed_tokens", chunk_size=200, chunk_overlap=0)
    )
    chunks = chunker.chunk_file("aurora-mission-report.pdf", doc.text)
    assert chunks
    stamp_provenance(chunks, extraction=doc.extraction, spans=doc.spans)
    for chunk in chunks:
        assert chunk.provenance is not None
        assert chunk.provenance.extraction == "docling"
        assert chunk.provenance.regions, chunk.chunk_id
        for region in chunk.provenance.regions:
            assert 0.0 <= region.left < region.right <= 1.0
    with_page_two = [c for c in chunks if PAGE_TWO_SENTENCE.split(".")[0] in c.content]
    assert with_page_two
    assert all(c.provenance is not None and c.provenance.page_end == 2 for c in with_page_two)
    assert any(c.provenance is not None and c.provenance.page_start == 1 for c in chunks)
