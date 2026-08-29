"""PDF page sizes and page rasters for the source document viewer (pypdfium2)."""

from __future__ import annotations

import io
from pathlib import Path

from server.models.index import PageSize


class PageOutOfRangeError(ValueError):
    """Requested page is outside the document."""


class NotRenderableError(ValueError):
    """The file is not a PDF pdfium can open."""


def _open(path: Path):  # type: ignore[no-untyped-def]
    import pypdfium2 as pdfium

    if path.suffix.lower() != ".pdf":
        raise NotRenderableError(f"not a PDF: {path.name}")
    try:
        return pdfium.PdfDocument(str(path))
    except Exception as exc:  # pdfium raises its own error types
        raise NotRenderableError(f"pdfium could not open {path.name}: {exc}") from exc


def pdf_page_sizes(path: Path) -> list[PageSize]:
    """Page sizes in points without rasterizing anything."""
    from docling.utils.locks import pypdfium2_lock

    with pypdfium2_lock:
        pdf = _open(path)
        try:
            sizes: list[PageSize] = []
            for index in range(len(pdf)):
                width, height = pdf.get_page_size(index)
                sizes.append(PageSize(width=float(width), height=float(height)))
            return sizes
        finally:
            pdf.close()


def render_page_png(path: Path, page: int, scale: float) -> bytes:
    """Rasterize one 1-based page at ``scale`` (1.0 = 72 dpi) to PNG bytes."""
    from docling.utils.locks import pypdfium2_lock

    if page < 1:
        raise PageOutOfRangeError(f"page must be >= 1, got {page}")
    with pypdfium2_lock:
        pdf = _open(path)
        try:
            if page > len(pdf):
                raise PageOutOfRangeError(f"page {page} of {len(pdf)}")
            pdf_page = pdf[page - 1]
            try:
                bitmap = pdf_page.render(scale=float(scale))
                image = bitmap.to_pil()
            finally:
                pdf_page.close()
        finally:
            pdf.close()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
