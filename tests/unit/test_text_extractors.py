from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from server.indexing.text_extractors import (
    document_kind_for_path,
    extract_text_for_path,
    extraction_method_for_path,
)
from tests.fixtures.pdf_builder import (
    AURORA_REPORT_PDF,
    PAGE_TWO_SENTENCE,
    build_aurora_report_pdf,
)


def test_extract_text_for_csv(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    doc = extract_text_for_path(p)
    assert doc is not None
    assert doc.extraction == "direct" and doc.kind == "text" and doc.spans == ()
    assert "a\tb\tc" in doc.text
    assert "1\t2\t3" in doc.text


def test_extract_text_for_xlsx(tmp_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["name", "value"])
    ws.append(["alpha", 1])
    ws.append(["beta", 2])

    p = tmp_path / "data.xlsx"
    wb.save(p)
    wb.close()

    assert extraction_method_for_path(p) == "docling"
    doc = extract_text_for_path(p)
    assert doc is not None
    out = doc.text
    assert doc.extraction == "docling" and doc.kind == "rich"
    # Docling renders worksheets as markdown tables.
    assert "|" in out
    assert "name" in out and "value" in out
    assert "alpha" in out and "beta" in out


def _build_minimal_pdf(text: str) -> bytes:
    """Hand-assemble a valid single-page PDF with a real text layer (no PDF writer dependency)."""
    content = f"BT /F1 18 Tf 40 740 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_extract_text_for_pdf(tmp_path: Path) -> None:
    p = tmp_path / "doc.pdf"
    p.write_bytes(_build_minimal_pdf("Hello PDF from ragweld"))

    assert extraction_method_for_path(p) == "docling"
    doc = extract_text_for_path(p)
    assert doc is not None
    assert doc.kind == "pdf"
    assert "hello pdf from ragweld" in doc.text.lower()


def test_checked_in_aurora_pdf_matches_its_builder() -> None:
    assert AURORA_REPORT_PDF.read_bytes() == build_aurora_report_pdf()


def test_pdf_extraction_yields_page_spans_with_normalized_boxes() -> None:
    doc = extract_text_for_path(AURORA_REPORT_PDF)
    assert doc is not None
    assert doc.extraction == "docling" and doc.kind == "pdf"
    assert doc.unlocated_items == 0
    assert doc.spans, "PDF extraction must carry a source map"
    assert {span.region.page for span in doc.spans} == {1, 2}
    previous_end = 0
    for span in doc.spans:
        region = span.region
        assert 0.0 <= region.left < region.right <= 1.0
        assert 0.0 <= region.top < region.bottom <= 1.0
        assert span.char_start >= previous_end  # monotonic, non-overlapping
        assert span.char_end > span.char_start
        assert doc.text[span.char_start : span.char_end].strip()
        previous_end = span.char_end
    hit = doc.text.find(PAGE_TWO_SENTENCE)
    assert hit >= 0
    covering = [s for s in doc.spans if s.char_start <= hit < s.char_end]
    assert covering and all(s.region.page == 2 for s in covering)
    # page-1 text sits above page-2 text in the markdown, never the reverse
    assert max(s.char_end for s in doc.spans if s.region.page == 1) <= min(
        s.char_start for s in doc.spans if s.region.page == 2
    )


def test_document_kind_for_path() -> None:
    assert document_kind_for_path(Path("a.pdf")) == "pdf"
    assert document_kind_for_path(Path("a.PDF")) == "pdf"
    assert document_kind_for_path(Path("a.docx")) == "rich"
    assert document_kind_for_path(Path("a.html")) == "rich"
    assert document_kind_for_path(Path("a.py")) == "text"
    assert document_kind_for_path(Path("a.txt")) == "text"


def test_extract_text_for_html_uses_docling_and_keeps_tables(tmp_path: Path) -> None:
    p = tmp_path / "handbook.html"
    p.write_text(
        "<html><body><h1>Calibration Handbook</h1>"
        "<p>The salinity array is calibrated every 45 days.</p>"
        "<table><tr><th>Sensor</th><th>Cycle</th></tr>"
        "<tr><td>Salinity</td><td>45 days</td></tr></table></body></html>",
        encoding="utf-8",
    )
    assert extraction_method_for_path(p) == "docling"
    doc = extract_text_for_path(p)
    assert doc is not None
    assert doc.kind == "rich" and doc.extraction == "docling"
    assert doc.spans == ()  # HTML items carry no page provenance
    out = doc.text
    assert "calibrated every 45 days" in out
    assert "|" in out  # table survived conversion to markdown


def test_docling_converter_singleton_is_thread_safe_under_real_concurrent_threads() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from server.indexing import text_extractors as text_extractors


        def race_once() -> None:
            text_extractors._DOCLING_CONVERTER = None
            barrier = threading.Barrier(8)

            def build(_index: int) -> int:
                barrier.wait()
                return id(text_extractors._docling_converter())

            with ThreadPoolExecutor(max_workers=8) as executor:
                ids = list(executor.map(build, range(8)))
            if len(set(ids)) != 1:
                print(ids)
                raise SystemExit(1)


        for _ in range(5):
            race_once()
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_extraction_method_is_direct_for_code_and_text(tmp_path: Path) -> None:
    assert extraction_method_for_path(tmp_path / "module.py") == "direct"
    assert extraction_method_for_path(tmp_path / "notes.md") == "direct"


def test_extract_text_for_unknown_binary_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    assert extract_text_for_path(p) is None


def test_extract_text_for_parquet_is_bounded(tmp_path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception:
        # Optional dependency: if pyarrow isn't installed, parquet extraction is unsupported.
        return

    p = tmp_path / "data.parquet"
    table = pa.table({"text": ["hello", "world"], "n": [1, 2]})
    pq.write_table(table, str(p))

    out = extract_text_for_path(
        p,
        parquet_max_rows=1,
        parquet_max_chars=10_000,
        parquet_max_cell_chars=1000,
        parquet_text_columns_only=True,
        parquet_include_column_names=True,
    )
    assert out is not None
    text = out.text
    assert out.extraction == "direct" and out.kind == "text"
    assert "row 0" in text
    assert "[text]" in text
    assert "hello" in text
    assert "world" not in text
