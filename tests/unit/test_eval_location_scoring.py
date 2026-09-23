"""Chunk-level eval scoring (server/evaluation/scoring.py): the one scorer behind every eval path.

Regression for the vacuous-100% defect: scoring compared de-duplicated file paths only, so on a
single-document corpus (nasa-apollo-11: one PDF, 359 pages) every question scored top-1 and
MRR 1.0 however badly the chunks ranked. These cases score real ``ChunkMatch`` rows (the shape
fusion returns) against typed page/line expectations; nothing is patched.
"""

from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from server.evaluation.scoring import (
    MAP_AT_K,
    EvalCutoffs,
    aggregate_entry_scores,
    build_expectations,
    classify_chunk,
    is_uninformative,
    score_entry,
)
from server.models.index import ChunkProvenance, PageRegion
from server.models.tribrid_config_model import (
    ChunkMatch,
    EvalDatasetItem,
    EvalExpectedLocation,
    EvalTestRequest,
)

PDF = "A11_MissionReport.pdf"
CUTOFFS = EvalCutoffs(final_k=5, recall_at_5=5, recall_at_10=10, recall_at_20=20, precision_at_5=5, ndcg_at_10=10)


def _pdf_chunk(rank: int, page_start: int | None, page_end: int | None, *, path: str = PDF) -> ChunkMatch:
    provenance = None
    if page_start is not None and page_end is not None:
        provenance = ChunkProvenance(
            extraction="docling",
            page_start=page_start,
            page_end=page_end,
            regions=[PageRegion(page=page_start, left=0.1, top=0.1, right=0.9, bottom=0.4)],
        )
    return ChunkMatch(
        chunk_id=f"pytest_pdf_{rank}",
        content="",
        file_path=path,
        start_line=rank * 40 + 1,
        end_line=rank * 40 + 30,
        score=1.0 / (rank + 1),
        source="vector",
        provenance=provenance,
    )


def _text_chunk(rank: int, path: str, start: int, end: int) -> ChunkMatch:
    return ChunkMatch(
        chunk_id=f"pytest_txt_{rank}",
        content="",
        file_path=path,
        start_line=start,
        end_line=end,
        score=1.0 / (rank + 1),
        source="sparse",
    )


def _pages(start: int, end: int, path: str = PDF) -> EvalExpectedLocation:
    return EvalExpectedLocation(path=path, unit="page", start=start, end=end)


def _lines(path: str, start: int, end: int) -> EvalExpectedLocation:
    return EvalExpectedLocation(path=path, unit="line", start=start, end=end)


# Ranked chunks of the one-PDF corpus for "What was the descent engine throttle behavior?":
# the powered-descent pages 176-179 rank second and third behind an unrelated page-52 chunk.
RANKED_PDF_CHUNKS = [_pdf_chunk(0, 52, 53), _pdf_chunk(1, 176, 179), _pdf_chunk(2, 179, 179)]


@pytest.mark.parametrize(
    ("location", "top1", "topk", "reciprocal_rank", "kinds"),
    [
        # The answer lives on pages 281-282 and nothing retrieved is there: a miss, not 100%.
        (_pages(281, 282), False, False, 0.0, ("outside_location",) * 3),
        # Pages 176-176 are only covered by the second chunk.
        (_pages(176, 176), False, True, 0.5, ("outside_location", "location", "outside_location")),
        # Page 53 is the tail of the first chunk's span.
        (_pages(53, 60), True, True, 1.0, ("location", "outside_location", "outside_location")),
    ],
)
def test_single_document_corpus_with_page_expectations_can_score_a_miss(
    location: EvalExpectedLocation, top1: bool, topk: bool, reciprocal_rank: float, kinds: tuple[str, ...]
) -> None:
    score = score_entry(
        build_expectations([PDF], [location]), RANKED_PDF_CHUNKS, cutoffs=CUTOFFS, corpus_paths=[PDF]
    )
    assert score.uninformative is False
    assert score.top1_hit is top1
    assert score.topk_hit is topk
    assert score.reciprocal_rank == pytest.approx(reciprocal_rank)
    assert score.matches == kinds


