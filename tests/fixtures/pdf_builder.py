"""Deterministic hand-assembled PDFs for tests (no PDF-writer dependency).

Every line of text is its own content block at a distinct baseline so Docling yields separate
layout items with distinct bounding boxes. Output is byte-deterministic (no timestamps, no ids),
so fixtures built from it can be pinned by hash.
"""

from __future__ import annotations

from pathlib import Path

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
_FIRST_BASELINE = 720
_LINE_STEP = 36
_FONT_SIZE = 14
_LEFT_MARGIN = 72


def _escape(text: str) -> bytes:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1")


def build_pdf(pages: list[list[str]]) -> bytes:
    """Build a multi-page PDF; ``pages`` is a list of pages, each a list of text lines."""
    if not pages:
        raise ValueError("build_pdf needs at least one page")
    objects: list[bytes] = []
    # 1 catalog, 2 pages tree, 3 font, then (page, content) pairs
    first_page_obj = 4
    kids = " ".join(f"{first_page_obj + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        page_no = first_page_obj + 2 * i
        content_no = page_no + 1
        blocks = []
        for line_index, line in enumerate(lines):
            y = _FIRST_BASELINE - _LINE_STEP * line_index
            if y < 40:
                raise ValueError("too many lines for one fixture page")
            blocks.append(
                b"BT /F1 %d Tf %d %d Td (" % (_FONT_SIZE, _LEFT_MARGIN, y) + _escape(line) + b") Tj ET"
            )
        content = b"\n".join(blocks)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_no} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


AURORA_REPORT_PAGES: list[list[str]] = [
    [
        "Aurora Observatory Mission Report",
        "The salinity array is calibrated every 45 days.",
        "Calibration drift above 0.3 PSU triggers a maintenance ticket.",
        "Section 1 covers the shoreline sensor cluster.",
    ],
    [
        "Section 2: Thermal probes",
        "Thermal probes are recalibrated after every 120 days of deployment.",
        "Probe T-7 failed its March calibration and was replaced.",
    ],
]

PAGE_TWO_SENTENCE = "Thermal probes are recalibrated after every 120 days of deployment."


def build_aurora_report_pdf() -> bytes:
    """The two-page fixture checked in at tests/fixtures/acceptance_corpus_docs."""
    return build_pdf(AURORA_REPORT_PAGES)


ACCEPTANCE_DOCS_DIR = Path(__file__).resolve().parent / "acceptance_corpus_docs"
AURORA_REPORT_PDF = ACCEPTANCE_DOCS_DIR / "aurora-mission-report.pdf"

# Two consecutive scanned pages of the Apollo 11 Mission Report (NASA, public domain) on which
# Docling's layout model detects at least one figure. Used by the figure-chunk tests.
APOLLO_FIGURE_FIXTURE = ACCEPTANCE_DOCS_DIR / "apollo11_figure_pages.pdf"


def apollo_figure_pages() -> Path:
    if not APOLLO_FIGURE_FIXTURE.exists():
        raise FileNotFoundError(f"missing fixture {APOLLO_FIGURE_FIXTURE}")
    return APOLLO_FIGURE_FIXTURE
