"""The index estimate is measured, not a byte ratio.

Every assertion here runs the real ``Chunker`` over real files on disk. The estimator this
covers replaced ``tokens = bytes / 4`` and ``chunks = tokens / 448``: on the Apollo 11 mission
report those constants sized tokens from embedded fonts and images and predicted 3,993,486
tokens / 8,915 chunks against an actual 244,789 / 1,315.
"""

from __future__ import annotations

import time
from pathlib import Path

from server.indexing.chunker import Chunker
from server.indexing.estimate import (
    _MODEL_RELATIVE_ERROR,
    _PDF_CHUNK_FACTOR,
    _PDF_TOKEN_FACTOR,
    CorpusSample,
    sample_corpus,
)
from server.models.tribrid_config_model import TriBridConfig
from tests.fixtures.pdf_builder import build_pdf


def _chunker(cfg: TriBridConfig | None = None) -> Chunker:
    c = cfg or TriBridConfig()
    return Chunker(c.chunking, c.tokenization)


def _sized(paths: list[Path]) -> list[tuple[Path, int]]:
    return [(p, p.stat().st_size) for p in paths]


def _write_many(root: Path, count: int, body: str) -> list[Path]:
    out = []
    for i in range(count):
        p = root / f"note_{i:04d}.txt"
        p.write_text(body, encoding="utf-8")
        out.append(p)
    return out


def test_every_non_empty_file_contributes_at_least_one_chunk(tmp_path: Path) -> None:
    """The defect that made epstein-files-public 4.5x too low.

    2,000 files of ~625 bytes produced 3,126 chunks because chunking is per file with a
    one-chunk minimum; ``bytes / 4 / 448`` sized the whole corpus as one stream and said 698.
    """
    files = _write_many(tmp_path, 300, "a short note about lunar module telemetry.\n")
    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    assert sample.total_chunks >= 300
    assert sample.total_tokens > 0


def test_a_pdf_is_sized_from_its_extracted_text_not_its_container_bytes(tmp_path: Path) -> None:
    """A PDF carries fonts and image streams that no chunker ever sees."""
    pdf = tmp_path / "report.pdf"
    pages = [[f"Page {n} of the mission report."] for n in range(1, 13)]
    pdf.write_bytes(build_pdf(pages))
    padding = tmp_path / "padding.bin"
    # Same page count, an order of magnitude more container bytes: a byte ratio would move,
    # extracted text does not.
    fat = tmp_path / "report_fat.pdf"
    fat.write_bytes(build_pdf(pages) + b"\n%" + b"0" * 400_000)
    padding.unlink(missing_ok=True)

    lean = sample_corpus(files=_sized([pdf]), chunker=_chunker())
    heavy = sample_corpus(files=_sized([fat]), chunker=_chunker())

    assert fat.stat().st_size > pdf.stat().st_size * 5
    assert lean.total_tokens == heavy.total_tokens
    assert lean.total_tokens < pdf.stat().st_size / 4


def test_the_pdf_factors_are_the_measured_ones() -> None:
    """Pins the calibration, not merely its rounded output.

    Measured on the Apollo 11 Mission Report (359 pages): pypdfium2 page text run through the
    configured chunker yields 152,753 chunk tokens in 778 chunks, against the completed
    figure-enabled Docling run's 244,789 tokens in 1,315 chunks.
    """
    assert _PDF_TOKEN_FACTOR == 1.60
    assert _PDF_CHUNK_FACTOR == 1.69


def test_the_error_band_brackets_the_point_estimate(tmp_path: Path) -> None:
    files = _write_many(tmp_path, 40, "telemetry sample line.\n" * 20)
    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    assert sample.relative_error >= _MODEL_RELATIVE_ERROR
    assert sample.tokens_low <= sample.total_tokens <= sample.tokens_high
    assert sample.chunks_low <= sample.total_chunks <= sample.chunks_high
    assert sample.tokens_low >= 0 and sample.chunks_low >= 0


def test_a_fully_measured_corpus_carries_no_sampling_error(tmp_path: Path) -> None:
    """Sampling error is only charged for files the estimator did not open."""
    files = _write_many(tmp_path, 3, "one short note.\n")
    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    assert sample.sampled_files == 3
    assert sample.relative_error == _MODEL_RELATIVE_ERROR


def test_a_partly_sampled_corpus_widens_the_band(tmp_path: Path) -> None:
    files = _write_many(tmp_path, 400, "one short note.\n")
    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    assert sample.sampled_files < 400
    assert sample.relative_error > _MODEL_RELATIVE_ERROR


def test_the_sample_stops_at_the_time_budget(tmp_path: Path) -> None:
    files = _write_many(tmp_path, 600, "telemetry sample line.\n" * 200)
    started = time.monotonic()
    sample = sample_corpus(files=_sized(files), chunker=_chunker(), budget_seconds=0.0)
    elapsed = time.monotonic() - started

    # A zero budget still measures one file per format -- an estimate with nothing measured
    # would be the byte ratio again -- and then stops.
    assert sample.sampled_files == 1
    assert sample.budget_exhausted is True
    assert elapsed < 5.0
    assert sample.total_chunks >= 600


def test_an_empty_corpus_estimates_nothing(tmp_path: Path) -> None:
    sample = sample_corpus(files=[], chunker=_chunker())

    assert sample == CorpusSample.empty()
    assert sample.total_tokens == 0 and sample.total_chunks == 0
    assert sample.assumptions == ()


def test_each_format_is_sampled_on_its_own(tmp_path: Path) -> None:
    """One tokens-per-byte ratio across a mixed corpus is how the old formula went wrong."""
    (tmp_path / "a.py").write_text("def f():\n    return 1\n" * 50, encoding="utf-8")
    (tmp_path / "b.py").write_text("def g():\n    return 2\n" * 50, encoding="utf-8")
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(build_pdf([["Mission report page one."]]))

    sample = sample_corpus(files=_sized([tmp_path / "a.py", tmp_path / "b.py", pdf]), chunker=_chunker())

    assert sample.sampled_files == 3
    assert set(sample.formats) == {".py", ".pdf"}
    assert any("pdf" in a for a in sample.assumptions)


def test_binary_files_the_indexer_skips_are_not_counted_as_text(tmp_path: Path) -> None:
    blob = tmp_path / "weights.bin"
    blob.write_bytes(b"\x00\x01\x02" * 40_000)

    sample = sample_corpus(files=_sized([blob]), chunker=_chunker())

    assert sample.total_tokens == 0
    assert sample.total_chunks == 0
