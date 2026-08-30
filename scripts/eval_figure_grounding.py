#!/usr/bin/env python
"""Score page-grounded retrieval for a figure eval dataset against a live Ragweld deployment.

The eval lane scores by ``expected_paths``, which cannot separate anything on a single-PDF
corpus. This script asks the question figure chunks actually change: does searching for a
figure question bring back the *page* the figure is printed on, and does a figure chunk come
back for it?

Every call is real HTTP against ``POST /api/search``; there are no mocks and no fixtures.
Retrieval caching is bypassed by default so a before/after comparison cannot replay a
pre-index answer.

    python scripts/eval_figure_grounding.py \
        --dataset data/eval_datasets/nasa-apollo-11-figures.json \
        --out /tmp/eval_before.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.models.eval_figures import FigureEvalDataset, FigureEvalItem  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:58012/api"
DEFAULT_DATASET = REPO_ROOT / "data" / "eval_datasets" / "nasa-apollo-11-figures.json"

PROSE_TAG = "prose"

MAX_PRECISE_SPAN_PAGES = 3
"""A chunk citing more pages than this locates nothing in particular.

On a scanned report, pages that are wholly figure carry almost no extractable text, so the
chunker merges across them and a single chunk can span a dozen pages. Such a chunk "covers"
any figure page in that run by accident, which would let ``page_hit`` score a blob as a hit.
``precise_page_hit_at_3`` re-asks the question with those blobs excluded.
"""


# ---------------------------------------------------------------------------
# Scoring (pure: no I/O, so it is unit-testable on hand-built match dicts)
# ---------------------------------------------------------------------------


def match_page_span(match: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """The ``(page_start, page_end)`` a match cites, or ``(None, None)``.

    Chunks extracted directly (not through Docling) carry provenance with no pages, and
    chunks indexed before provenance capture carry no provenance at all. Both are "no page",
    never an error.
    """
    provenance = match.get("provenance")
    if not isinstance(provenance, Mapping):
        return (None, None)
    raw_start = provenance.get("page_start")
    raw_end = provenance.get("page_end")
    start = raw_start if isinstance(raw_start, int) else None
    end = raw_end if isinstance(raw_end, int) else None
    if start is None or end is None:
        return (None, None)
    return (start, end)


def match_covers_page(match: Mapping[str, Any], page: int) -> bool:
    """Whether the match's cited page span contains ``page``."""
    start, end = match_page_span(match)
    if start is None or end is None:
        return False
    return start <= page <= end


def match_chunk_kind(match: Mapping[str, Any]) -> str | None:
    """``metadata.chunk_kind`` when present; ``None`` for a match with no metadata."""
    metadata = match.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    kind = metadata.get("chunk_kind")
    return kind if isinstance(kind, str) else None


def match_figure_summary(match: Mapping[str, Any]) -> str | None:
    """``metadata.figure.summary`` when the match is a described figure chunk."""
    metadata = match.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    figure = metadata.get("figure")
    if not isinstance(figure, Mapping):
        return None
    summary = figure.get("summary")
    return summary if isinstance(summary, str) else None


def match_span_pages(match: Mapping[str, Any]) -> int | None:
    """How many pages the match cites, or ``None`` when it cites no page."""
    start, end = match_page_span(match)
    if start is None or end is None:
        return None
    return end - start + 1


def match_is_precise(match: Mapping[str, Any]) -> bool:
    """Whether the match cites few enough pages to have located something."""
    span = match_span_pages(match)
    return span is not None and span <= MAX_PRECISE_SPAN_PAGES


def _hits_expected_page(matches: Sequence[Mapping[str, Any]], expected_pages: Sequence[int]) -> bool:
    return any(match_covers_page(m, p) for m in matches for p in expected_pages)


def score_matches(
    matches: Sequence[Mapping[str, Any]], expected_pages: Sequence[int]
) -> dict[str, Any]:
    """Score one question's ranked matches against the pages that carry its answer.

    ``page_hit_at_3``/``page_hit_at_5``: an expected page appears in the top 3/top 5.
    ``precise_page_hit_at_3``: the same, counting only chunks narrow enough to have located
    something (see ``MAX_PRECISE_SPAN_PAGES``).
    ``figure_chunk_at_3``: a top-3 match is a figure chunk *and* sits on an expected page.
    ``top``: the full ranked window, so a hit can be read back as real retrieval or as a
    neighbour-expanded chunk rather than being taken on trust.
    """
    top3 = list(matches[:3])
    top5 = list(matches[:5])
    figure_at_3 = any(
        match_chunk_kind(m) == "figure" and any(match_covers_page(m, p) for p in expected_pages)
        for m in top3
    )
    rows: list[dict[str, Any]] = []
    for rank, match in enumerate(top5, start=1):
        start, end = match_page_span(match)
        rows.append(
            {
                "rank": rank,
                "chunk_id": str(match.get("chunk_id") or ""),
                "page_start": start,
                "page_end": end,
                "span_pages": match_span_pages(match),
                "chunk_kind": match_chunk_kind(match),
                "on_expected_page": any(match_covers_page(match, p) for p in expected_pages),
            }
        )
    return {
        "page_hit_at_3": _hits_expected_page(top3, expected_pages),
        "page_hit_at_5": _hits_expected_page(top5, expected_pages),
        "precise_page_hit_at_3": _hits_expected_page(
            [m for m in top3 if match_is_precise(m)], expected_pages
        ),
        "figure_chunk_at_3": figure_at_3,
        "top": rows,
    }


