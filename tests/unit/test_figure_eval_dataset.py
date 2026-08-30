"""The committed figure eval dataset is real, and the scorer that reads it is honest.

Two halves, both zero-mock: the dataset is validated as data against its boundary model
(the questions must be real Apollo questions grounded on pages that exist in the report),
and the scoring function is exercised as a pure function on hand-built match dicts,
including the shapes a live search actually returns -- absent provenance, null pages,
page spans, and the rank-4 boundary between @3 and @5.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from scripts.eval_figure_grounding import (
    _top_k,
    item_group,
    match_chunk_kind,
    match_covers_page,
    match_figure_summary,
    match_is_precise,
    match_page_span,
    match_span_pages,
    score_matches,
    summarize,
)
from server.models.eval_figures import FigureEvalDataset, FigureEvalItem
from server.models.index import ChunkProvenance

DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "eval_datasets" / "nasa-apollo-11-figures.json"
)

# The Apollo 11 Mission Report (A11_MissionReport.pdf) is 359 scanned pages.
SOURCE_PAGE_COUNT = 359


@pytest.fixture(scope="module")
def dataset() -> FigureEvalDataset:
    return FigureEvalDataset.model_validate_json(DATASET_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The committed dataset
# ---------------------------------------------------------------------------


def test_dataset_validates_against_its_boundary_model(dataset: FigureEvalDataset) -> None:
    assert dataset.corpus_id == "nasa-apollo-11"
    assert len(dataset.items) >= 20


def test_every_expected_page_is_inside_the_source_document(dataset: FigureEvalDataset) -> None:
    for item in dataset.items:
        assert item.expected_pages, f"{item.figure_ref} has no expected page"
        for page in item.expected_pages:
            assert 1 <= page <= SOURCE_PAGE_COUNT, (
                f"{item.figure_ref} cites page {page}, outside 1..{SOURCE_PAGE_COUNT}"
            )


def test_questions_are_real_questions_not_placeholders(dataset: FigureEvalDataset) -> None:
    # Whole words only, and only tokens that are never real prose: "bar" and "baz" are left
    # out deliberately because "scale bar" / "error bar" / "bar chart" are figure vocabulary.
    banned_words = {"lorem", "ipsum", "placeholder", "tbd", "todo", "foo", "asdf", "qwerty"}
    banned_phrases = ("example query", "test query", "sample question")
    for item in dataset.items:
        words = item.question.split()
        assert len(words) >= 6, f"question too short to be real: {item.question!r}"
        assert item.question.strip().endswith("?"), f"not a question: {item.question!r}"
        lowered = item.question.lower()
        tokens = set(re.findall(r"[a-z0-9]+", lowered))
        assert not (tokens & banned_words), f"placeholder word in {item.question!r}"
        assert not any(phrase in lowered for phrase in banned_phrases), (
            f"placeholder phrase in {item.question!r}"
        )


def test_questions_are_unique(dataset: FigureEvalDataset) -> None:
    questions = [item.question for item in dataset.items]
    assert len(set(questions)) == len(questions)


def test_both_kinds_are_present_in_useful_numbers(dataset: FigureEvalDataset) -> None:
    kinds = [item.kind for item in dataset.items]
    assert kinds.count("locate") >= 10
    assert kinds.count("content") >= 10


def test_reporting_groups_are_disjoint_and_cover_every_item(dataset: FigureEvalDataset) -> None:
    """A prose control item must never be counted inside the ``locate`` figure number.

    Prose items carry ``kind="locate"`` (a page is located, not read off a plot), so a naive
    split by ``kind`` would fold the non-regression control into the headline figure result.
    """
    groups: dict[str, list[FigureEvalItem]] = {}
    for item in dataset.items:
        groups.setdefault(item_group(item), []).append(item)

    assert set(groups) == {"locate", "content", "prose"}
    assert sum(len(members) for members in groups.values()) == len(dataset.items)
    for name, members in groups.items():
        assert members, f"group {name} is empty"
    assert all("prose" not in item.tags for item in groups["locate"])
    assert all("prose" not in item.tags for item in groups["content"])
    assert all("prose" in item.tags for item in groups["prose"])
    assert len(groups["prose"]) >= 5


def test_figure_items_name_the_figure_the_report_names(dataset: FigureEvalDataset) -> None:
    figure_items = [item for item in dataset.items if "prose" not in item.tags]
    assert len(figure_items) >= 20
    for item in figure_items:
        assert item.figure_ref.startswith("Figure "), item.figure_ref


def test_locate_and_content_items_cover_distinct_pages(dataset: FigureEvalDataset) -> None:
    """The two figure groups must not measure the same pages, or a single well-indexed
    figure would move both numbers together."""
    pages_of = {
        group: {page for item in dataset.items if item_group(item) == group for page in item.expected_pages}
        for group in ("locate", "content")
    }
    assert not (pages_of["locate"] & pages_of["content"])


def test_dataset_file_is_serialized_from_the_model_shape(dataset: FigureEvalDataset) -> None:
    """The on-disk JSON must carry exactly the model's fields: an unread key in a dataset
    is a silent lie about what is being scored."""
    raw: dict[str, Any] = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert set(raw) == {"corpus_id", "items"}
    allowed = set(FigureEvalItem.model_fields)
    for entry in raw["items"]:
        assert set(entry) <= allowed, f"unknown keys: {set(entry) - allowed}"


def test_model_rejects_a_page_below_one() -> None:
    with pytest.raises(ValidationError):
        FigureEvalItem(
            question="Which figure shows the pitch attitude time history during descent?",
            expected_pages=[0],
            figure_ref="Figure 5-5",
            kind="locate",
        )


def test_model_rejects_an_item_with_no_expected_page() -> None:
    with pytest.raises(ValidationError):
        FigureEvalItem(
            question="Which figure shows the pitch attitude time history during descent?",
            expected_pages=[],
            figure_ref="Figure 5-5",
            kind="locate",
        )


# ---------------------------------------------------------------------------
# The scorer (pure)
# ---------------------------------------------------------------------------


def _match(
    chunk_id: str,
    *,
    page_start: int | None = None,
    page_end: int | None = None,
    chunk_kind: str | None = None,
    summary: str | None = None,
    provenance: bool = True,
) -> dict[str, Any]:
    """A match shaped like a real ``ChunkMatch`` serialization.

    The provenance block is a *valid* ``ChunkProvenance`` serialization, not a convenient
    approximation: the real model requires both pages set or both ``None``, and ``regions``
    non-empty exactly when ``page_start`` is set. ``test_match_fixture_is_a_valid_chunk_provenance``
    validates it through the model so the fixture cannot drift into a shape search never returns.
    """
    metadata: dict[str, Any] = {"corpus_id": "nasa-apollo-11"}
    if chunk_kind is not None:
        metadata["chunk_kind"] = chunk_kind
    if summary is not None:
        metadata["figure"] = {"kind": "chart", "summary": summary}
    match: dict[str, Any] = {"chunk_id": chunk_id, "score": 0.9, "metadata": metadata}
    if provenance:
        regions = (
            []
            if page_start is None
            else [
                {"page": page, "left": 0.1, "top": 0.2, "right": 0.9, "bottom": 0.8}
                for page in range(page_start, (page_end if page_end is not None else page_start) + 1)
            ]
        )
        match["provenance"] = {
            "extraction": "docling",
            "page_start": page_start,
            "page_end": page_end,
            "regions": regions,
        }
    return match


def test_match_fixture_is_a_valid_chunk_provenance() -> None:
    """Every provenance shape the scorer tests against must be one the real model accepts."""
    for match in (
        _match("paged", page_start=72, page_end=72),
        _match("spanning", page_start=72, page_end=74),
        _match("direct", page_start=None, page_end=None),
    ):
        ChunkProvenance.model_validate(match["provenance"])
    assert "provenance" not in _match("none", provenance=False)


def test_page_span_of_a_match_with_no_provenance_is_empty() -> None:
    assert match_page_span(_match("c1", provenance=False)) == (None, None)
    assert not match_covers_page(_match("c1", provenance=False), 72)


def test_page_span_of_a_direct_extraction_chunk_is_empty() -> None:
    """Direct (non-Docling) extraction stores provenance with both pages ``None``."""
    match = _match("c1", page_start=None, page_end=None)
    assert match_page_span(match) == (None, None)
    assert not match_covers_page(match, 72)


def test_a_match_covers_every_page_in_its_span() -> None:
    match = _match("c1", page_start=54, page_end=56)
    assert [match_covers_page(match, p) for p in (53, 54, 55, 56, 57)] == [
        False,
        True,
        True,
        True,
        False,
    ]


def test_chunk_kind_and_summary_survive_a_match_with_no_metadata() -> None:
    bare: dict[str, Any] = {"chunk_id": "c1"}
    assert match_chunk_kind(bare) is None
    assert match_figure_summary(bare) is None
    assert match_figure_summary(_match("c2", chunk_kind="figure")) is None


def test_figure_summary_is_read_from_figure_metadata() -> None:
    assert match_figure_summary(_match("c1", summary="Pitch attitude")) == "Pitch attitude"


def test_a_hit_at_rank_four_counts_for_at_5_but_not_at_3() -> None:
    matches = [
        _match("c1", page_start=10, page_end=10),
        _match("c2", page_start=11, page_end=11),
        _match("c3", page_start=12, page_end=12),
        _match("c4", page_start=72, page_end=72),
        _match("c5", page_start=13, page_end=13),
    ]
    scored = score_matches(matches, [72])
    assert scored["page_hit_at_3"] is False
    assert scored["page_hit_at_5"] is True
    assert scored["figure_chunk_at_3"] is False


def test_a_figure_chunk_on_an_expected_page_scores_figure_chunk_at_3() -> None:
    matches = [
        _match("c1", page_start=54, page_end=54),
        _match("c2", page_start=72, page_end=72, chunk_kind="figure", summary="Pitch attitude"),
        _match("c3", page_start=13, page_end=13),
    ]
    scored = score_matches(matches, [72])
    assert scored["page_hit_at_3"] is True
    assert scored["figure_chunk_at_3"] is True


def test_a_figure_chunk_on_the_wrong_page_does_not_score() -> None:
    """Retrieving *some* figure is not retrieving *the* figure."""
    matches = [_match("c1", page_start=200, page_end=200, chunk_kind="figure", summary="Rock")]
    scored = score_matches(matches, [72])
    assert scored["page_hit_at_3"] is False
    assert scored["figure_chunk_at_3"] is False


def test_a_text_chunk_on_the_right_page_is_a_page_hit_but_not_a_figure_hit() -> None:
    matches = [_match("c1", page_start=72, page_end=72)]
    scored = score_matches(matches, [72])
    assert scored["page_hit_at_3"] is True
    assert scored["figure_chunk_at_3"] is False


def test_any_of_several_expected_pages_counts() -> None:
    """A figure continued across pages is found by any of the pages it is printed on."""
    matches = [_match("c1", page_start=27, page_end=27)]
    assert score_matches(matches, [20, 21, 25, 27, 28])["page_hit_at_3"] is True


def test_scoring_an_empty_result_set_is_all_misses() -> None:
    scored = score_matches([], [72])
    assert scored == {
        "page_hit_at_3": False,
        "page_hit_at_5": False,
        "precise_page_hit_at_3": False,
        "figure_chunk_at_3": False,
        "top": [],
    }


def test_a_wide_span_chunk_is_a_page_hit_but_not_a_precise_one() -> None:
    """A textless run of figure pages merges into one chunk that "covers" a dozen pages.

    Counting that as having located the figure would score the pre-figure index as already
    good at exactly the questions figure chunks are supposed to fix.
    """
    matches = [_match("blob", page_start=73, page_end=84)]
    scored = score_matches(matches, [76])
    assert scored["page_hit_at_3"] is True
    assert scored["precise_page_hit_at_3"] is False


def test_a_chunk_at_the_span_limit_still_counts_as_precise() -> None:
    assert match_is_precise(_match("c1", page_start=72, page_end=74)) is True
    assert match_is_precise(_match("c2", page_start=72, page_end=75)) is False
    assert match_span_pages(_match("c3", page_start=72, page_end=74)) == 3
    assert match_span_pages(_match("c4", provenance=False)) is None
    assert match_is_precise(_match("c5", provenance=False)) is False


def test_a_narrow_chunk_on_the_expected_page_is_a_precise_hit() -> None:
    scored = score_matches([_match("c1", page_start=72, page_end=72)], [72])
    assert scored["precise_page_hit_at_3"] is True


def test_precise_hit_ignores_a_narrow_chunk_on_the_wrong_page() -> None:
    scored = score_matches([_match("c1", page_start=10, page_end=10)], [72])
    assert scored["precise_page_hit_at_3"] is False


def test_top_window_records_every_rank_with_its_pages_and_kind() -> None:
    matches = [
        _match("c1", page_start=72, page_end=73, chunk_kind="figure", summary="Pitch"),
        _match("c2", provenance=False),
    ]
    rows = score_matches(matches, [72])["top"]
    assert [r["rank"] for r in rows] == [1, 2]
    assert rows[0] == {
        "rank": 1,
        "chunk_id": "c1",
        "page_start": 72,
        "page_end": 73,
        "span_pages": 2,
        "chunk_kind": "figure",
        "on_expected_page": True,
    }
    assert rows[1]["page_start"] is None and rows[1]["on_expected_page"] is False


def test_summarize_reports_rates_and_the_raw_counts_behind_them() -> None:
    per_item = [
        {"group": "locate", "page_hit_at_3": True, "page_hit_at_5": True,
         "precise_page_hit_at_3": True, "figure_chunk_at_3": True},
        {"group": "locate", "page_hit_at_3": False, "page_hit_at_5": True,
         "precise_page_hit_at_3": False, "figure_chunk_at_3": False},
        {"group": "prose", "page_hit_at_3": True, "page_hit_at_5": True,
         "precise_page_hit_at_3": True, "figure_chunk_at_3": False},
    ]
    summary = summarize(per_item)
    assert summary["n"] == 3
    assert summary["page_hit_at_3_hits"] == 2
    assert summary["page_hit_at_5"] == 1.0
    assert summary["by_group"]["locate"] == {
        "n": 2,
        "page_hit_at_3": 0.5,
        "page_hit_at_3_hits": 1,
        "page_hit_at_5": 1.0,
        "page_hit_at_5_hits": 2,
        "precise_page_hit_at_3": 0.5,
        "precise_page_hit_at_3_hits": 1,
        "figure_chunk_at_3": 0.5,
        "figure_chunk_at_3_hits": 1,
    }
    assert summary["by_group"]["prose"]["n"] == 1


def test_summarize_of_no_items_does_not_divide_by_zero() -> None:
    assert summarize([])["page_hit_at_3"] == 0.0


def test_top_k_below_five_is_rejected() -> None:
    """``page_hit@5`` reads rank 5; a smaller window would silently make it equal ``page_hit@3``."""
    for good in ("5", "10", "20"):
        assert _top_k(good) == int(good)
    for bad in ("4", "3", "1", "0"):
        with pytest.raises(argparse.ArgumentTypeError):
            _top_k(bad)
