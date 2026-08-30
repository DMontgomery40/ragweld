"""Sampled corpus size estimate: what the indexer will really chunk, measured on real files.

The pre-run estimate used to be ``tokens = total_size_bytes / 4`` and
``chunks = tokens / 448``. Both constants were applied to raw container bytes, so a 15 MiB
figure-heavy PDF was sized from its embedded fonts and images: the dialog quoted 3,993,486
tokens / 8,915 chunks for the Apollo 11 mission report against a completed run of 244,789
tokens / 1,315 chunks (16x and 6.8x over). The 448 divisor also ignored the chunking strategy
the operator had just chosen, and a corpus of 2,000 small files came out 4.5x low because
chunking is per file with a one-chunk minimum that a single-stream division cannot express.

This module measures instead. Per file format it takes a systematic sample across the size
distribution, extracts each sampled file the way the indexer does, runs the configured
``Chunker`` over it, and extrapolates with a ratio estimator on the group's known total bytes.
The ratio estimator is what makes it stable: scaling a rank-uniform sample by file count
over-weights the largest file in every format and came out 3.3x high on a code corpus, while
scaling measured tokens-per-byte by the exact byte total lands within 10% on all three corpora
with a completed run to check against.

Accuracy against three live indexes, estimate / actual (16 samples per format, ~2 s):

    corpus shape                      chunks            tokens
    one 359-page scanned PDF          1,323 / 1,315     267,318 / 244,789
    2,000 small plain-text documents  2,672 / 3,126     361,906 / 346,731
    794 files of source and docs      6,089 / 5,806     3,848,895 / 3,531,477
"""

from __future__ import annotations

import math
import re
import time
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from server.indexing.chunker import Chunker
from server.indexing.text_extractors import extract_text_for_path

# Sampling invariants. The budget is wall clock for the whole sample: the estimate backs a
# confirmation dialog, so it may never make the operator wait on a corpus walk. Every format
# is measured at least once even when the budget is already gone -- an estimate with nothing
# measured would be the byte ratio this module exists to replace.
_SAMPLE_FILES_PER_FORMAT = 16
_SAMPLE_BUDGET_SECONDS = 5.0

# PDFs: pypdfium2 reads the page text in well under a second where a Docling conversion of the
# same document takes minutes, so the estimate reads pages and scales. Calibrated on the
# Apollo 11 Mission Report (359 pages): its pdfium page text through the configured chunker is
# 152,753 chunk tokens in 778 chunks, against the completed figure-enabled run's 244,789
# tokens in 1,315 chunks. Docling re-emits tables as markdown and folds in the figure
# descriptions, which is the whole of the difference -- so with figure description turned off
# these factors run high by roughly the figure share (124 of 1,315 chunks on that run).
_PDF_SAMPLE_MAX_PAGES = 400
_PDF_TOKEN_FACTOR = 1.60
_PDF_CHUNK_FACTOR = 1.69

# Band. The model error covers the extraction factors, the chunker's per-format fallbacks and
# the indexer's streaming path for very large text files; the sampling term is charged only
# for formats the estimator could not measure in full.
_MODEL_RELATIVE_ERROR = 0.35
_MAX_RELATIVE_ERROR = 0.90

_PDF_SUFFIX = ".pdf"
_HTML_SUFFIXES = frozenset({".html", ".htm"})
# Office documents are zip containers of XML. Their text is read straight out of the parts
# below rather than through Docling, which would cost a full conversion per sampled file.
_OFFICE_PARTS: dict[str, tuple[str, ...]] = {
    ".docx": ("word/document.xml",),
    ".pptx": ("ppt/slides/",),
    ".xlsx": ("xl/sharedStrings.xml",),
}
_XML_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class CorpusSample:
    """Measured corpus size with the band and the assumptions that produced it."""

    total_tokens: int
    total_chunks: int
    tokens_low: int
    tokens_high: int
    chunks_low: int
    chunks_high: int
    sampled_files: int
    sampled_bytes: int
    relative_error: float
    formats: tuple[str, ...]
    budget_exhausted: bool
    assumptions: tuple[str, ...]

    @classmethod
    def empty(cls) -> CorpusSample:
        return cls(
            total_tokens=0,
            total_chunks=0,
            tokens_low=0,
            tokens_high=0,
            chunks_low=0,
            chunks_high=0,
            sampled_files=0,
            sampled_bytes=0,
            relative_error=_MODEL_RELATIVE_ERROR,
            formats=(),
            budget_exhausted=False,
            assumptions=(),
        )


