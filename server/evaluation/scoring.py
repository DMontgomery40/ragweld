"""Chunk-level retrieval scoring: the one scorer behind every eval path.

POST /eval/run, the SSE eval stream, the ad-hoc /eval/test and the synthetic quality gate
all score through ``score_entry`` and aggregate through ``aggregate_entry_scores``.

An entry's expectations are its expected paths, each optionally refined by one page or line
span (``EvalExpectedLocation``). A retrieved chunk satisfies an expectation when it comes from
the expected file and, when the expectation has a span, the chunk's own page span (PDF
provenance) or line span overlaps it. Ranks are chunk ranks in fusion order, never
de-duplicated file ranks, so a single-document corpus can still rank the right pages low.

An entry whose expectations cannot discriminate is ``uninformative``: it has no expectations,
or its file-only expectations cover every indexed document, so any chunk the corpus could
return would count as a hit. Such entries are excluded from the headline metrics instead of
scoring a vacuous 1.0.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from server.evaluation.path_match import normalize_path, path_matches
from server.models.tribrid_config_model import ChunkMatch, EvalDocMatch, EvalExpectedLocation

MAP_AT_K = 5

# When one chunk relates to several expectations in different ways, the strongest wins.
_MATCH_PRIORITY: dict[EvalDocMatch, int] = {
    "location": 4,
    "file": 3,
    "no_page_provenance": 2,
    "outside_location": 1,
    "none": 0,
}


@dataclass(frozen=True)
class Expectation:
    """One expected path, optionally narrowed to a page/line span."""

    path: str
    location: EvalExpectedLocation | None


@dataclass(frozen=True)
class EvalCutoffs:
    """Rank cutoffs for one scoring pass (from ``cfg.evaluation`` plus the run's final-k)."""

    final_k: int
    recall_at_5: int
    recall_at_10: int
    recall_at_20: int
    precision_at_5: int
    ndcg_at_10: int

    @property
    def retrieval_k(self) -> int:
        """How many chunks retrieval must return for every cutoff to be computable."""
        return max(
            self.final_k,
            self.recall_at_5,
            self.recall_at_10,
            self.recall_at_20,
            self.precision_at_5,
            self.ndcg_at_10,
            MAP_AT_K,
        )


@dataclass(frozen=True)
class EntryScore:
    """Per-entry scores; ``matches`` has one classification per retrieved chunk, in rank order."""

    uninformative: bool
    matches: tuple[EvalDocMatch, ...]
    reciprocal_rank: float
    top1_hit: bool
    topk_hit: bool
    recall: float
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    precision_at_5: float
    ndcg_at_10: float
    average_precision_at_5: float


@dataclass(frozen=True)
class HeadlineMetrics:
    """Run-level means over the scored (informative) entries only."""

    total: int
    uninformative: int
    top1_hits: int
    topk_hits: int
    top1_accuracy: float
    topk_accuracy: float
    mrr: float
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    precision_at_5: float
    ndcg_at_10: float
    map_at_5: float | None

    @property
    def scored(self) -> int:
        return self.total - self.uninformative


def build_expectations(
    expected_paths: Sequence[str], expected_locations: Sequence[EvalExpectedLocation]
) -> list[Expectation]:
    """Pair each expected path with its location (the boundary models guarantee at most one per path)."""
    by_path = {normalize_path(location.path): location for location in expected_locations}
    out: list[Expectation] = []
    seen: set[str] = set()
    for raw in expected_paths:
        key = normalize_path(str(raw or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(Expectation(path=str(raw).strip(), location=by_path.get(key)))
    return out


def _chunk_span(chunk: ChunkMatch, location: EvalExpectedLocation) -> tuple[int, int] | None:
    if location.unit == "page":
        provenance = chunk.provenance
        if provenance is None or provenance.page_start is None or provenance.page_end is None:
            return None
        return int(provenance.page_start), int(provenance.page_end)
    start = int(chunk.start_line)
    return start, max(start, int(chunk.end_line))


def classify_chunk(chunk: ChunkMatch, expectations: Sequence[Expectation]) -> tuple[EvalDocMatch, frozenset[int]]:
    """How one retrieved chunk relates to the expectations, plus the indices it satisfies."""
    best: EvalDocMatch = "none"
    satisfied: set[int] = set()
    for index, expectation in enumerate(expectations):
        if not path_matches(expectation.path, chunk.file_path):
            continue
        kind: EvalDocMatch
        if expectation.location is None:
            kind = "file"
            satisfied.add(index)
        else:
            span = _chunk_span(chunk, expectation.location)
            if span is None:
                kind = "no_page_provenance"
            elif span[0] <= expectation.location.end and span[1] >= expectation.location.start:
                kind = "location"
                satisfied.add(index)
            else:
                kind = "outside_location"
        if _MATCH_PRIORITY[kind] > _MATCH_PRIORITY[best]:
            best = kind
    return best, frozenset(satisfied)


def is_uninformative(expectations: Sequence[Expectation], corpus_paths: Sequence[str]) -> bool:
    """True when no retrieval outcome could fail the entry.

    With no expectations there is nothing to hit. With file-only expectations that cover every
    indexed document (e.g. the only file of a single-document corpus), every chunk is a hit.
    """
    if not expectations:
        return True
    file_only = [expectation.path for expectation in expectations if expectation.location is None]
    documents = [path for path in corpus_paths if str(path or "").strip()]
    if not file_only or not documents:
        return False
    return all(any(path_matches(expected, document) for expected in file_only) for document in documents)


def score_entry(
    expectations: Sequence[Expectation],
    chunks: Sequence[ChunkMatch],
    *,
    cutoffs: EvalCutoffs,
    corpus_paths: Sequence[str],
) -> EntryScore:
    """Score one entry against its ranked retrieved chunks."""
    classified = [classify_chunk(chunk, expectations) for chunk in chunks]
    kinds = tuple(kind for kind, _ in classified)
    hits = [bool(satisfied) for _, satisfied in classified]

    # First chunk rank (1-based) that satisfies each expectation, and the ranks where a
    # not-yet-satisfied expectation is first satisfied ("novel" hits). Gains are binary per
    # novel rank, so nDCG and AP stay within [0, 1] however many chunks of one file rank.
    first_rank: dict[int, int] = {}
    novel_ranks: list[int] = []
    for rank, (_, satisfied) in enumerate(classified, start=1):
        fresh = [index for index in satisfied if index not in first_rank]
        for index in fresh:
            first_rank[index] = rank
        if fresh:
            novel_ranks.append(rank)

    expected_count = len(expectations)

    def recall_at(k: int) -> float:
        if expected_count == 0 or k <= 0:
            return 0.0
        return sum(1 for rank in first_rank.values() if rank <= k) / float(expected_count)

    def precision_at(k: int) -> float:
        if k <= 0:
            return 0.0
        return sum(1 for hit in hits[:k] if hit) / float(k)

    def ndcg_at(k: int) -> float:
        ideal_hits = min(expected_count, k)
        if k <= 0 or ideal_hits <= 0:
            return 0.0
        dcg = sum(1.0 / math.log2(rank + 1) for rank in novel_ranks if rank <= k)
        idcg = sum(1.0 / math.log2(position + 2) for position in range(ideal_hits))
        return float(dcg / idcg)

    def average_precision_at(k: int) -> float:
        denominator = min(expected_count, k)
        if denominator <= 0:
            return 0.0
        total = 0.0
        for found, rank in enumerate((rank for rank in novel_ranks if rank <= k), start=1):
            total += found / float(rank)
        return total / float(denominator)

    first_hit = next((rank for rank, hit in enumerate(hits, start=1) if hit), None)
    final_k = max(1, cutoffs.final_k)
    return EntryScore(
        uninformative=is_uninformative(expectations, corpus_paths),
        matches=kinds,
        reciprocal_rank=1.0 / float(first_hit) if first_hit is not None else 0.0,
        top1_hit=bool(hits[:1] and hits[0]),
        topk_hit=any(hits[:final_k]),
        recall=recall_at(len(chunks)),
        recall_at_5=recall_at(cutoffs.recall_at_5),
        recall_at_10=recall_at(cutoffs.recall_at_10),
        recall_at_20=recall_at(cutoffs.recall_at_20),
        precision_at_5=precision_at(cutoffs.precision_at_5),
        ndcg_at_10=ndcg_at(cutoffs.ndcg_at_10),
        average_precision_at_5=average_precision_at(MAP_AT_K),
    )


def aggregate_entry_scores(scores: Sequence[EntryScore]) -> HeadlineMetrics:
    """Headline metrics over the informative entries; uninformative ones are only counted."""
    scored = [score for score in scores if not score.uninformative]
    n = len(scored)

    def mean(values: list[float]) -> float:
        return float(sum(values) / len(values)) if values else 0.0

    top1_hits = sum(1 for score in scored if score.top1_hit)
    topk_hits = sum(1 for score in scored if score.topk_hit)
    return HeadlineMetrics(
        total=len(scores),
        uninformative=len(scores) - n,
        top1_hits=top1_hits,
        topk_hits=topk_hits,
        top1_accuracy=float(top1_hits / n) if n else 0.0,
        topk_accuracy=float(topk_hits / n) if n else 0.0,
        mrr=mean([score.reciprocal_rank for score in scored]),
        recall_at_5=mean([score.recall_at_5 for score in scored]),
        recall_at_10=mean([score.recall_at_10 for score in scored]),
        recall_at_20=mean([score.recall_at_20 for score in scored]),
        precision_at_5=mean([score.precision_at_5 for score in scored]),
        ndcg_at_10=mean([score.ndcg_at_10 for score in scored]),
        map_at_5=mean([score.average_precision_at_5 for score in scored]) if n else None,
    )
