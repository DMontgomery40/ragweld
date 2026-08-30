"""Config becomes Docling pipeline options exactly; disabled config keeps the plain converter."""

from __future__ import annotations

import pytest
from docling.datamodel.pipeline_options import PdfPipelineOptions, PictureDescriptionApiOptions

from server.indexing.text_extractors import (
    FigureGateway,
    _docling_converter,
    build_figure_pipeline_options,
    docling_converter_for,
    extract_text_for_path,
)
from server.models.tribrid_config_model import IndexingFiguresConfig
from tests.fixtures.pdf_builder import apollo_figure_pages


def test_disabled_config_uses_the_plain_cached_converter() -> None:
    figures = IndexingFiguresConfig(enabled=False)
    assert docling_converter_for(figures, None) is _docling_converter()


def test_enabled_config_maps_every_field_onto_pipeline_options() -> None:
    figures = IndexingFiguresConfig(
        enabled=True,
        describe=True,
        classify=True,
        vision_model="z-ai.glm-5.3-flash",
        prompt_profile="schematic",
        images_scale=3.0,
        min_area_fraction=0.05,
        skip_classes=["logo"],
        max_completion_tokens=800,
        concurrency=2,
        timeout_s=45,
    )
    gateway = FigureGateway(
        base_url="http://127.0.0.1:54000/v1", api_key="sk-test", model="z-ai.glm-5.3-flash"
    )
    opts = build_figure_pipeline_options(figures, gateway)
    assert isinstance(opts, PdfPipelineOptions)
    assert opts.generate_picture_images is True and opts.images_scale == 3.0
    assert opts.do_picture_classification is True and opts.do_picture_description is True
    assert opts.enable_remote_services is True
    api = opts.picture_description_options
    assert isinstance(api, PictureDescriptionApiOptions)
    # ``url`` is a pydantic ``AnyUrl``, which never compares equal to a plain string.
    assert str(api.url) == "http://127.0.0.1:54000/v1/chat/completions"
    assert api.headers["Authorization"] == "Bearer sk-test"
    assert api.params["model"] == "z-ai.glm-5.3-flash"
    assert api.params["max_completion_tokens"] == 800
    assert api.params["response_format"] == {"type": "json_object"}
    assert api.timeout == 45 and api.concurrency == 2
    assert api.picture_area_threshold == 0.05
    assert api.classification_deny == ["logo"]
    assert api.classification_min_confidence == 0.5
    # The crop actually sent to the vision alias is governed by the API options' own
    # scale, not only by the pipeline raster scale; both must follow images_scale.
    assert api.scale == 3.0
    assert api.provenance == "ragweld:z-ai.glm-5.3-flash"
    assert "drawing number" in api.prompt.lower()


def test_describe_off_still_classifies_without_remote_services() -> None:
    figures = IndexingFiguresConfig(enabled=True, describe=False, classify=True)
    opts = build_figure_pipeline_options(figures, None)
    assert opts.do_picture_classification is True and opts.do_picture_description is False
    assert opts.enable_remote_services is False


def test_describe_without_a_gateway_fails_closed() -> None:
    """An operator who asked for descriptions never silently gets none."""
    figures = IndexingFiguresConfig(enabled=True, describe=True)
    with pytest.raises(ValueError, match="vision gateway"):
        build_figure_pipeline_options(figures, None)


def test_converters_are_cached_per_options_signature() -> None:
    a = IndexingFiguresConfig(enabled=True, describe=False)
    b = IndexingFiguresConfig(enabled=True, describe=False)
    c = IndexingFiguresConfig(enabled=True, describe=False, images_scale=1.5)
    assert docling_converter_for(a, None) is docling_converter_for(b, None)
    assert docling_converter_for(a, None) is not docling_converter_for(c, None)


