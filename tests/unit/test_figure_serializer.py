"""Described figures serialize as prose at the picture's position; JSON stays out of the text."""

from __future__ import annotations

import json

import pytest
from docling.document_converter import DocumentConverter
from docling_core.transforms.serializer.markdown import MarkdownParams
from docling_core.types.doc import PictureItem
from docling_core.types.doc.document import (
    DescriptionAnnotation,
    DescriptionMetaField,
    PictureClassificationClass,
    PictureClassificationData,
    PictureClassificationMetaField,
    PictureClassificationPrediction,
    PictureMeta,
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


@pytest.fixture(autouse=True)
def _restore_picture_state(converted):
    """Tests mutate ``annotations``/``meta``/``captions`` on pictures from the module-scoped
    ``converted`` fixture; restore each picture to its pre-test state so tests don't leak state
    into each other regardless of execution order.
    """
    _, pictures = converted
    snapshot = [(pic, list(pic.annotations), pic.meta, list(pic.captions)) for pic in pictures]
    yield
    for pic, saved_annotations, saved_meta, saved_captions in snapshot:
        pic.annotations = saved_annotations
        pic.meta = saved_meta
        pic.captions = saved_captions


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
    placeholder = MarkdownParams().image_placeholder
    assert placeholder in part, "the image part must still be present after the prose block"
    assert part.index(placeholder) > part.index("References: Figure 6-3"), "placeholder must come after the prose block"
    picture_serializer = serializer.picture_serializer
    assert isinstance(picture_serializer, RagweldPictureSerializer)
    assert picture_serializer.figures_by_ref[pic.self_ref].values == ["50 000 ft"]
    assert picture_serializer.classes_by_ref[pic.self_ref] == "chart"


def test_undescribed_picture_serializes_exactly_as_docling_would(converted) -> None:
    """Byte-identity with stock Docling holds only when there is neither a description nor a
    classification anywhere on the item; make that premise explicit rather than assuming it.
    """
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer

    doc, pictures = converted
    pic = pictures[-1]
    pic.meta = None
    pic.annotations = [a for a in pic.annotations if not isinstance(a, (DescriptionAnnotation, PictureClassificationData))]
    assert pic.meta is None
    assert not any(isinstance(a, PictureClassificationData) for a in pic.annotations)

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


def test_meta_only_picture_serializes_as_prose_block(converted) -> None:
    """Docling's live enrichment writes ``item.meta``, not just the deprecated annotations."""
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations = []
    pic.meta = PictureMeta(
        description=DescriptionMetaField(text=REPLY, created_by="test"),
        classification=PictureClassificationMetaField(
            predictions=[PictureClassificationPrediction(class_name="chart", confidence=0.9)]
        ),
    )

    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    part = serializer.serialize(item=pic).text

    assert part.startswith("Figure (chart):")
    assert "Spacecraft altitude versus time" in part
    assert full.count(part) == 1, "the prose block must appear exactly once in the full document"
    assert '"summary"' not in full and REPLY not in full, "the raw JSON reply must never reach the markdown"
    picture_serializer = serializer.picture_serializer
    assert picture_serializer.figures_by_ref[pic.self_ref].values == ["50 000 ft"]
    assert picture_serializer.classes_by_ref[pic.self_ref] == "chart"


def test_meta_and_annotations_both_set_render_prose_once(converted) -> None:
    """Docling keeps the deprecated annotations alongside meta by default
    (``_keep_deprecated_annotations=True``); the prose block must not duplicate.
    """
    doc, pictures = converted
    pic = pictures[0]
    pic.meta = PictureMeta(
        description=DescriptionMetaField(text=REPLY, created_by="test"),
        classification=PictureClassificationMetaField(
            predictions=[PictureClassificationPrediction(class_name="chart", confidence=0.9)]
        ),
    )
    pic.annotations = [
        PictureClassificationData(provenance="test", predicted_classes=[PictureClassificationClass(class_name="chart", confidence=0.9)]),
        DescriptionAnnotation(text=REPLY, provenance="test"),
    ]

    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    part = serializer.serialize(item=pic).text

    assert part.startswith("Figure (chart):")
    assert full.count(part) == 1, "the prose block must appear exactly once even with both shapes set"
    assert '"summary"' not in full and REPLY not in full


def test_classified_but_undescribed_picture_shows_class_header(converted) -> None:
    """A classifier can run without a description (area threshold, class deny-list, or a
    vision-alias timeout); the class name is searchable text and must not silently disappear
    into the undescribed (byte-identical-to-Docling) branch.
    """
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations = []
    pic.meta = PictureMeta(
        classification=PictureClassificationMetaField(
            predictions=[PictureClassificationPrediction(class_name="chart", confidence=0.9)]
        )
    )

    serializer = make_markdown_serializer(doc)
    caption = serializer.serialize_captions(item=pic).text
    full = serializer.serialize().text
    part = serializer.serialize(item=pic).text

    assert part.startswith("Figure (chart):")
    assert caption in part
    placeholder = MarkdownParams().image_placeholder
    assert part.endswith(placeholder), "the image part must still follow the class header"
    assert "{" not in part
    assert full.count(part) == 1
    picture_serializer = serializer.picture_serializer
    assert picture_serializer.classes_by_ref[pic.self_ref] == "chart"
    assert pic.self_ref not in picture_serializer.figures_by_ref, "no description was parsed, so no FigureAnnotation"


def test_blank_description_text_is_treated_as_no_description(converted) -> None:
    """A vision reply of ``""`` (empty gateway response) is not a description: it must fall
    back to the classified-but-undescribed header-only block, exactly like no description was
    ever attached, and must never be parsed into a ``FigureAnnotation``.
    """
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations = []
    pic.meta = PictureMeta(
        description=DescriptionMetaField(text="", created_by="test"),
        classification=PictureClassificationMetaField(
            predictions=[PictureClassificationPrediction(class_name="chart", confidence=0.9)]
        ),
    )

    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    part = serializer.serialize(item=pic).text

    assert part.startswith("Figure (chart)")
    assert full.count(part) == 1
    picture_serializer = serializer.picture_serializer
    assert pic.self_ref not in picture_serializer.figures_by_ref, "a blank reply must not become a FigureAnnotation"
    assert picture_serializer.classes_by_ref[pic.self_ref] == "chart"


def test_classified_but_undescribed_and_uncaptioned_picture_shows_class_header(converted) -> None:
    """Docling only attaches a caption when adjacent text is recognised as one — a common shape
    where a classified-but-undescribed picture has neither a description nor a caption. Without
    ``cls`` alone keeping ``figure_block_markdown`` alive, this collapses to just the image
    placeholder and the classification vanishes again.
    """
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations = []
    pic.captions = []
    pic.meta = PictureMeta(
        classification=PictureClassificationMetaField(
            predictions=[PictureClassificationPrediction(class_name="chart", confidence=0.9)]
        )
    )

    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    part = serializer.serialize(item=pic).text

    assert part.startswith("Figure (chart)")
    placeholder = MarkdownParams().image_placeholder
    assert part.endswith(placeholder), "the image part must still follow the class header"
    assert full.count(part) == 1
    picture_serializer = serializer.picture_serializer
    assert picture_serializer.classes_by_ref[pic.self_ref] == "chart"