class _TextOnly(HTMLParser):
    """Collect the rendered text of an HTML document, dropping script/style bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._muted = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:  # noqa: ARG002
        if tag in {"script", "style"}:
            self._muted += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._muted > 0:
            self._muted -= 1

    def handle_data(self, data: str) -> None:
        if self._muted == 0 and data.strip():
            self.parts.append(data)


def _read_html_text(path: Path) -> str:
    parser = _TextOnly()
    try:
        parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
        parser.close()
    except Exception:
        return ""
    return "\n".join(parser.parts)


def _read_office_text(path: Path, parts: tuple[str, ...]) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if any(name == part or name.startswith(part) for part in parts)
            ]
            out: list[str] = []
            for name in sorted(names):
                if not name.endswith(".xml"):
                    continue
                raw = archive.read(name).decode("utf-8", errors="ignore")
                out.append(_XML_TAG.sub(" ", raw))
    except Exception:
        return ""
    return "\n".join(out)


def _read_pdf_text(path: Path) -> tuple[str, float]:
    """Page text and the factor that scales it to the whole document."""
    import pypdfium2 as pdfium
    from docling.utils.locks import pypdfium2_lock

    with pypdfium2_lock:
        try:
            document = pdfium.PdfDocument(str(path))
        except Exception:
            return "", 1.0
        try:
            pages = len(document)
            if pages <= 0:
                return "", 1.0
            wanted = min(pages, _PDF_SAMPLE_MAX_PAGES)
            indexes = (
                list(range(pages))
                if wanted >= pages
                else [round(i * (pages - 1) / (wanted - 1)) for i in range(wanted)]
            )
            parts: list[str] = []
            for index in indexes:
                page = document[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        parts.append(textpage.get_text_range())
                    finally:
                        textpage.close()
                finally:
                    page.close()
            return "\n\n".join(parts), float(pages) / float(len(indexes))
        finally:
            document.close()


def _extracted_text(path: Path, ext: str) -> tuple[str, float, float, float]:
    """``(text, page_scale, token_factor, chunk_factor)`` for one sampled file.

    Mirrors what the indexer feeds the chunker for every format it can read cheaply. Docling
    conversions are the exception: a real conversion costs minutes per document, so PDFs are
    read by pypdfium2 and scaled by the measured factors above, and office containers are read
    out of their own XML parts.
    """
    if ext == _PDF_SUFFIX:
        text, page_scale = _read_pdf_text(path)
        return text, page_scale, _PDF_TOKEN_FACTOR, _PDF_CHUNK_FACTOR
    if ext in _HTML_SUFFIXES:
        return _read_html_text(path), 1.0, 1.0, 1.0
    office_parts = _OFFICE_PARTS.get(ext)
    if office_parts is not None:
        return _read_office_text(path, office_parts), 1.0, 1.0, 1.0
    extracted = extract_text_for_path(path)
    if extracted is not None:
        return extracted.text, 1.0, 1.0, 1.0
    # Same last resort as the indexer: read it as UTF-8 and let the NUL check below decide.
    try:
        return path.read_text(encoding="utf-8", errors="ignore"), 1.0, 1.0, 1.0
    except Exception:
        return "", 1.0, 1.0, 1.0


def _measure(path: Path, ext: str, chunker: Chunker) -> tuple[float, float]:
    """Chunks and chunk tokens this one file contributes, or ``(0.0, 0.0)`` if the indexer skips it."""
    text, page_scale, token_factor, chunk_factor = _extracted_text(path, ext)
    # The indexer drops any document whose text contains a NUL byte; so does the estimate,
    # or a directory of binaries would be sized as if it were prose.
    if not text or "\x00" in text:
        return 0.0, 0.0
    chunks = chunker.chunk_file(path.name, text)
    if not chunks:
        return 0.0, 0.0
    tokens = float(sum(int(chunk.token_count or 0) for chunk in chunks))
    return len(chunks) * page_scale * chunk_factor, tokens * page_scale * token_factor


def _systematic_picks(
    items: list[tuple[Path, int]], count: int
) -> list[tuple[Path, int]]:
    """``count`` files spread evenly across the size-sorted group, endpoints included."""
    total = len(items)
    if count >= total:
        return list(items)
    if count <= 1:
        return [items[total // 2]]
    return [items[round(i * (total - 1) / (count - 1))] for i in range(count)]



def warm_sampler(chunker: Chunker) -> None:
    """Load whatever the sampler loads lazily, so the first estimate does not pay for it.

    The chunker's tokenizer loads its model on first use -- measured at 29.3 s in a fresh API
    process against a 30 s client timeout, i.e. the operator's first Index Now after every
    service restart was a coin flip. Nothing in the sampling budget can help: the budget is
    checked between files and the load happens inside the first one.

    Cheap and idempotent: the tokenizer caches per model name, so after the first call this
    costs a few hundred microseconds. Safe to call from anywhere, including a background task.
    """
    chunker.chunk_file("warmup.md", "warm the tokenizer with one short line of text.\n")


def sample_corpus(
    *,
    files: Sequence[tuple[Path, int]],
    chunker: Chunker,
    budget_seconds: float = _SAMPLE_BUDGET_SECONDS,
    files_per_format: int = _SAMPLE_FILES_PER_FORMAT,
) -> CorpusSample:
    """Estimate a corpus's chunk and token totals by measuring a sample of its files."""
    if not files:
        return CorpusSample.empty()

    groups: dict[str, list[tuple[Path, int]]] = {}
    for path, size in files:
        groups.setdefault(path.suffix.lower(), []).append((path, max(0, int(size))))

    started = time.monotonic()
    total_tokens = 0.0
    total_chunks = 0.0
    sampled_files = 0
    sampled_bytes = 0
    partial_sampled = 0
    budget_exhausted = False
    saw_pdf = False
    saw_converted = False

    for ext, items in sorted(groups.items()):
        items.sort(key=lambda item: item[1])
        group_files = len(items)
        group_bytes = sum(size for _path, size in items)
        picks = _systematic_picks(items, min(files_per_format, group_files))

        measured_chunks = 0.0
        measured_tokens = 0.0
        measured_bytes = 0
        measured_files = 0
        indexable_files = 0
        for path, size in picks:
            if measured_files > 0 and (time.monotonic() - started) >= budget_seconds:
                budget_exhausted = True
                break
            chunks, tokens = _measure(path, ext, chunker)
            measured_chunks += chunks
            measured_tokens += tokens
            measured_bytes += size
            measured_files += 1
            if chunks > 0:
                indexable_files += 1

        sampled_files += measured_files
        sampled_bytes += measured_bytes
        if measured_files < group_files:
            partial_sampled += measured_files
        if ext == _PDF_SUFFIX:
            saw_pdf = True
        elif ext in _HTML_SUFFIXES or ext in _OFFICE_PARTS:
            saw_converted = True

        if measured_bytes <= 0:
            continue
        scale = float(group_bytes) / float(measured_bytes)
        group_tokens = measured_tokens * scale
        group_chunks = measured_chunks * scale
        # Chunking is per file with a one-chunk minimum, so a corpus of files smaller than one
        # chunk cannot have fewer chunks than it has readable files however few bytes it holds.
        floor = float(group_files) * (float(indexable_files) / float(measured_files))
        total_tokens += group_tokens
        total_chunks += max(group_chunks, floor)

    relative_error = (
        _MODEL_RELATIVE_ERROR
        if partial_sampled <= 0
        else min(_MAX_RELATIVE_ERROR, _MODEL_RELATIVE_ERROR + 1.0 / math.sqrt(partial_sampled))
    )

    tokens = int(round(total_tokens))
    chunks = int(round(total_chunks))
    assumptions: list[str] = [
        f"tokens and chunks measured by chunking {sampled_files:,} sampled files "
        f"({sampled_bytes:,} bytes) with the configured chunker, then scaled by byte share",
        f"estimate error band ±{relative_error * 100:.0f}%",
    ]
    if saw_pdf:
        assumptions.append(
            f"PDF text read with pypdfium2 and scaled to a Docling conversion "
            f"(tokens ×{_PDF_TOKEN_FACTOR:g}, chunks ×{_PDF_CHUNK_FACTOR:g}, measured on the "
            "Apollo 11 mission report)"
        )
    if saw_converted:
        assumptions.append(
            "HTML and office documents measured from their own text, without Docling's "
            "layout markup (uncalibrated)"
        )
    if budget_exhausted:
        assumptions.append(
            f"sampling stopped at the {budget_seconds:g}s budget; the rest is extrapolated"
        )

    return CorpusSample(
        total_tokens=tokens,
        total_chunks=chunks,
        tokens_low=max(0, int(round(total_tokens * (1.0 - relative_error)))),
        tokens_high=int(round(total_tokens * (1.0 + relative_error))),
        chunks_low=max(0, int(round(total_chunks * (1.0 - relative_error)))),
        chunks_high=int(round(total_chunks * (1.0 + relative_error))),
        sampled_files=sampled_files,
        sampled_bytes=sampled_bytes,
        relative_error=relative_error,
        formats=tuple(sorted(groups)),
        budget_exhausted=budget_exhausted,
        assumptions=tuple(assumptions),
    )