def test_enrichment_converter_still_accepts_every_format_the_plain_one_does() -> None:
    """Registering PDF/IMAGE options must not narrow the converter's accepted formats.

    ``extract_text_for_path`` sends every ``DOCLING_SUFFIXES`` document (DOCX, PPTX, XLSX,
    HTML) through whichever converter it is handed, so a converter that only accepted PDF
    would stop extracting every non-PDF rich document the moment figures were enabled.
    """
    figures = IndexingFiguresConfig(enabled=True, describe=False)
    enriched = set(docling_converter_for(figures, None).allowed_formats)
    assert enriched >= set(_docling_converter().allowed_formats)


def test_extract_text_for_path_runs_the_classifier_over_a_real_pdf() -> None:
    """The integration point: config in, a classified Docling document out.

    Classification is local (no gateway), so this pins the whole
    ``extract_text_for_path -> docling_converter_for -> _read_with_docling`` path against a
    real PDF, including that the enrichment converter still produces a usable source map.
    """
    pdf = apollo_figure_pages()
    figures = IndexingFiguresConfig(enabled=True, classify=True, describe=False)

    plain = extract_text_for_path(pdf)
    assert plain is not None

    doc = extract_text_for_path(pdf, figures=figures, gateway=None)
    assert doc is not None
    assert doc.extraction == "docling"
    assert doc.text.strip()
    assert doc.spans
    for span in doc.spans:
        assert 0 <= span.char_start < span.char_end <= len(doc.text)
    # Enrichment must not cost us provenance: the same file locates the same way.
    assert doc.unlocated_items == plain.unlocated_items
    assert any(span.figure_class for span in doc.spans), "the figure classifier did not run"

    # Pin the classification_min_confidence=0.5 protocol invariant (set in
    # build_figure_pipeline_options) against Docling's own gate. ``extract_text_for_path``
    # does not expose the raw Docling document/PictureMeta, so convert directly.
    from docling.models.picture_description_base_model import _passes_classification
    from docling_core.types.doc import PictureItem

    docling_doc = docling_converter_for(figures, None).convert(str(pdf)).document
    classified_pics = [
        p
        for p, _ in docling_doc.iterate_items()
        if isinstance(p, PictureItem) and p.meta and p.meta.classification
    ]
    assert classified_pics, "fixture must have at least one classified picture to pin the gate"
    skip_classes = list(IndexingFiguresConfig().skip_classes)
    for pic in classified_pics:
        # At the protocol's floor, a picture whose majority prediction is not in skip_classes
        # must pass: skip_classes means "never sent for description" for the figure's own
        # (majority) class, not for anything appearing anywhere in the classifier's long tail.
        assert _passes_classification(pic.meta, None, skip_classes, 0.5) is True
    # At Docling's library default (0.0), the classifier's full softmax always assigns some
    # nonzero long-tail probability to every denied class, so the deny check matches on every
    # real picture and denies it -- this is the exact bug classification_min_confidence=0.5
    # fixes. Pinning it here means the bug cannot silently come back if the floor is ever
    # dropped or removed.
    assert any(
        _passes_classification(pic.meta, None, skip_classes, 0.0) is False for pic in classified_pics
    ), "min_confidence=0.0 must still deny at least one real picture -- pins the bug this floor fixes"


def test_unreachable_vision_gateway_yields_undescribed_pictures_not_an_exception() -> None:
    """Pinned Docling behaviour: a dead vision endpoint does NOT fail the conversion.

    Docling absorbs the per-picture API failure and returns the document with its pictures
    undescribed. That is why the run log reports ``figures_undescribed`` and why the
    described/undescribed split is the only signal an operator gets that the vision alias
    was unreachable -- the conversion itself still succeeds.
    """
    figures = IndexingFiguresConfig(
        enabled=True, describe=True, classify=True, timeout_s=5, concurrency=1
    )
    gateway = FigureGateway(
        base_url="http://127.0.0.1:9/v1", api_key="x", model="z-ai.glm-5.3-flash"
    )
    doc = extract_text_for_path(apollo_figure_pages(), figures=figures, gateway=gateway)
    assert doc is not None
    assert doc.extraction == "docling"
    assert doc.figures_described == 0
    assert doc.figures_skipped > 0
