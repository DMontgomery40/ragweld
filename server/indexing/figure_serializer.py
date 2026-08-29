"""Markdown serialization of described figures.

Docling's own picture serializer emits captions, raw annotation text and an image placeholder.
Ragweld's variant renders the vision reply as prose (``figure_block_markdown``) at the
picture's position and keeps the parsed ``FigureAnnotation`` aside, keyed by ``self_ref``, so
the extractor's source map can attach it to the chunk that lands on that text.

One serializer instance is used for both the whole-document serialization and the per-item
calls made by ``_build_source_map``; the per-item text is therefore findable verbatim in the
whole text, which is what the source map relies on.

When a picture has no ``DescriptionAnnotation``, this serializer defers to Docling's own
``MarkdownPictureSerializer.serialize`` so the output is byte-identical to stock Docling.
"""

from __future__ import annotations

from typing import Any

from docling_core.transforms.serializer.common import create_ser_result
from docling_core.transforms.serializer.markdown import (
    MarkdownDocSerializer,
    MarkdownParams,
    MarkdownPictureSerializer,
)
from docling_core.types.doc.document import (
    DescriptionAnnotation,
    DoclingDocument,
    PictureClassificationData,
    PictureItem,
)

from server.indexing.figure_prompts import figure_block_markdown, parse_figure_reply
from server.models.index import FigureAnnotation


class RagweldPictureSerializer(MarkdownPictureSerializer):
    """Prose for described pictures; Docling's default output for everything else."""

    def __init__(self) -> None:
        super().__init__()
        self.figures_by_ref: dict[str, FigureAnnotation] = {}
        self.classes_by_ref: dict[str, str] = {}

    def serialize(self, *, item: PictureItem, doc_serializer: Any, doc: DoclingDocument, **kwargs: Any):  # type: ignore[override]
        description: DescriptionAnnotation | None = None
        cls: str | None = None
        for ann in item.annotations:
            if isinstance(ann, DescriptionAnnotation) and description is None:
                description = ann
            elif isinstance(ann, PictureClassificationData) and ann.predicted_classes and cls is None:
                cls = ann.predicted_classes[0].class_name.replace("_", " ")
        if cls is not None:
            self.classes_by_ref[item.self_ref] = cls
        if description is None:
            return super().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)

        fig = parse_figure_reply(description.text)
        self.figures_by_ref[item.self_ref] = fig
        caption = doc_serializer.serialize_captions(item=item, **kwargs).text
        params = MarkdownParams(**kwargs)
        block = figure_block_markdown(caption, cls, fig)
        placeholder = ""
        if item.self_ref not in doc_serializer.get_excluded_refs(**kwargs):
            placeholder = self._serialize_image_part(
                item=item,
                doc=doc,
                image_mode=params.image_mode,
                image_placeholder=params.image_placeholder,
            ).text
        text = "\n\n".join(p for p in (block, placeholder) if p)
        return create_ser_result(text=text, span_source=item)


def make_markdown_serializer(doc: DoclingDocument) -> MarkdownDocSerializer:
    """A Docling markdown serializer whose picture serializer records figure annotations."""
    return MarkdownDocSerializer(doc=doc, picture_serializer=RagweldPictureSerializer())
