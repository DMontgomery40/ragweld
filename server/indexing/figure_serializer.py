"""Markdown serialization of described figures.

Docling's own picture serializer emits captions, raw annotation text and an image placeholder.
Ragweld's variant renders the vision reply as prose (``figure_block_markdown``) at the
picture's position and keeps the parsed ``FigureAnnotation`` aside, keyed by ``self_ref``, so
the extractor's source map can attach it to the chunk that lands on that text.

One serializer instance is used for both the whole-document serialization and the per-item
calls made by ``_build_source_map``; the per-item text is therefore findable verbatim in the
whole text, which is what the source map relies on.

Docling's live enrichment pipeline attaches the description and classification to
``item.meta`` (``PictureMeta.description`` / ``.classification``), and only additionally
appends the deprecated ``DescriptionAnnotation`` / ``PictureClassificationData`` to
``item.annotations`` because ``_keep_deprecated_annotations`` defaults to True. This
serializer reads ``item.meta`` first and falls back to ``item.annotations`` so it works
against both the live enrichment shape and hand-built test fixtures that only set
annotations. Whenever ``item.meta`` is set at all, ``DocSerializer.serialize`` prepends a
``serialize_meta`` block ahead of the picture serializer's own output; left unconfigured that
block renders ``meta.description.text`` verbatim (the raw JSON reply) via
``MarkdownMetaSerializer``. ``make_markdown_serializer`` blocks the ``description`` and
``classification`` meta names so that leak cannot happen no matter which item is being
serialized, and this serializer is the sole place that turns the parsed reply into prose.

A picture can be classified without being described — the vision alias is skipped by an area
threshold, a class deny-list, or a timeout, while the (cheaper, local) classifier still ran.
The class name is searchable text and must not silently vanish, so a classified-but-undescribed
picture still gets a header-only block (``figure_block_markdown(caption, cls, None)``) plus the
image part. Byte-identity with stock Docling's ``MarkdownPictureSerializer.serialize`` holds
only for a picture with neither a description nor a classification; that is the only case this
serializer defers to ``super().serialize(...)``.
"""

from __future__ import annotations

from typing import Any

from docling_core.transforms.serializer.base import SerializationResult
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
    PictureMeta,
)

from server.indexing.figure_prompts import figure_block_markdown, parse_figure_reply
from server.models.index import FigureAnnotation


def non_blank(text: str | None) -> str | None:
    """``text`` if it has non-whitespace content, else ``None``.

    Public because ``text_extractors._read_with_docling``'s picture triage imports it: the
    counts and the spans must agree on what "described" means, so both call this one helper.

    A vision reply of ``""`` (the gateway returned nothing, or Docling's own API client
    swallowed a failed request) is not a description: it must be treated exactly like no
    description was ever attached, not parsed into a ``FigureAnnotation`` and not counted as
    described anywhere downstream.
    """
    return text if text and text.strip() else None


class RagweldPictureSerializer(MarkdownPictureSerializer):
    """Prose for described and/or classified pictures; Docling's default output only when
    neither a description nor a classification is present.
    """

    def __init__(self) -> None:
        super().__init__()
        self.figures_by_ref: dict[str, FigureAnnotation] = {}
        self.classes_by_ref: dict[str, str] = {}

    def serialize(self, *, item: PictureItem, doc_serializer: Any, doc: DoclingDocument, **kwargs: Any) -> SerializationResult:
        meta = item.meta if isinstance(item.meta, PictureMeta) else None
        description_text: str | None = (
            non_blank(meta.description.text) if meta and meta.description else None
        )
        cls: str | None = (
            meta.classification.get_main_prediction().class_name.replace("_", " ")
            if meta and meta.classification
            else None
        )
        if description_text is None or cls is None:
            for ann in item.annotations:
                if description_text is None and isinstance(ann, DescriptionAnnotation):
                    description_text = non_blank(ann.text)
                elif cls is None and isinstance(ann, PictureClassificationData) and ann.predicted_classes:
                    cls = ann.predicted_classes[0].class_name.replace("_", " ")

        if cls is not None:
            self.classes_by_ref[item.self_ref] = cls
        if description_text is None and cls is None:
            return super().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)

        fig: FigureAnnotation | None = None
        if description_text is not None:
            fig = parse_figure_reply(description_text)
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
    """A Docling markdown serializer whose picture serializer records figure annotations.

    ``blocked_meta_names`` stops ``DocSerializer.serialize`` from prepending Docling's own
    ``serialize_meta`` block (raw description JSON, humanized class name) ahead of every item
    that carries ``item.meta`` — including pictures, which is where the JSON would otherwise
    leak regardless of what ``RagweldPictureSerializer`` itself renders.
    """
    return MarkdownDocSerializer(
        doc=doc,
        picture_serializer=RagweldPictureSerializer(),
        params=MarkdownParams(blocked_meta_names={"description", "classification"}),
    )
