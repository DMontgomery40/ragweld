from __future__ import annotations

from pathlib import Path

from server.indexing.text_extractors import extract_text_for_path


def test_extract_text_for_csv(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    out = extract_text_for_path(p)
    assert out is not None
    assert "a\tb\tc" in out
    assert "1\t2\t3" in out


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

    out = extract_text_for_path(p)
    assert out is not None
    assert "sheet Sheet1" in out
    assert "name\tvalue" in out
    assert "alpha\t1" in out


def test_extract_text_for_pdf(tmp_path: Path) -> None:
    # Create a tiny 1-page PDF with text using pypdf primitives.
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)

    # Minimal font resource so the text operator can reference /F1.
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )

    stream = StreamObject()
    stream._data = b"BT /F1 12 Tf 10 280 Td (Hello PDF) Tj ET"
    stream[NameObject("/Length")] = NumberObject(len(stream._data))
    page[NameObject("/Contents")] = stream

    p = tmp_path / "doc.pdf"
    with p.open("wb") as f:
        writer.write(f)

    out = extract_text_for_path(p)
    assert out is not None
    assert "hello" in out.lower()


def test_extract_text_for_unknown_binary_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    assert extract_text_for_path(p) is None

