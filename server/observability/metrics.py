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
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily

# --------------------------------------------------------------------------------------
# Core request/search metrics
# --------------------------------------------------------------------------------------

# Tri-brid retrieval request count, measured on the shared fusion lane so
# /api/search, chat retrieval, benchmark grounding and MCP search all count.
SEARCH_REQUESTS_TOTAL = Counter(
    "tribrid_search_requests_total",
    "Total number of tri-brid retrieval requests (search, chat, benchmark, MCP).",
)

# Retrieval error count (exceptions raised by the fusion lane; HTTP validation errors are not counted here).
SEARCH_ERRORS_TOTAL = Counter(
    "tribrid_search_errors_total",
    "Total number of tri-brid retrieval failures (search, chat, benchmark, MCP).",
)

# End-to-end retrieval latency (seconds) on the fusion lane. Use histogram_quantile on *_bucket.
SEARCH_LATENCY_SECONDS = Histogram(
    "tribrid_search_latency_seconds",
    "End-to-end tri-brid retrieval latency in seconds (search, chat, benchmark, MCP).",
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
# Semantic cache metrics
# --------------------------------------------------------------------------------------

SEMANTIC_CACHE_LOOKUPS_TOTAL = Counter(
    "tribrid_semantic_cache_lookups_total",
    "Total semantic cache lookups by endpoint and outcome.",
    ["endpoint", "outcome"],
)

SEMANTIC_CACHE_LOOKUP_LATENCY_SECONDS = Histogram(
    "tribrid_semantic_cache_lookup_latency_seconds",
    "Semantic cache lookup latency by endpoint.",
    ["endpoint"],
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

SEMANTIC_CACHE_WRITES_TOTAL = Counter(
    "tribrid_semantic_cache_writes_total",
    "Total semantic cache writes by endpoint and outcome.",
    ["endpoint", "outcome"],
)

SEMANTIC_CACHE_SEMANTIC_SIMILARITY = Histogram(
    "tribrid_semantic_cache_semantic_similarity",
    "Similarity score distribution for semantic cache hits.",
    ["endpoint"],
    buckets=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.99, 1.0),
)

# --------------------------------------------------------------------------------------
# Reranker metrics (inference-time)
# --------------------------------------------------------------------------------------
#
# NOTE:
# - Keep labels low-cardinality (mode/reason only).
# - Do NOT label by corpus_id, query, model name, or file path.
RERANKER_REQUESTS_TOTAL = Counter(
    "tribrid_reranker_requests_total",
    "Total number of reranker attempts (mode != none).",
    ["mode"],
)

RERANKER_CANDIDATES_TOTAL = Counter(
    "tribrid_reranker_candidates_total",
    "Total number of candidates sent through reranking (top_n summed).",
    ["mode"],
)

RERANKER_SKIPPED_TOTAL = Counter(
    "tribrid_reranker_skipped_total",
    "Total number of reranker skips due to missing prerequisites (mode != none).",
    ["mode", "reason"],
)

RERANKER_ERRORS_TOTAL = Counter(
    "tribrid_reranker_errors_total",
    "Total number of reranker failures (exceptions).",
    ["mode"],
)

RERANKER_LATENCY_SECONDS = Histogram(
    "tribrid_reranker_latency_seconds",
    "Reranker latency in seconds (local/learning/cloud).",
    ["mode"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

RERANKER_TRAIN_RUNS_TOTAL = Counter(
    "tribrid_reranker_train_runs_total",
    "Total number of reranker training runs by outcome.",
    ["outcome"],
)

RERANKER_TRAIN_ACTIVE_RUNS = Gauge(
    "tribrid_reranker_train_active_runs",
    "Number of reranker training runs currently active in this process.",
)

RERANKER_TRAIN_STAGE_LATENCY_SECONDS = Histogram(
    "tribrid_reranker_train_stage_latency_seconds",
    "Latency of reranker training/eval/mine stages in seconds.",
    ["stage"],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

RERANKER_TRAIN_STAGE_ERRORS_TOTAL = Counter(
    "tribrid_reranker_train_stage_errors_total",
    "Total number of reranker training/eval/mine stage errors.",
    ["stage"],
)

RERANKER_TRAIN_EVENTS_TOTAL = Counter(
    "tribrid_reranker_train_events_total",
    "Total number of reranker training event-stream records by type.",
    ["type"],
)

RERANKER_TRAIN_STEP_TIME_SECONDS = Histogram(
    "tribrid_reranker_train_step_time_seconds",
    "Effective training step time in seconds.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

RERANKER_TRAIN_LOSS = Histogram(
    "tribrid_reranker_train_loss",
    "Distribution of reranker training loss values emitted during training.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
)

RERANKER_TRAIN_GRAD_NORM = Histogram(
    "tribrid_reranker_train_grad_norm",
    "Distribution of reranker training gradient norms.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
)

RERANKER_TRAIN_SAMPLES_TOTAL = Counter(
    "tribrid_reranker_train_samples_total",
    "Total number of training samples processed by the reranker trainer.",
)

RERANKER_TRAIN_PROGRESS_PERCENT = Gauge(
    "tribrid_reranker_train_progress_percent",
    "Best-effort latest reranker training progress percent for the most recently updated run.",
)

RERANKER_TRAIN_LAST_STEP = Gauge(
    "tribrid_reranker_train_last_step",
    "Latest reranker training step observed in the event stream.",
)

RERANKER_TRAIN_LAST_EPOCH = Gauge(
    "tribrid_reranker_train_last_epoch",
    "Latest reranker training epoch fraction observed in the event stream.",
)

RERANKER_TRAIN_LAST_METRIC = Gauge(
    "tribrid_reranker_train_last_metric",
    "Latest reranker metric values by metric/phase for the most recent run activity.",
    ["metric", "phase"],
)

RERANKER_TRIPLETS_TOTAL = Counter(
    "tribrid_reranker_triplets_total",
    "Total number of reranker triplets observed or generated by stage.",
    ["kind"],
)

RERANKER_TRIPLET_SKIPS_TOTAL = Counter(
    "tribrid_reranker_triplet_skips_total",
    "Total number of triplets skipped during materialization by reason.",
    ["reason"],
)

RERANKER_MINE_RUNS_TOTAL = Counter(
    "tribrid_reranker_mine_runs_total",
    "Total number of triplet mining runs by outcome.",
    ["outcome"],
)

RERANKER_MINE_LATENCY_SECONDS = Histogram(
    "tribrid_reranker_mine_latency_seconds",
    "Triplet mining latency in seconds.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

RERANKER_EVAL_RUNS_TOTAL = Counter(
    "tribrid_reranker_eval_runs_total",
    "Total number of reranker evaluation runs by phase and outcome.",
    ["phase", "outcome"],
)

RERANKER_EVAL_LATENCY_SECONDS = Histogram(
    "tribrid_reranker_eval_latency_seconds",
    "Reranker evaluation latency in seconds by phase.",
    ["phase"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

RERANKER_PROMOTIONS_TOTAL = Counter(
    "tribrid_reranker_promotions_total",
    "Total number of reranker promotion attempts by outcome.",
    ["outcome"],
)

RERANKER_PROMOTION_LATENCY_SECONDS = Histogram(
    "tribrid_reranker_promotion_latency_seconds",
    "Reranker promotion latency in seconds.",
    buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

RERANKER_DIAGNOSTIC_EVENTS_TOTAL = Counter(
    "tribrid_reranker_diagnostic_events_total",
    "Total number of structured reranker diagnostic log records by level and event.",
    ["level", "event"],
)

# --------------------------------------------------------------------------------------
# ML-quality metrics (eval / promptfoo / benchmark runs)
# --------------------------------------------------------------------------------------

# Unlabeled by design: the module's no-high-cardinality contract forbids
# corpus_id labels, and label-less instruments expose real zeros from process
# start so 24h increase() windows never miss the first run. Per-corpus
# drill-down lives in the ML-quality summary APIs, not Prometheus.

EVAL_RUNS_TOTAL = Counter(
    "tribrid_eval_runs_total",
    "Total number of persisted Eval Analysis runs.",
)

PROMPTFOO_RUNS_TOTAL = Counter(
    "tribrid_promptfoo_runs_total",
    "Total number of persisted Promptfoo regression runs.",
)

BENCHMARK_RUNS_TOTAL = Counter(
    "tribrid_benchmark_runs_total",
    "Total number of persisted Benchmark comparison runs.",
)


class LatestMLQualityCollector:
    """Scrape-time view of the newest persisted eval / Promptfoo / benchmark run.

    These four series used to be `Gauge`s set from the request that completed a
    run, which made them process-local: every API restart re-exported them at
    0 until the next run landed, and Grafana rendered that as a green 0%.
    A collector reads the persisted runs instead, so a freshly started process
    already reports the truth, and a metric with no persisted run behind it is
    **not exported at all** — the only encoding of "no data" Prometheus has.
    A plain gauge cannot express it: it can only say zero.
    """

    def collect(self):  # noqa: ANN201 - prometheus_client's collector protocol
        try:
            # Imported lazily: `ml_quality` reaches into the API and lineage
            # layers, which import this module.
            from server.observability.ml_quality import latest_quality_values

            values = latest_quality_values()
        except Exception:
            # A scrape must never fail wholesale because the run store is
            # unreadable; the absent series is the honest answer.
            return
        for name, documentation, value in (
            (
                "tribrid_eval_last_top1_accuracy",
                "Top-1 accuracy of the most recently persisted eval run.",
                values.eval_top1_accuracy,
            ),
            (
                "tribrid_eval_last_topk_accuracy",
                "Top-K accuracy of the most recently persisted eval run.",
                values.eval_topk_accuracy,
            ),
            (
                "tribrid_promptfoo_last_pass_ratio",
                "Pass ratio (passed/total) of the most recently persisted Promptfoo run.",
                values.promptfoo_pass_ratio,
            ),
            (
                "tribrid_benchmark_last_avg_latency_ms",
                "Mean per-model latency (ms) of the most recently persisted benchmark run.",
                values.benchmark_average_latency_ms,
            ),
        ):
            if value is None:
                continue
            yield GaugeMetricFamily(name, documentation, value=float(value))


REGISTRY.register(LatestMLQualityCollector())

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
    "qdrant_vector_search",
    "qdrant_sparse_search",
    "neo4j_connect",
    "neo4j_chunk_vector_search",
    "neo4j_expand_chunks_via_entities",
    "neo4j_entity_chunk_search",
    "postgres_get_chunks",
    "fusion_rrf",
    "normalize_scores",
    "fusion_weighted",
    "rerank",
    # Error aggregation stages (still low-cardinality)
    "vector_leg",
    "sparse_leg",
    "graph_leg",
)

_SEARCH_LEGS = ("vector", "sparse", "graph")

_CACHE_ENDPOINTS = ("search", "answer", "chat")
_CACHE_LOOKUP_OUTCOMES = ("hit_exact", "hit_semantic", "miss", "bypass", "too_short", "error")
_CACHE_WRITE_OUTCOMES = ("ok", "bypass", "too_short", "error")

_INDEX_STAGES = (
    "collect_file_paths",
    "file_read",
    "chunk",
    "embed_chunks",
    "postgres_upsert_chunks",
    "qdrant_write_chunks",
    "generation_commit",
    "neo4j_upsert_document_chunks",
    "neo4j_upsert_semantic_graph",
    "semantic_kg",
)

for _stage in _SEARCH_STAGES:
    SEARCH_STAGE_LATENCY_SECONDS.labels(stage=_stage)
    SEARCH_STAGE_ERRORS_TOTAL.labels(stage=_stage)

for _leg in _SEARCH_LEGS:
    SEARCH_LEG_RESULTS_COUNT.labels(leg=_leg)

for _endpoint in _CACHE_ENDPOINTS:
    SEMANTIC_CACHE_LOOKUP_LATENCY_SECONDS.labels(endpoint=_endpoint)
    SEMANTIC_CACHE_SEMANTIC_SIMILARITY.labels(endpoint=_endpoint)
    for _outcome in _CACHE_LOOKUP_OUTCOMES:
        SEMANTIC_CACHE_LOOKUPS_TOTAL.labels(endpoint=_endpoint, outcome=_outcome)
    for _outcome in _CACHE_WRITE_OUTCOMES:
        SEMANTIC_CACHE_WRITES_TOTAL.labels(endpoint=_endpoint, outcome=_outcome)

for _stage in _INDEX_STAGES:
    INDEX_STAGE_LATENCY_SECONDS.labels(stage=_stage)
    INDEX_STAGE_ERRORS_TOTAL.labels(stage=_stage)

_RERANKER_MODES = ("learning", "cloud")
_RERANKER_SKIP_REASONS = (
    "missing_trained_model",
    "missing_api_key",
    "no_candidates",
    "empty_query",
)
_RERANKER_TRAIN_OUTCOMES = ("started", "completed", "failed", "cancelled")
_RERANKER_TRAIN_STAGES = (
    "load_scoped_config",
    "load_triplets",
    "resolve_backend",
    "resolve_corpus",
    "materialize_triplets",
    "baseline_eval",
    "train_loop",
    "final_eval",
    "promote",
    "mine_triplets",
    "evaluate_active",
    "score_pair",
)
_RERANKER_EVENT_TYPES = ("state", "log", "progress", "metrics", "telemetry", "error", "complete")
_RERANKER_TRIPLET_KINDS = ("loaded", "materialized", "train_split", "dev_split", "mined")
_RERANKER_TRIPLET_SKIP_REASONS = ("missing_positive", "missing_negative", "empty_positive", "empty_negative")
_RERANKER_EVAL_PHASES = ("baseline", "final", "active")
_RERANKER_METRIC_PHASES = ("stream", "baseline", "final", "evaluate")
_RERANKER_METRIC_NAMES = ("mrr", "ndcg", "map", "train_loss", "lr", "grad_norm")
_RERANKER_MINE_OUTCOMES = ("ok", "error")
_RERANKER_PROMOTION_OUTCOMES = ("ok", "error", "promoted", "skipped")

for _mode in _RERANKER_MODES:
    RERANKER_REQUESTS_TOTAL.labels(mode=_mode)
    RERANKER_CANDIDATES_TOTAL.labels(mode=_mode)
    RERANKER_ERRORS_TOTAL.labels(mode=_mode)
    RERANKER_LATENCY_SECONDS.labels(mode=_mode)
    for _reason in _RERANKER_SKIP_REASONS:
        RERANKER_SKIPPED_TOTAL.labels(mode=_mode, reason=_reason)

for _outcome in _RERANKER_TRAIN_OUTCOMES:
    RERANKER_TRAIN_RUNS_TOTAL.labels(outcome=_outcome)

for _stage in _RERANKER_TRAIN_STAGES:
    RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=_stage)
    RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage=_stage)

for _etype in _RERANKER_EVENT_TYPES:
    RERANKER_TRAIN_EVENTS_TOTAL.labels(type=_etype)

for _kind in _RERANKER_TRIPLET_KINDS:
    RERANKER_TRIPLETS_TOTAL.labels(kind=_kind)

for _reason in _RERANKER_TRIPLET_SKIP_REASONS:
    RERANKER_TRIPLET_SKIPS_TOTAL.labels(reason=_reason)

for _phase in _RERANKER_EVAL_PHASES:
    RERANKER_EVAL_LATENCY_SECONDS.labels(phase=_phase)
    for _outcome in ("ok", "error"):
        RERANKER_EVAL_RUNS_TOTAL.labels(phase=_phase, outcome=_outcome)

for _phase in _RERANKER_METRIC_PHASES:
    for _metric in _RERANKER_METRIC_NAMES:
        RERANKER_TRAIN_LAST_METRIC.labels(metric=_metric, phase=_phase)

for _outcome in _RERANKER_MINE_OUTCOMES:
    RERANKER_MINE_RUNS_TOTAL.labels(outcome=_outcome)

for _outcome in _RERANKER_PROMOTION_OUTCOMES:
    RERANKER_PROMOTIONS_TOTAL.labels(outcome=_outcome)


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
