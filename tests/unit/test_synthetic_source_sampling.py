"""Synthetic source chunks are drawn from across each document, not its head.

Regression: within each file the draw always took the first chunks by start_line, so on the
single-file nasa-apollo-11 corpus every generated question came from the cover, the front
matter and the first appendix tables (agency name, report number, distribution boilerplate).
Pure, seeded selection over real ``Chunk`` rows; the whole-corpus candidate fetch is proven
against live Postgres in tests/integration/test_synthetic_source_sampling_live.py.
"""

from __future__ import annotations

import random

from server.models.index import Chunk
from server.synthetic.recipes import _round_robin_chunks

LINES_PER_CHUNK = 10


def _document(path: str, chunk_count: int) -> list[Chunk]:
    return [
        Chunk(
            chunk_id=f"pytest_{path}_{index:04d}",
            content=f"section {index}",
            file_path=path,
            start_line=index * LINES_PER_CHUNK + 1,
            end_line=index * LINES_PER_CHUNK + LINES_PER_CHUNK,
        )
        for index in range(chunk_count)
    ]


def test_a_long_single_document_is_sampled_from_every_quarter() -> None:
    chunks = _document("A11_MissionReport.pdf", 400)
    total_lines = 400 * LINES_PER_CHUNK
    picked = _round_robin_chunks(chunks, 10, random.Random(1337))

    assert len(picked) == 10
    starts = sorted(chunk.start_line for chunk in picked)
    assert (starts[-1] - starts[0]) / total_lines > 0.75, starts
    quarters = {(chunk.start_line - 1) * 4 // total_lines for chunk in picked}
    assert quarters == {0, 1, 2, 3}, starts


def test_sampling_is_deterministic_per_seed_and_varies_across_seeds() -> None:
    chunks = _document("A11_MissionReport.pdf", 400)

    def ids(seed: int) -> list[str]:
        return [chunk.chunk_id for chunk in _round_robin_chunks(chunks, 10, random.Random(seed))]

    assert ids(1337) == ids(1337)
    assert ids(1337) != ids(7)
    # Input order does not change the draw.
    shuffled = list(chunks)
    random.Random(99).shuffle(shuffled)
    assert [c.chunk_id for c in _round_robin_chunks(shuffled, 10, random.Random(1337))] == ids(1337)


def test_every_file_contributes_before_any_file_contributes_twice() -> None:
    chunks = _document("a.md", 50) + _document("b.md", 3) + _document("c.md", 120)
    picked = _round_robin_chunks(chunks, 3, random.Random(1337))
    assert sorted(chunk.file_path for chunk in picked) == ["a.md", "b.md", "c.md"]
    # A limit beyond the corpus returns every chunk exactly once.
    everything = _round_robin_chunks(chunks, 10_000, random.Random(1337))
    assert sorted(chunk.chunk_id for chunk in everything) == sorted(chunk.chunk_id for chunk in chunks)
