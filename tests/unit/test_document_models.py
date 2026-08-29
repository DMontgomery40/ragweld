"""Boundary-model invariants for chunk provenance and the source document viewer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from server.models.index import (
    Chunk,
    ChunkProvenance,
    DocumentNotCapturedDetail,
    DocumentPdfView,
    DocumentProvenanceCaptured,
    DocumentProvenanceNotCaptured,
    DocumentRichView,
    DocumentTextView,
    DocumentTooLargeDetail,
    DocumentView,
    PageRegion,
    PageSize,
)
from server.models.tribrid_config_model import (
    ChunkMatch,
    DocumentViewerConfig,
    TriBridConfig,
    validate_corpus_id_component,
)

SHA = "a" * 64


def _region(page: int = 1) -> PageRegion:
    return PageRegion(page=page, left=0.1, top=0.2, right=0.6, bottom=0.3)


# --- PageRegion ---------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0, "left": 0, "top": 0, "right": 1, "bottom": 1},
        {"page": 1, "left": -0.1, "top": 0, "right": 1, "bottom": 1},
        {"page": 1, "left": 0, "top": 0, "right": 1.1, "bottom": 1},
        {"page": 1, "left": 0.7, "top": 0, "right": 0.5, "bottom": 1},
        {"page": 1, "left": 0, "top": 0.9, "right": 1, "bottom": 0.4},
    ],
)
def test_page_region_rejects_out_of_range_or_inverted_boxes(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        PageRegion(**kwargs)


def test_page_region_accepts_degenerate_zero_width_box() -> None:
    assert PageRegion(page=3, left=0.5, top=0.5, right=0.5, bottom=0.5).page == 3


# --- ChunkProvenance ------------------------------------------------------------


def test_direct_provenance_has_no_pages_or_regions() -> None:
    prov = ChunkProvenance(extraction="direct")
    assert prov.page_start is None and prov.page_end is None and prov.regions == []


def test_docling_provenance_round_trips_pages_and_regions() -> None:
    prov = ChunkProvenance(
        extraction="docling", page_start=1, page_end=2, regions=[_region(1), _region(2)]
    )
    again = ChunkProvenance.model_validate(prov.model_dump(mode="json"))
    assert again == prov


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extraction": "docling", "page_start": 1},  # end missing
        {"extraction": "docling", "page_end": 1},  # start missing
        {"extraction": "docling", "page_start": 3, "page_end": 2, "regions": [_region(2)]},
        {"extraction": "docling", "page_start": 1, "page_end": 1},  # regions empty
        {"extraction": "docling", "regions": [_region(1)]},  # pages missing
        {"extraction": "ocr"},
    ],
)
def test_chunk_provenance_rejects_inconsistent_states(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        ChunkProvenance(**kwargs)


def test_chunk_and_chunk_match_carry_optional_provenance() -> None:
    base = dict(chunk_id="f.md:1-2:0", content="x", file_path="f.md", start_line=1, end_line=2)
    assert Chunk(**base).provenance is None
    prov = ChunkProvenance(extraction="direct")
    assert Chunk(**base, provenance=prov).provenance == prov
    match = ChunkMatch(**base, score=0.5, source="vector", provenance=prov)
    assert ChunkMatch.model_validate(match.model_dump(mode="json")).provenance == prov
    assert ChunkMatch(**base, score=0.5, source="graph").provenance is None


# --- DocumentView ---------------------------------------------------------------


def _captured() -> DocumentProvenanceCaptured:
    return DocumentProvenanceCaptured(
        extraction="direct", sha256=SHA, byte_size=12, indexed_at=datetime.now(UTC), stale=False
    )


def _not_captured() -> DocumentProvenanceNotCaptured:
    return DocumentProvenanceNotCaptured(message="m", operator_hint="re-index")


@pytest.mark.parametrize(
    "content",
    [
        DocumentTextView(text="a\nb", line_count=2),
        DocumentPdfView(page_count=2, page_sizes=[PageSize(width=612, height=792)] * 2),
        DocumentRichView(markdown="# h\n\n| a |"),
    ],
)
@pytest.mark.parametrize("provenance", [_captured(), _not_captured()])
def test_document_view_discriminated_union_round_trips(content, provenance) -> None:
    view = DocumentView(
        corpus_id="c", file_path="doc.bin", byte_size=12, content=content, provenance=provenance
    )
    payload = view.model_dump(mode="json")
    assert payload["content"]["kind"] == content.kind
    assert payload["provenance"]["state"] == provenance.state
    assert DocumentView.model_validate(payload) == view


def test_document_view_rejects_unknown_content_kind() -> None:
    with pytest.raises(ValidationError):
        DocumentView.model_validate(
            {
                "corpus_id": "c",
                "file_path": "f",
                "byte_size": 1,
                "content": {"kind": "image", "bytes": ""},
                "provenance": _not_captured().model_dump(),
            }
        )


def test_error_details_carry_stable_codes() -> None:
    d = DocumentNotCapturedDetail(corpus_id="c", file_path="f", message="m", operator_hint="h")
    assert d.code == "document_not_captured"
    t = DocumentTooLargeDetail(
        corpus_id="c", file_path="f", byte_size=10, max_text_bytes=5, message="m", operator_hint="h"
    )
    assert t.code == "document_too_large"


def test_pdf_view_requires_at_least_one_page() -> None:
    with pytest.raises(ValidationError):
        DocumentPdfView(page_count=0, page_sizes=[])


# --- DocumentViewerConfig -------------------------------------------------------


def test_document_viewer_config_defaults_and_bounds() -> None:
    cfg = DocumentViewerConfig()
    assert cfg.page_render_scale == 2.0
    assert cfg.thumbnail_render_scale == 0.5
    assert cfg.max_text_bytes == 5_000_000
    assert TriBridConfig().document_viewer == cfg
    with pytest.raises(ValidationError):
        DocumentViewerConfig(page_render_scale=5.0)
    with pytest.raises(ValidationError):
        DocumentViewerConfig(thumbnail_render_scale=0.1)
    with pytest.raises(ValidationError):
        DocumentViewerConfig(max_text_bytes=1)


# --- corpus id component --------------------------------------------------------


@pytest.mark.parametrize("bad", [".", "..", "a/b", "a\\b", "a b", ""])
def test_validate_corpus_id_component_rejects_path_escapes(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_corpus_id_component(bad)


def test_validate_corpus_id_component_accepts_plain_ids() -> None:
    assert validate_corpus_id_component(" nasa-apollo-11 ") == "nasa-apollo-11"
