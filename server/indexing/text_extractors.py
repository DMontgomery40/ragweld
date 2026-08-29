from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.models.index import DocumentKind, ExtractionMethod, FigureAnnotation, PageRegion

# Rich-document formats are converted through Docling; code and plain-text
# formats keep the direct read path by design.
DOCLING_SUFFIXES: frozenset[str] = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"})

_DOCLING_CONVERTER: Any = None
_DOCLING_CONVERTER_LOCK = threading.Lock()


@dataclass(frozen=True)
class SourceSpan:
    """One Docling layout item located in the serialized markdown: [char_start, char_end)."""

    char_start: int
    char_end: int
    region: PageRegion
    figure: FigureAnnotation | None = None
    figure_class: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    """Extracted text plus the provenance needed to point a chunk back at its source."""

    text: str
    extraction: ExtractionMethod
    kind: DocumentKind
    spans: tuple[SourceSpan, ...] = ()
    unlocated_items: int = 0
    figures_described: int = 0
    figures_failed: int = 0
    figures_skipped: int = 0


def extraction_method_for_path(path: Path) -> ExtractionMethod:
    return "docling" if path.suffix.lower() in DOCLING_SUFFIXES else "direct"


def document_kind_for_path(path: Path) -> DocumentKind:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in DOCLING_SUFFIXES:
        return "rich"
    return "text"


def _direct(text: str | None) -> ExtractedDocument | None:
    if text is None:
        return None
    return ExtractedDocument(text=text, extraction="direct", kind="text")


def _docling_converter() -> Any:
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is not None:
        return _DOCLING_CONVERTER
    with _DOCLING_CONVERTER_LOCK:
        if _DOCLING_CONVERTER is None:
            from docling.document_converter import DocumentConverter

            _DOCLING_CONVERTER = DocumentConverter()
    return _DOCLING_CONVERTER


