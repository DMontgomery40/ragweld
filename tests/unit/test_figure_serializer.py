"""Described figures serialize as prose at the picture's position; JSON stays out of the text."""

from __future__ import annotations

import json

import pytest
from docling.document_converter import DocumentConverter
from docling_core.types.doc import PictureItem
from docling_core.types.doc.document import (
    DescriptionAnnotation,
    PictureClassificationClass,
    PictureClassificationData,
)

from server.indexing.figure_serializer import RagweldPictureSerializer, make_markdown_serializer
from tests.fixtures.pdf_builder import apollo_figure_pages

REPLY = json.dumps({
    "kind": "chart",
    "summary": "Spacecraft altitude versus time during the descent orbit insertion burn.",
    "labels": ["ALTITUDE, FEET", "TIME, MIN"],
    "components": ["descent engine"],
    "connections": [],
    "values": ["50 000 ft"],
    "references": ["Figure 6-3"],
})


@pytest.fixture(scope="module")
def converted():
    doc = DocumentConverter().convert(str(apollo_figure_pages())).document
    pictures = [p for p, _ in doc.iterate_items() if isinstance(p, PictureItem) and p.prov]
    assert pictures, "fixture must contain at least one detected picture"
    return doc, pictures


def test_described_picture_serializes_as_prose_block(converted) -> None:
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations.append(PictureClassificationData(provenance="test", predicted_classes=[PictureClassificationClass(class_name="chart", confidence=0.9)]))
    pic.annotations.append(DescriptionAnnotation(text=REPLY, provenance="test"))

    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    part = serializer.serialize(item=pic).text

    assert part.startswith("Figure (chart):")
    assert "Spacecraft altitude versus time" in part
    assert "Labels: ALTITUDE, FEET, TIME, MIN" in part
    assert "References: Figure 6-3" in part
    assert "{" not in part and '"summary"' not in part
    assert part in full, "the per-item serialization must be findable verbatim in the whole document"
    picture_serializer = serializer.picture_serializer
    assert isinstance(picture_serializer, RagweldPictureSerializer)
    assert picture_serializer.figures_by_ref[pic.self_ref].values == ["50 000 ft"]
    assert picture_serializer.classes_by_ref[pic.self_ref] == "chart"


def test_undescribed_picture_serializes_exactly_as_docling_would(converted) -> None:
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer

    doc, pictures = converted
    pic = pictures[-1]
    pic.annotations = [a for a in pic.annotations if not isinstance(a, DescriptionAnnotation)]
    ours = make_markdown_serializer(doc).serialize(item=pic).text
    theirs = MarkdownDocSerializer(doc=doc).serialize(item=pic).text
    assert ours == theirs


def test_non_json_description_becomes_summary(converted) -> None:
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations = [a for a in pic.annotations if not isinstance(a, DescriptionAnnotation)]
    pic.annotations.append(DescriptionAnnotation(text="A scanned line drawing of the lunar module landing gear.", provenance="test"))
    serializer = make_markdown_serializer(doc)
    part = serializer.serialize(item=pic).text
    assert "A scanned line drawing of the lunar module landing gear." in part
    assert serializer.picture_serializer.figures_by_ref[pic.self_ref].labels == []