def test_single_document_corpus_with_a_file_only_expectation_is_uninformative() -> None:
    score = score_entry(build_expectations([PDF], []), RANKED_PDF_CHUNKS, cutoffs=CUTOFFS, corpus_paths=[PDF])
    assert score.uninformative is True
    # Every chunk of the only document "matches" the file; that is exactly why it cannot count.
    assert score.matches == ("file", "file", "file")


@pytest.mark.parametrize(
    ("chunk_span", "expected_span", "hit"),
    [
        ((10, 20), (20, 30), True),  # touching at the last line (inclusive)
        ((30, 40), (20, 30), True),  # touching at the first line
        ((10, 19), (20, 30), False),  # ends one line before
        ((31, 40), (20, 30), False),  # starts one line after
        ((1, 100), (20, 30), True),  # chunk contains the span
        ((22, 24), (20, 30), True),  # span contains the chunk
        ((25, 25), (25, 25), True),  # single line on single line
    ],
)
def test_line_range_overlap_matrix(chunk_span: tuple[int, int], expected_span: tuple[int, int], hit: bool) -> None:
    path = "docs/sensor-calibration.md"
    expectations = build_expectations([path], [_lines(path, *expected_span)])
    kind, satisfied = classify_chunk(_text_chunk(0, path, *chunk_span), expectations)
    assert bool(satisfied) is hit
    assert kind == ("location" if hit else "outside_location")


def test_a_chunk_from_another_file_never_satisfies_a_location() -> None:
    expectations = build_expectations(["docs/a.md"], [_lines("docs/a.md", 1, 50)])
    kind, satisfied = classify_chunk(_text_chunk(0, "docs/b.md", 1, 50), expectations)
    assert (kind, satisfied) == ("none", frozenset())


def test_a_page_expectation_is_not_hit_by_a_chunk_without_page_provenance() -> None:
    """Chunks indexed before provenance capture carry no pages; they are reported, not scored as hits."""
    expectations = build_expectations([PDF], [_pages(176, 179)])
    kind, satisfied = classify_chunk(_pdf_chunk(0, None, None), expectations)
    assert kind == "no_page_provenance"
    assert satisfied == frozenset()


def test_ranks_are_chunk_ranks_not_deduplicated_file_ranks() -> None:
    """Two chunks of a.md ahead of b.md put b.md at chunk rank 3 (the old file rank was 2)."""
    chunks = [
        _text_chunk(0, "docs/a.md", 1, 10),
        _text_chunk(1, "docs/a.md", 11, 20),
        _text_chunk(2, "docs/b.md", 1, 10),
    ]
    score = score_entry(
        build_expectations(["docs/b.md"], []), chunks, cutoffs=CUTOFFS, corpus_paths=["docs/a.md", "docs/b.md"]
    )
    assert score.uninformative is False
    assert score.reciprocal_rank == pytest.approx(1.0 / 3.0)
    assert score.matches == ("none", "none", "file")


@pytest.mark.parametrize(
    ("expected_paths", "locations", "corpus_paths", "uninformative"),
    [
        ([], [], ["docs/a.md"], True),  # nothing to hit
        (["docs/a.md"], [], ["docs/a.md"], True),  # the only document, file-only
        (["a.md", "b.md"], [], ["docs/a.md", "docs/b.md"], True),  # file-only over every document
        (["docs/a.md"], [], ["docs/a.md", "docs/b.md"], False),  # b.md chunks can miss
        (["docs/a.md"], [_lines("docs/a.md", 5, 9)], ["docs/a.md"], False),  # located on one doc
        (["docs/a.md"], [], [], False),  # nothing indexed: not provably vacuous
    ],
)
def test_uninformative_detection(
    expected_paths: list[str],
    locations: list[EvalExpectedLocation],
    corpus_paths: list[str],
    uninformative: bool,
) -> None:
    assert is_uninformative(build_expectations(expected_paths, locations), corpus_paths) is uninformative


