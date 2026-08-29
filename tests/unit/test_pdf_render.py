"""pypdfium2-backed page sizing and rasterization."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from server.models.index import PageSize
from server.services.pdf_render import (
    NotRenderableError,
    PageOutOfRangeError,
    pdf_page_sizes,
    render_page_png,
)
from tests.fixtures.pdf_builder import AURORA_REPORT_PDF


def test_page_sizes_of_fixture() -> None:
    assert pdf_page_sizes(AURORA_REPORT_PDF) == [PageSize(width=612.0, height=792.0)] * 2


def test_render_page_at_scale_two_is_letter_at_144_dpi() -> None:
    png = render_page_png(AURORA_REPORT_PDF, 1, 2.0)
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG"
    assert image.size == (1224, 1584)
    thumb = Image.open(io.BytesIO(render_page_png(AURORA_REPORT_PDF, 2, 0.5)))
    assert thumb.size == (306, 396)


def test_out_of_range_pages_raise() -> None:
    with pytest.raises(PageOutOfRangeError):
        render_page_png(AURORA_REPORT_PDF, 3, 1.0)
    with pytest.raises(PageOutOfRangeError):
        render_page_png(AURORA_REPORT_PDF, 0, 1.0)


def test_non_pdf_is_not_renderable(tmp_path: Path) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("not a pdf")
    with pytest.raises(NotRenderableError):
        pdf_page_sizes(text)
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"not a pdf either")
    with pytest.raises(NotRenderableError):
        render_page_png(fake, 1, 1.0)
