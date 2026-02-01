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

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

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

# Internal stage metrics (low-cardinality via stage/leg labels).
#
# IMPORTANT:
# - Do NOT add corpus_id/repo_id labels.
# - Keep label values stable (dashboards depend on them).
SEARCH_STAGE_LATENCY_SECONDS = Histogram(
    "tribrid_search_stage_latency_seconds",
    "Latency of internal search stages in seconds (low-cardinality by stage).",
    ["stage"],
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
        5.0,
        10.0,
    ),
)

SEARCH_STAGE_ERRORS_TOTAL = Counter(
    "tribrid_search_stage_errors_total",
    "Total number of internal search stage errors (low-cardinality by stage).",
    ["stage"],
)

SEARCH_LEG_RESULTS_COUNT = Histogram(
    "tribrid_search_leg_results_count",
    "Number of results produced per retrieval leg.",
    ["leg"],
    buckets=(0, 1, 2, 5, 10, 20, 50, 100, 200),
)

SEARCH_RESULTS_FINAL_COUNT = Histogram(
    "tribrid_search_results_final_count",
    "Number of results returned after fusion (final_k).",
    buckets=(0, 1, 2, 5, 10, 20, 50, 100, 200),
)

SEARCH_GRAPH_HYDRATED_CHUNKS_COUNT = Histogram(
    "tribrid_search_graph_hydrated_chunks_count",
    "Number of hydrated chunks produced by the graph leg.",
    buckets=(0, 1, 2, 5, 10, 20, 50, 100, 200),
)

# --------------------------------------------------------------------------------------
# Indexing metrics
# --------------------------------------------------------------------------------------

INDEX_RUNS_TOTAL = Counter(
    "tribrid_index_runs_total",
    "Total number of indexing runs started.",
)

INDEX_ERRORS_TOTAL = Counter(
    "tribrid_index_errors_total",
    "Total number of indexing runs that ended in error.",
)

INDEX_DURATION_SECONDS = Histogram(
    "tribrid_index_duration_seconds",
    "End-to-end indexing duration in seconds.",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600),
)

INDEX_STAGE_LATENCY_SECONDS = Histogram(
    "tribrid_index_stage_latency_seconds",
    "Latency of internal indexing stages in seconds (low-cardinality by stage).",
    ["stage"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

INDEX_STAGE_ERRORS_TOTAL = Counter(
    "tribrid_index_stage_errors_total",
    "Total number of internal indexing stage errors (low-cardinality by stage).",
    ["stage"],
)

INDEX_FILES_PROCESSED_TOTAL = Counter(
    "tribrid_index_files_processed_total",
    "Total number of files successfully processed during indexing (read + chunked).",
)

INDEX_CHUNKS_CREATED_TOTAL = Counter(
    "tribrid_index_chunks_created_total",
    "Total number of chunks created during indexing.",
)

INDEX_TOKENS_TOTAL = Counter(
    "tribrid_index_tokens_total",
    "Total number of chunk tokens processed during indexing.",
)

# --------------------------------------------------------------------------------------
# Process-level gauges (for Grafana stat panels)
# --------------------------------------------------------------------------------------
#
# These are intentionally low-cardinality and do NOT include repo_id/corpus_id labels.
# They represent the *most recently observed* totals (typically from the latest indexing run).
CHUNKS_INDEXED_CURRENT = Gauge(
    "tribrid_chunks_indexed_current",
    "Current total number of indexed chunks (process-level; updated on indexing runs).",
)

GRAPH_ENTITIES_CURRENT = Gauge(
    "tribrid_graph_entities_current",
    "Current total number of graph entities (process-level; updated on indexing runs).",
)

GRAPH_RELATIONSHIPS_CURRENT = Gauge(
    "tribrid_graph_relationships_current",
    "Current total number of graph relationships (process-level; updated on indexing runs).",
)


# --------------------------------------------------------------------------------------
# Pre-initialize labelled metrics
# --------------------------------------------------------------------------------------
#
# Prometheus client only exports labelled time series after the corresponding labelset
# is created (e.g., via `.labels(stage="...")`). For dashboards/tests that scrape
# immediately on startup, we pre-create the expected low-cardinality labelsets here.

_SEARCH_STAGES = (
    "embed_query",
    "postgres_vector_search",
    "postgres_sparse_search",
    "neo4j_connect",
    "neo4j_chunk_vector_search",
    "neo4j_expand_chunks_via_entities",
    "neo4j_entity_chunk_search",
    "postgres_get_chunks",
    "fusion_rrf",
    "normalize_scores",
    "fusion_weighted",
    # Error aggregation stages (still low-cardinality)
    "vector_leg",
    "sparse_leg",
    "graph_leg",
)

_SEARCH_LEGS = ("vector", "sparse", "graph")

_INDEX_STAGES = (
    "collect_file_paths",
    "file_read",
    "chunk",
    "embed_chunks",
    "postgres_upsert_embeddings",
    "postgres_upsert_fts",
    "neo4j_upsert_document_chunks",
    "neo4j_upsert_semantic_entities",
    "neo4j_upsert_semantic_relationships",
    "neo4j_link_entities_to_chunks",
    "semantic_kg",
    "graph_build",
    "neo4j_rebuild_entity_chunk_links",
)

for _stage in _SEARCH_STAGES:
    SEARCH_STAGE_LATENCY_SECONDS.labels(stage=_stage)
    SEARCH_STAGE_ERRORS_TOTAL.labels(stage=_stage)

for _leg in _SEARCH_LEGS:
    SEARCH_LEG_RESULTS_COUNT.labels(leg=_leg)

for _stage in _INDEX_STAGES:
    INDEX_STAGE_LATENCY_SECONDS.labels(stage=_stage)
    INDEX_STAGE_ERRORS_TOTAL.labels(stage=_stage)


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