def test_rank_metrics_stay_within_bounds_however_many_chunks_hit_one_expectation() -> None:
    """Property: many chunks of one expected file must not push nDCG/AP/precision/recall past 1."""
    rng = random.Random(20260923)
    paths = ["docs/a.md", "docs/b.md", "docs/c.md"]
    for _ in range(300):
        chunks = [
            _text_chunk(rank, rng.choice(paths), start, start + rng.randint(0, 30))
            for rank, start in enumerate(rng.randint(1, 400) for _ in range(rng.randint(0, 25)))
        ]
        expected = rng.sample(paths, rng.randint(1, 3))
        locations: list[EvalExpectedLocation] = []
        for path in expected:
            if rng.random() < 0.5:
                start = rng.randint(1, 400)
                locations.append(_lines(path, start, start + rng.randint(0, 60)))
        score = score_entry(build_expectations(expected, locations), chunks, cutoffs=CUTOFFS, corpus_paths=paths)
        for value in (
            score.reciprocal_rank,
            score.recall,
            score.recall_at_5,
            score.recall_at_10,
            score.recall_at_20,
            score.precision_at_5,
            score.ndcg_at_10,
            score.average_precision_at_5,
        ):
            assert 0.0 <= value <= 1.0 + 1e-12, (value, expected, locations)


def test_every_chunk_on_the_expected_pages_is_a_perfect_ranking() -> None:
    chunks = [_pdf_chunk(rank, 176, 179) for rank in range(12)]
    score = score_entry(build_expectations([PDF], [_pages(177, 178)]), chunks, cutoffs=CUTOFFS, corpus_paths=[PDF])
    assert score.ndcg_at_10 == pytest.approx(1.0)
    assert score.average_precision_at_5 == pytest.approx(1.0)
    assert score.precision_at_5 == pytest.approx(1.0)
    assert MAP_AT_K == 5


def test_headline_metrics_exclude_uninformative_entries() -> None:
    informative_miss = score_entry(
        build_expectations([PDF], [_pages(281, 282)]), RANKED_PDF_CHUNKS, cutoffs=CUTOFFS, corpus_paths=[PDF]
    )
    informative_hit = score_entry(
        build_expectations([PDF], [_pages(52, 52)]), RANKED_PDF_CHUNKS, cutoffs=CUTOFFS, corpus_paths=[PDF]
    )
    vacuous = score_entry(build_expectations([PDF], []), RANKED_PDF_CHUNKS, cutoffs=CUTOFFS, corpus_paths=[PDF])

    headline = aggregate_entry_scores([informative_miss, vacuous, informative_hit, vacuous])
    assert (headline.total, headline.uninformative, headline.scored) == (4, 2, 2)
    assert headline.top1_hits == 1
    assert headline.top1_accuracy == pytest.approx(0.5)
    assert headline.mrr == pytest.approx(0.5)
    assert headline.map_at_5 is not None

    only_vacuous = aggregate_entry_scores([vacuous, vacuous])
    assert (only_vacuous.scored, only_vacuous.top1_accuracy, only_vacuous.map_at_5) == (0, 0.0, None)


def test_expected_locations_contract() -> None:
    question = "What was the Apollo 11 lunar module descent engine throttle setting during powered descent?"
    item = EvalDatasetItem(
        question=question,
        expected_paths=["./A11_MissionReport.pdf"],
        expected_locations=[_pages(176, 179)],
    )
    assert item.expected_locations[0].unit == "page"
    # Rows persisted before locations existed still load unchanged.
    assert EvalDatasetItem.model_validate({"question": question, "expected_paths": [PDF]}).expected_locations == []

    with pytest.raises(ValidationError, match="not one of expected_paths"):
        EvalDatasetItem(question=question, expected_paths=["other.pdf"], expected_locations=[_pages(1, 2)])
    with pytest.raises(ValidationError, match="more than one expected location"):
        EvalDatasetItem(question=question, expected_paths=[PDF], expected_locations=[_pages(1, 2), _pages(5, 6)])
    with pytest.raises(ValidationError, match="start 9 > end 3"):
        EvalExpectedLocation(path=PDF, unit="page", start=9, end=3)
    with pytest.raises(ValidationError):
        EvalExpectedLocation(path=PDF, unit="page", start=0, end=3)
    with pytest.raises(ValidationError, match="not one of expected_paths"):
        EvalTestRequest(corpus_id="pytest_eval", question=question, expected_paths=[], expected_locations=[_pages(1, 2)])