def item_group(item: FigureEvalItem) -> str:
    """The disjoint reporting group: ``prose`` control items never dilute ``locate``."""
    return PROSE_TAG if PROSE_TAG in item.tags else str(item.kind)


def summarize(per_item: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Overall and per-group rates, reported with the raw counts behind them."""

    def rates(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        out: dict[str, Any] = {"n": n}
        for metric in (
            "page_hit_at_3",
            "page_hit_at_5",
            "precise_page_hit_at_3",
            "figure_chunk_at_3",
        ):
            hits = sum(1 for r in rows if r.get(metric))
            out[metric] = round(hits / n, 4) if n else 0.0
            out[f"{metric}_hits"] = hits
        return out

    groups = sorted({str(r.get("group") or "") for r in per_item})
    return {
        **rates(per_item),
        "by_group": {g: rates([r for r in per_item if r.get("group") == g]) for g in groups},
    }


# ---------------------------------------------------------------------------
# Live search
# ---------------------------------------------------------------------------


def search(
    *, base_url: str, corpus_id: str, query: str, top_k: int, cache_mode: str, timeout: float
) -> list[dict[str, Any]]:
    """One real ``POST /api/search``. Any transport or HTTP error is fatal: a silent
    empty result would score as a miss and quietly understate the index."""
    payload = json.dumps(
        {"query": query, "repo_id": corpus_id, "top_k": top_k, "cache_mode": cache_mode}
    ).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:  # surface the server's own message
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"search failed ({exc.code}) for {query!r}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"search unreachable at {base_url}: {exc.reason}") from exc
    matches = body.get("matches")
    if not isinstance(matches, list):
        # Treating an unexpected body as "no matches" would score every item a miss and
        # report a plausible-looking zero instead of a broken response contract.
        raise SystemExit(
            f"search response for {query!r} has no 'matches' list "
            f"(got {type(matches).__name__}; body keys: {sorted(body)})"
        )
    return list(matches)


def run(
    *, dataset: FigureEvalDataset, base_url: str, top_k: int, cache_mode: str, timeout: float
) -> dict[str, Any]:
    per_item: list[dict[str, Any]] = []
    for index, item in enumerate(dataset.items, start=1):
        matches = search(
            base_url=base_url,
            corpus_id=dataset.corpus_id,
            query=item.question,
            top_k=top_k,
            cache_mode=cache_mode,
            timeout=timeout,
        )
        scored = score_matches(matches, item.expected_pages)
        summaries = [s for s in (match_figure_summary(m) for m in matches[:3]) if s]
        per_item.append(
            {
                "question": item.question,
                "figure_ref": item.figure_ref,
                "kind": str(item.kind),
                "group": item_group(item),
                "tags": list(item.tags),
                "expected_pages": list(item.expected_pages),
                "matches_returned": len(matches),
                **scored,
                "figure_summaries_at_3": [s[:200] for s in summaries],
            }
        )
        flag = "hit" if scored["page_hit_at_3"] else "   "
        print(
            f"[{index:2d}/{len(dataset.items)}] {flag} {item_group(item):7s} "
            f"pages={item.expected_pages} {item.question[:70]}",
            file=sys.stderr,
        )
    return {
        "corpus_id": dataset.corpus_id,
        "base_url": base_url,
        "top_k": top_k,
        "cache_mode": cache_mode,
        **summarize(per_item),
        "per_item": per_item,
    }


def _top_k(raw: str) -> int:
    """``--top-k`` must cover the deepest rank any metric reads."""
    value = int(raw)
    if value < 5:
        raise argparse.ArgumentTypeError(
            f"--top-k must be >= 5 so page_hit@5 is a real measurement, not a copy of page_hit@3 (got {value})"
        )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--top-k",
        type=_top_k,
        default=5,
        help="matches to request; must be >= 5 or page_hit@5 silently collapses onto page_hit@3",
    )
    parser.add_argument(
        "--cache-mode",
        default="bypass",
        choices=("default", "bypass", "refresh"),
        help="bypass (the default) keeps a before/after comparison from replaying cached results",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    dataset = FigureEvalDataset.model_validate_json(args.dataset.read_text(encoding="utf-8"))
    result = run(
        dataset=dataset,
        base_url=args.base_url,
        top_k=int(args.top_k),
        cache_mode=str(args.cache_mode),
        timeout=float(args.timeout),
    )
    text = json.dumps(result, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
