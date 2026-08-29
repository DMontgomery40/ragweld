"""Config becomes Docling pipeline options exactly; disabled config keeps the plain converter."""

from __future__ import annotations

import pytest
from docling.datamodel.pipeline_options import PdfPipelineOptions, PictureDescriptionApiOptions

from server.indexing.text_extractors import (
    FigureGateway,
    _docling_converter,
    build_figure_pipeline_options,
    docling_converter_for,
)
from server.models.tribrid_config_model import IndexingFiguresConfig


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
