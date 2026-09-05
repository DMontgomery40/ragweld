#!/usr/bin/env python3
"""Ragweld performance benchmark against an explicitly selected running API.

This script is intentionally self-contained and reproducible:
- Index through the normal server-owned fence, accounting and promotion lifecycle
- Measure complete HTTP search requests, including the application boundary

Notes:
- Requires a running Ragweld API with a registered corpus and its saved config.
- Corpus paths are interpreted by that server, never by the benchmark client.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import platform
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field, field_validator

from server.models.index import IndexRequest, IndexRunSummary, IndexStatus
from server.models.tribrid_config_model import Corpus, SearchRequest, SearchResponse

DEFAULT_QUERIES: list[str] = [
    "authentication flow",
    "prometheus metrics endpoint /metrics",
    "neo4j graph retrieval mode",
    "where is /api/search implemented",
    "fusion rrf_k parameter",
]


class BenchmarkConnection(BaseModel):
    """Validated CLI connection and wait limits; no application runtime is started."""

    api_base_url: str
    request_timeout_s: float = Field(default=60, gt=0, le=3600)
    index_timeout_s: float = Field(default=3600, gt=0, le=86400)

    @field_validator("api_base_url")
    @classmethod
    def _api_origin(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") not in {"", "/api"}):
            raise ValueError("API base URL must be an explicit HTTP(S) origin, optionally ending in /api")
        return f"{parsed.scheme}://{parsed.netloc}/api/"


@contextmanager
def _owned_report_output(path: Path | None) -> Iterator[Path | None]:
    """An explicit report path belongs to one invocation from before its first API call."""
    if path is None:
        yield None
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep a stable lock inode: removing this sidecar would let a later writer
    # acquire a different inode while another invocation still owns the old one.
    with path.with_name(path.name + ".lock").open("a") as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Report output is already owned by another benchmark") from error
        # --out-json explicitly replaces this report. A failed replacement must
        # not leave an earlier invocation's successful measurements in its place.
        path.unlink(missing_ok=True)
        yield path


def _publish_report(path: Path, result: dict[str, Any]) -> None:
    """Readers see the complete successful report, never a partially written JSON file."""
    descriptor, temporary = tempfile.mkstemp(prefix=".ragweld-benchmark-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(result, output, indent=2, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _percentile_ms(values_ms: list[float], p: float) -> float:
    """Nearest-rank percentile (p in [0, 100])."""
    if not values_ms:
        return 0.0
    p = max(0.0, min(100.0, float(p)))
    xs = sorted(values_ms)
    # Nearest-rank: https://en.wikipedia.org/wiki/Percentile#The_nearest-rank_method
    k = int((p / 100.0) * len(xs) + 0.999999)  # ceil without math import
    idx = max(0, min(len(xs) - 1, k - 1))
    return float(xs[idx])


def _mean_ms(values_ms: list[float]) -> float:
    if not values_ms:
        return 0.0
    return float(sum(values_ms) / float(len(values_ms)))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _env_summary() -> dict[str, Any]:
    return {
        "timestamp": _now_iso(),
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cwd": str(Path.cwd()),
    }


async def _benchmark_search(
    *,
    client: httpx.AsyncClient,
    corpus_id: str,
    queries: list[str],
    iterations: int,
    warmup: int,
    include_vector: bool,
    include_sparse: bool,
    include_graph: bool,
    top_k: int | None,
) -> dict[str, Any]:
    per_query: list[dict[str, Any]] = []
    all_lat_ms: list[float] = []
    total_calls = 0

    for q in queries:
        q = str(q or "").strip()
        if not q:
            continue

        request = SearchRequest(
            repo_id=corpus_id, query=q, include_vector=include_vector,
            include_sparse=include_sparse, include_graph=include_graph,
            top_k=top_k if top_k is not None else int(SearchRequest.model_fields["top_k"].default),
        )
        body = request.model_dump(mode="json", by_alias=True)

        # Warmup is excluded from both measured latency and throughput.
        for _ in range(max(0, int(warmup))):
            response = await client.post("search", json=body)
            response.raise_for_status()
            SearchResponse.model_validate(response.json())

        lat_ms: list[float] = []
        matches_counts: list[int] = []
        for _ in range(max(1, int(iterations))):
            t0 = time.perf_counter()
            response = await client.post("search", json=body)
            response.raise_for_status()
            matches = SearchResponse.model_validate(response.json()).matches
            dt_ms = (time.perf_counter() - t0) * 1000.0
            lat_ms.append(dt_ms)
            matches_counts.append(len(matches))
            all_lat_ms.append(dt_ms)
            total_calls += 1

        per_query.append(
            {
                "query": q,
                "iterations": int(iterations),
                "warmup": int(warmup),
                "latency_ms": {
                    "p50": _percentile_ms(lat_ms, 50),
                    "p95": _percentile_ms(lat_ms, 95),
                    "mean": _mean_ms(lat_ms),
                    "min": float(min(lat_ms) if lat_ms else 0.0),
                    "max": float(max(lat_ms) if lat_ms else 0.0),
                },
                "matches": {
                    "mean": float(sum(matches_counts) / max(1, len(matches_counts))),
                    "min": int(min(matches_counts) if matches_counts else 0),
                    "max": int(max(matches_counts) if matches_counts else 0),
                },
            }
        )

    total_s = max(0.000001, sum(all_lat_ms) / 1000)
    qps = float(total_calls) / total_s
    return {
        "config": {
            "include_vector": bool(include_vector),
            "include_sparse": bool(include_sparse),
            "include_graph": bool(include_graph),
            "top_k": int(top_k) if top_k is not None else None,
            "iterations": int(iterations),
            "warmup": int(warmup),
        },
        "summary": {
            "total_calls": int(total_calls),
            "total_seconds": float(total_s),
            "qps": float(qps),
            "latency_ms": {
                "p50": _percentile_ms(all_lat_ms, 50),
                "p95": _percentile_ms(all_lat_ms, 95),
                "mean": _mean_ms(all_lat_ms),
                "min": float(min(all_lat_ms) if all_lat_ms else 0.0),
                "max": float(max(all_lat_ms) if all_lat_ms else 0.0),
            },
        },
        "per_query": per_query,
    }


async def _benchmark_index(
    client: httpx.AsyncClient, request: IndexRequest, *, timeout_s: float,
) -> dict[str, Any]:
    """Wait for this accepted run, never a later run's status or latest stats."""
    started_clock = time.perf_counter()
    response = await client.post("index", json=request.model_dump(mode="json", by_alias=True))
    response.raise_for_status()
    accepted = IndexStatus.model_validate(response.json())
    if accepted.repo_id != request.repo_id or accepted.started_at is None or accepted.status != "indexing":
        raise RuntimeError("API did not return a matching accepted index run")
    corpus_path = quote(request.repo_id, safe="")
    run_id: str | None = None
    try:
        async with asyncio.timeout(timeout_s):
            while True:
                suffix = run_id or "latest"
                response = await client.get(f"index/{corpus_path}/runs/{suffix}")
                if response.status_code == 404 and run_id is None:
                    await asyncio.sleep(0.1)
                    continue
                response.raise_for_status()
                run = IndexRunSummary.model_validate(response.json())
                if run.repo_id != request.repo_id or run.run_kind != "index":
                    raise RuntimeError("Index history belongs to a different corpus or operation")
                if run.started_at < accepted.started_at and run_id is None:
                    # The accepted background owner has not written its first summary yet.
                    await asyncio.sleep(0.1)
                    continue
                if run.started_at != accepted.started_at or (run_id is not None and run.run_id != run_id):
                    raise RuntimeError("Index history no longer identifies the accepted benchmark run")
                run_id = run.run_id
                if run.status == "complete":
                    return {
                        "duration_seconds": time.perf_counter() - started_clock,
                        "run_id": run_id,
                        "stats": {"total_files": run.total_files, "total_chunks": run.total_chunks,
                                  "total_tokens": run.total_tokens},
                    }
                if run.status in {"error", "cancelled"}:
                    raise RuntimeError(f"Index run failed ({run_id}): {run.error or run.status}")
                await asyncio.sleep(0.1)
    except TimeoutError as error:
        owner = run_id or f"started at {accepted.started_at.isoformat()}"
        raise RuntimeError(
            f"Index wait timed out for {request.repo_id} ({owner}); indexing may continue on the server"
        ) from error


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Benchmark complete HTTP requests against a running Ragweld API")
    parser.add_argument("--api-base-url", required=True, help="Explicit running API origin (or origin/api); starts no local runtime")
    parser.add_argument("--request-timeout", type=float, default=60, help="Maximum seconds per HTTP request")
    parser.add_argument("--index-timeout", type=float, default=3600, help="Maximum seconds to wait for the accepted index run; expiration does not stop it")
    parser.add_argument("--corpus-id", default="tribrid-rag", help="Corpus ID (repo_id)")
    parser.add_argument("--corpus-path", default="", help="Corpus root on the API server; defaults to the registered corpus path")
    parser.add_argument("--approved-graph-schema-hash", default=None, help="Exact reviewed schema hash required for semantic graph indexing")
    parser.add_argument("--force-reindex", action="store_true", help="Rebuild the index before benchmarking")
    parser.add_argument("--skip-index", action="store_true", help="Skip indexing step (assumes corpus already indexed)")

    parser.add_argument("--iterations", type=int, default=5, help="Search iterations per query (measured)")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup runs per query (not measured)")
    parser.add_argument("--top-k", type=int, default=10, help="Override retrieval.final_k for this run")

    parser.add_argument("--no-vector", action="store_true", help="Disable vector leg for this benchmark run")
    parser.add_argument("--no-sparse", action="store_true", help="Disable sparse leg for this benchmark run")
    parser.add_argument("--no-graph", action="store_true", help="Disable graph leg for this benchmark run")

    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Add a query (repeatable). If omitted, uses a small built-in query set.",
    )
    parser.add_argument(
        "--queries-file",
        default="",
        help="Optional path to a newline-delimited query file.",
    )
    parser.add_argument("--out-json", default="", help="Replace this report before API work; publish JSON only on success (one writer per path)")
    args = parser.parse_args()
    connection = BenchmarkConnection(api_base_url=args.api_base_url, request_timeout_s=args.request_timeout,
                                     index_timeout_s=args.index_timeout)

    corpus_id = str(args.corpus_id).strip()

    include_vector = not bool(args.no_vector)
    include_sparse = not bool(args.no_sparse)
    include_graph = not bool(args.no_graph)

    queries: list[str] = []
    if args.queries_file:
        qf = Path(str(args.queries_file)).expanduser().resolve()
        if not qf.exists():
            raise SystemExit(f"Queries file not found: {qf}")
        queries.extend([ln.strip() for ln in qf.read_text(encoding="utf-8").splitlines() if ln.strip()])
    queries.extend([str(q).strip() for q in (args.query or []) if str(q).strip()])
    if not queries:
        queries = list(DEFAULT_QUERIES)

    out_path = Path(str(args.out_json)).expanduser().resolve() if args.out_json else None
    with _owned_report_output(out_path) as report_path:
        async with httpx.AsyncClient(base_url=connection.api_base_url, timeout=connection.request_timeout_s,
                                     trust_env=False) as client:
            response = await client.get(f"corpora/{quote(corpus_id, safe='')}")
            response.raise_for_status()
            corpus = Corpus.model_validate(response.json())
            if corpus.repo_id != corpus_id:
                raise RuntimeError("API returned a different corpus")
            corpus_path = str(args.corpus_path).strip() or corpus.path
            result: dict[str, Any] = {
                "env": _env_summary(), "measurement": "application_http", "api_base_url": connection.api_base_url,
                "corpus": {"corpus_id": corpus_id, "corpus_path": corpus_path},
            }
            if not args.skip_index:
                result["indexing"] = await _benchmark_index(client, IndexRequest(
                    repo_id=corpus_id, repo_path=corpus_path, force_reindex=bool(args.force_reindex),
                    approved_graph_schema_hash=args.approved_graph_schema_hash,
                ), timeout_s=connection.index_timeout_s)
            else:
                result["indexing"] = {"skipped": True}
            search = await _benchmark_search(
                client=client, corpus_id=corpus_id, queries=queries, iterations=int(args.iterations),
                warmup=int(args.warmup), include_vector=include_vector, include_sparse=include_sparse,
                include_graph=include_graph, top_k=int(args.top_k) if args.top_k is not None else None,
            )
        result["search"] = search
        if report_path is not None:
            _publish_report(report_path, result)

    # Print markdown summary (copy/paste into README)
    idx = result.get("indexing") or {}
    idx_stats = (idx.get("stats") or {}) if isinstance(idx, dict) else {}
    search_sum = search["summary"]

    print("# Ragweld HTTP Benchmark Result")
    print()
    print(f"- timestamp: `{result['env']['timestamp']}`")
    print(f"- corpus_id: `{corpus_id}`")
    print(f"- corpus_path: `{corpus_path}`")
    print(f"- API: `{connection.api_base_url}`")
    print("- measurement: complete HTTP search requests; warmup excluded from latency and throughput")
    print(f"- include_vector/sparse/graph: `{include_vector}/{include_sparse}/{include_graph}`")
    print(f"- iterations/warmup: `{int(args.iterations)}/{int(args.warmup)}`")
    print()

    if isinstance(idx_stats, dict) and idx_stats:
        print("## Indexing")
        print()
        print(f"- duration_s: `{float(idx.get('duration_seconds') or 0.0):.3f}`")
        print(f"- total_files: `{idx_stats.get('total_files', 0)}`")
        print(f"- total_chunks: `{idx_stats.get('total_chunks', 0)}`")
        print(f"- total_tokens: `{idx_stats.get('total_tokens', 0)}`")
        print()

    print("## Search")
    print()
    print("| Metric | Value |")
    print("|---|---:|")
    print(f"| Calls | {search_sum['total_calls']} |")
    print(f"| QPS | {search_sum['qps']:.2f} |")
    print(f"| Latency p50 (ms) | {search_sum['latency_ms']['p50']:.1f} |")
    print(f"| Latency p95 (ms) | {search_sum['latency_ms']['p95']:.1f} |")
    print(f"| Latency mean (ms) | {search_sum['latency_ms']['mean']:.1f} |")
    print()

    print("### Per-query")
    print()
    print("| Query | p50 ms | p95 ms | mean ms | matches (avg) |")
    print("|---|---:|---:|---:|---:|")
    for row in search.get("per_query") or []:
        q = str(row.get("query") or "")
        lat = row.get("latency_ms") or {}
        matches = row.get("matches") or {}
        print(
            f"| {q} | {float(lat.get('p50') or 0.0):.1f} | {float(lat.get('p95') or 0.0):.1f} | {float(lat.get('mean') or 0.0):.1f} | {float(matches.get('mean') or 0.0):.1f} |"
        )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