def extract_text_for_path(
    path: Path,
    *,
    parquet_max_rows: int = 5000,
    parquet_max_chars: int = 2_000_000,
    parquet_max_cell_chars: int = 20_000,
    parquet_text_columns_only: bool = True,
    parquet_include_column_names: bool = True,
) -> ExtractedDocument | None:
    """Return the extracted document for a file, or None if unsupported/unreadable.

    - Text/code formats are read as UTF-8 (errors ignored)
    - CSV/TSV are normalized into tab-separated rows
    - PDF, DOCX, PPTX, XLSX, and HTML are converted to markdown by Docling
    - Parquet extraction uses pyarrow, bounded by config
    """
    ext = path.suffix.lower()
    if ext in {".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".toml", ".sql", ".py", ".js", ".jsx", ".ts", ".tsx"}:
        return _direct(_read_text(path))
    if ext in {".csv", ".tsv"}:
        return _direct(_read_delimited(path, delimiter="," if ext == ".csv" else "\t"))
    if ext in DOCLING_SUFFIXES:
        return _read_with_docling(path)
    if ext == ".parquet":
        return _direct(
            _read_parquet(
                path,
                max_rows=int(parquet_max_rows),
                max_chars=int(parquet_max_chars),
                max_cell_chars=int(parquet_max_cell_chars),
                text_columns_only=bool(parquet_text_columns_only),
                include_column_names=bool(parquet_include_column_names),
            )
        )
    return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _read_delimited(path: Path, *, delimiter: str) -> str | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    # Normalize into a simple “table-ish” textual representation.
    out_lines: list[str] = []
    try:
        reader = csv.reader(raw.splitlines(), delimiter=delimiter)
        for row in reader:
            if not row:
                continue
            out_lines.append("\t".join(str(c).strip() for c in row))
    except Exception:
        return raw
    return "\n".join(out_lines)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else float(value)


def _build_source_map(doc: Any, serializer: Any, full: str) -> tuple[tuple[SourceSpan, ...], int]:
    """Locate every Docling item's markdown inside the whole-document markdown.

    The document serialization is the concatenation of the per-item serializations in
    reading order, so a monotonic ``find`` cursor maps each item to one [start, end) span. Each
    of the item's ``prov`` entries (page + bounding box, bottom-left origin in PDF points)
    becomes a normalized top-left ``PageRegion`` over that span. Items that cannot be located
    are counted, never raised: extraction must not fail because one layout item drifted.
    """
    from docling_core.types.doc import DocItem

    spans: list[SourceSpan] = []
    unlocated = 0
    cursor = 0
    for item, _level in doc.iterate_items():
        if not isinstance(item, DocItem) or not getattr(item, "prov", None):
            continue
        part = serializer.serialize(item=item).text
        if not part.strip():
            continue
        pos = full.find(part, cursor)
        if pos < 0:
            unlocated += 1
            continue
        end = pos + len(part)
        cursor = end
        figures = getattr(getattr(serializer, "picture_serializer", None), "figures_by_ref", {})
        classes = getattr(getattr(serializer, "picture_serializer", None), "classes_by_ref", {})
        figure = figures.get(getattr(item, "self_ref", ""))
        figure_class = classes.get(getattr(item, "self_ref", ""))
        for prov in item.prov:
            page = doc.pages.get(prov.page_no)
            size = getattr(page, "size", None)
            if size is None or size.width <= 0 or size.height <= 0:
                continue
            box = prov.bbox.to_top_left_origin(size.height)
            left, right = sorted((_clamp01(box.l / size.width), _clamp01(box.r / size.width)))
            top, bottom = sorted((_clamp01(box.t / size.height), _clamp01(box.b / size.height)))
            spans.append(
                SourceSpan(
                    char_start=pos,
                    char_end=end,
                    region=PageRegion(
                        page=int(prov.page_no), left=left, top=top, right=right, bottom=bottom
                    ),
                    figure=figure,
                    figure_class=figure_class,
                )
            )
    spans.sort(key=lambda span: (span.char_start, span.char_end))
    return tuple(spans), unlocated


def _read_with_docling(path: Path, *, converter: Any | None = None) -> ExtractedDocument | None:
    """Convert a rich document to markdown via Docling with a page/bbox source map.

    ``converter`` lets the indexer pass a converter configured for figure enrichment
    (Task 6); the default is the plain cached converter.

    Returns None when the document is unparseable or serializes to nothing. The returned text
    is the whole-document markdown serialization, unmodified, so chunk char offsets index it
    exactly.

    Only Docling's own conversion is guarded: a malformed/unsupported input is expected to fail
    there, and that failure degrades to ``None`` (unparseable), never raises. Everything past
    that point — building ragweld's own markdown serializer, serializing, the source map, the
    figure counts — is ragweld's own code; a bug there must raise so a regression is visible
    instead of silently degrading to "unparseable".
    """
    from docling_core.types.doc import PictureItem
    from docling_core.types.doc.document import DescriptionAnnotation, PictureMeta

    from server.indexing.figure_serializer import make_markdown_serializer

    try:
        result = (converter or _docling_converter()).convert(str(path))
        doc = result.document
    except Exception:
        return None
    serializer = make_markdown_serializer(doc)
    full = str(serializer.serialize().text or "")
    if not full.strip():
        return None
    spans, unlocated = _build_source_map(doc, serializer, full)
    pictures = [p for p, _ in doc.iterate_items() if isinstance(p, PictureItem)]
    # A description can live in the current ``item.meta`` shape (live enrichment, and any
    # fixture that sets meta directly) or the deprecated ``item.annotations`` shape (fixtures
    # built against the older API); setting meta alone does not populate annotations, so both
    # must be checked or meta-only pictures would be miscounted as skipped.
    described = sum(
        1
        for p in pictures
        if (isinstance(p.meta, PictureMeta) and p.meta.description is not None)
        or any(isinstance(a, DescriptionAnnotation) for a in p.get_annotations())
    )
    return ExtractedDocument(
        text=full,
        extraction="docling",
        kind=document_kind_for_path(path),
        spans=spans,
        unlocated_items=unlocated,
        figures_described=described,
        figures_skipped=max(0, len(pictures) - described),
    )


def _read_parquet(
    path: Path,
    *,
    max_rows: int,
    max_chars: int,
    max_cell_chars: int,
    text_columns_only: bool,
    include_column_names: bool,
) -> str | None:
    """Read a Parquet file into a bounded text representation.

    This is designed for indexing: avoid loading huge Parquet files into memory.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception:
        return None

    max_rows = max(1, int(max_rows))
    max_chars = max(1, int(max_chars))
    max_cell_chars = max(1, int(max_cell_chars))

    def _is_text_type(t: pa.DataType) -> bool:
        if pa.types.is_string(t) or pa.types.is_large_string(t):
            return True
        if pa.types.is_dictionary(t):
            try:
                return _is_text_type(t.value_type)
            except Exception:
                return False
        return False

    try:
        pf = pq.ParquetFile(str(path))
    except Exception:
        return None

    cols: list[str] | None = None
    if text_columns_only:
        try:
            schema = pf.schema_arrow
            text_cols = [f.name for f in schema if _is_text_type(f.type)]
            cols = text_cols or None
        except Exception:
            cols = None

    out_parts: list[str] = []
    total_rows = 0
    total_chars = 0

    try:
        for batch in pf.iter_batches(batch_size=1024, columns=cols):
            if total_rows >= max_rows or total_chars >= max_chars:
                break
            table = pa.Table.from_batches([batch])
            batch_rows = int(table.num_rows or 0)
            if batch_rows <= 0:
                continue

            names = list(table.column_names)
            arrays = [table.column(i).to_pylist() for i in range(table.num_columns)]
            for i in range(batch_rows):
                if total_rows >= max_rows or total_chars >= max_chars:
                    break
                row_parts: list[str] = []
                for col_name, col_vals in zip(names, arrays, strict=True):
                    try:
                        v = col_vals[i]
                    except Exception:
                        continue
                    if v is None:
                        continue
                    s = str(v).strip()
                    if not s:
                        continue
                    if len(s) > max_cell_chars:
                        s = s[:max_cell_chars] + "…"
                    row_parts.append(f"[{col_name}]\n{s}" if include_column_names else s)

                if row_parts:
                    chunk = f"\n\n--- row {total_rows} ---\n\n" + "\n\n".join(row_parts)
                    out_parts.append(chunk)
                    total_chars += len(chunk)
                total_rows += 1
    except Exception:
        return None

    joined = "\n".join(out_parts).strip()
    if total_rows >= max_rows and len(joined) < max_chars:
        joined = (joined + "\n\n… (truncated by parquet_extract_max_rows)\n").strip()
    elif total_chars >= max_chars:
        joined = (joined[:max_chars] + "\n\n… (truncated by parquet_extract_max_chars)\n").strip()
    return joined or ""
