"""Prometheus metrics collection.

This module defines low-cardinality application metrics and helpers to expose them
via a Prometheus scrape endpoint.

Design goals:
- **No high-cardinality labels** (no corpus_id, no file_path, no query strings)
- **Use seconds** for latency histograms (Prometheus best practice)
- Keep metric names stable (dashboards depend on them)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# --------------------------------------------------------------------------------------
# Core request/search metrics
# --------------------------------------------------------------------------------------

# Search endpoint request count.
SEARCH_REQUESTS_TOTAL = Counter(
    "tribrid_search_requests_total",
    "Total number of /api/search requests handled.",
)

# Search endpoint error count (internal errors; HTTP validation errors are not counted here).
SEARCH_ERRORS_TOTAL = Counter(
    "tribrid_search_errors_total",
    "Total number of /api/search internal errors.",
)

# End-to-end search latency (seconds). Use histogram_quantile on *_bucket.
SEARCH_LATENCY_SECONDS = Histogram(
    "tribrid_search_latency_seconds",
    "End-to-end /api/search latency in seconds.",
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)

# Retrieval leg latencies (seconds).
VECTOR_LEG_LATENCY_SECONDS = Histogram(
    "tribrid_vector_leg_latency_seconds",
    "Vector retrieval leg latency in seconds (embed + vector search).",
    buckets=(
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
    ),
)

SPARSE_LEG_LATENCY_SECONDS = Histogram(
    "tribrid_sparse_leg_latency_seconds",
    "Sparse retrieval leg latency in seconds (FTS/BM25).",
    buckets=(
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
    ),
)

GRAPH_LEG_LATENCY_SECONDS = Histogram(
    "tribrid_graph_leg_latency_seconds",
    "Graph retrieval leg latency in seconds (Neo4j query + hydration).",
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)


@contextmanager
def timed(hist: Histogram) -> Iterator[None]:
    """Time a code block and observe seconds in the provided histogram."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        hist.observe(time.perf_counter() - t0)


def render_latest() -> tuple[bytes, str]:
    """Return (body, content_type) for a Prometheus scrape response."""
    body = generate_latest()
    return body, CONTENT_TYPE_LATEST
