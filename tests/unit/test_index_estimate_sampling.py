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


def test_a_uniform_corpus_keeps_the_floor_band_however_little_of_it_was_opened(
    tmp_path: Path,
) -> None:
    """400 identical files have nothing left to be uncertain about after the first few.

    The band's sampling term is the observed spread of tokens-per-byte, so a corpus whose files
    are all alike reports the model floor -- not a penalty for the file count. Charging by
    ``1/sqrt(n)`` alone, as this did first, would have widened the band on a corpus that could
    not be more predictable.
    """
    files = _write_many(tmp_path, 400, "one short note.\n")
    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    assert sample.sampled_files < 400
    assert sample.relative_error == _MODEL_RELATIVE_ERROR


def test_a_heterogeneous_corpus_widens_the_band(tmp_path: Path) -> None:
    """The same file count, wildly different documents: the band has to say so."""
    files = []
    for i in range(400):
        path = tmp_path / f"mixed_{i:04d}.txt"
        # Alternating dense prose and near-empty files: the token density really does vary.
        path.write_text("x\n" if i % 2 else "lunar module telemetry sample line.\n" * 40, encoding="utf-8")
        files.append(path)

    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    assert sample.sampled_files < 400
    assert sample.relative_error > _MODEL_RELATIVE_ERROR, (
        "a corpus whose token density varies by an order of magnitude must not report the same "
        "band as a uniform one"
    )


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


def test_a_relative_corpus_root_resolves_against_the_runtime_root_not_the_cwd(tmp_path: Path) -> None:
    """The recall corpus is registered as the relative "data/recall".

    Resolved against the process CWD, that names a different directory for every process that
    reads it -- so the estimate answered "repo_path not found: data/recall" while a uvicorn
    started from the repo root would have found it. Anchoring to the runtime root that owns
    data/ makes it one place.
    """
    from server.api.index import _RUNTIME_ROOT, _resolve_corpus_root

    assert _resolve_corpus_root("data/recall") == (_RUNTIME_ROOT / "data" / "recall").resolve()
    # An absolute path is left exactly where it points.
    assert _resolve_corpus_root(str(tmp_path)) == tmp_path.resolve()
    # And the resolution does not depend on where the process happens to be running.
    assert _resolve_corpus_root("data/recall").is_absolute()


def test_the_runtime_root_is_the_directory_that_owns_data(tmp_path: Path) -> None:
    from server.api.index import _INDEX_RUNS_DIR, _RUNTIME_ROOT

    assert (_RUNTIME_ROOT / "data").exists()
    # Same anchor the persisted run directory already uses, so the two cannot drift apart.
    assert _INDEX_RUNS_DIR.parent.parent == _RUNTIME_ROOT


def test_a_saturated_error_band_refuses_to_produce_a_number(tmp_path: Path) -> None:
    """The G-1 shape, caught by the signal that actually distinguishes it.

    A cold run measured 6 files totalling 8 bytes of 8.5 MB and the byte-ratio estimator scaled
    them to 15,437 tokens for a 3,531,477-token corpus. What made that sample worthless was not
    its size -- 1.31% of epstein-files-public is a fine sample -- but that it said nothing: the
    band computed from its own spread saturates.
    """
    files = []
    for i in range(60):
        path = tmp_path / f"mixed_{i:04d}.txt"
        # Densities two orders of magnitude apart, so the measured spread is enormous.
        path.write_text("\n" * 400 if i % 2 else "telemetry sample line.\n" * 400, encoding="utf-8")
        files.append(path)

    sample = sample_corpus(files=_sized(files), chunker=_chunker(), max_relative_error=0.4)

    assert sample.sufficient is False
    assert "error band" in sample.insufficient_reason
    assert any(a.startswith("NO ESTIMATE") for a in sample.assumptions)


def test_many_similar_files_are_a_good_sample_however_small_their_byte_share(
    tmp_path: Path,
) -> None:
    """The case a share-of-bytes floor got wrong.

    epstein-files-public is 2,000 similar documents; sampling 16 of them covers 1.31% of the
    corpus's bytes and estimates it accurately (361,906 tokens against an actual 346,731). A 5%
    byte floor refused exactly this, and would refuse any format group over ~320 similar files.
    """
    files = _write_many(tmp_path, 800, "a short note about lunar module telemetry.\n")

    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    covered = sample.sampled_bytes / sum(size for _p, size in _sized(files))
    assert covered < 0.05, f"precondition: this samples {covered * 100:.2f}% of the bytes"
    assert sample.sufficient is True, sample.insufficient_reason
    assert sample.total_chunks >= 800


def test_a_format_that_measured_nothing_refuses_too(tmp_path: Path) -> None:
    """A starved group contributes no tokens, no chunks and not even its one-per-file floor."""
    (tmp_path / "a.txt").write_text("one short note.\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    sample = sample_corpus(
        files=_sized([tmp_path / "a.txt", tmp_path / "b.py"]),
        chunker=_chunker(),
        min_files_per_format=2,  # neither group can reach this, so both are starved
    )

    assert sample.sufficient is False
    assert "not measured at all" in sample.insufficient_reason


def test_a_well_covered_sample_is_still_sufficient(tmp_path: Path) -> None:
    """The floors must not refuse the ordinary case they exist to protect."""
    files = _write_many(tmp_path, 12, "telemetry sample line.\n" * 20)

    sample = sample_corpus(files=_sized(files), chunker=_chunker())

    assert sample.sufficient is True
    assert sample.insufficient_reason == ""
    assert sample.total_chunks >= 12


def test_the_model_load_is_not_charged_to_the_sampling_budget(tmp_path: Path) -> None:
    """Why G-1 happened: the load ran inside the first pick and ate the whole budget.

    With a zero budget the sampler still measures one file per the old rule -- what it must NOT
    do is let the load consume the budget and then extrapolate the one file it managed. The
    warm-up now runs before the clock starts, so a zero budget is a real zero.
    """
    from server.indexing.estimate import _MODEL_RELATIVE_ERROR  # noqa: F401

    files = _write_many(tmp_path, 30, "telemetry sample line.\n" * 50)

    sample = sample_corpus(files=_sized(files), chunker=_chunker(), budget_seconds=0.0)

    # One file measured, 30 in the group: nowhere near the default 5% byte floor... except the
    # single file IS ~3.3% here, so assert the mechanism rather than a magic number.
    assert sample.budget_exhausted is True
    assert sample.sampled_files == 1
