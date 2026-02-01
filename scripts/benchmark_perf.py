#!/usr/bin/env python3
"""TriBridRAG performance benchmark runner.

This script is intentionally self-contained and reproducible:
- Index a corpus via the same internal pipeline used by the API
- Run a fixed set of searches and report latency distributions

Notes:
- Requires Postgres + Neo4j to be running (see README).
- Uses the current `tribrid_config.json` as the baseline (Pydantic-first).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.api.index import _run_index
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import get_config as load_scoped_config

DEFAULT_QUERIES: list[str] = [
    "authentication flow",
    "prometheus metrics endpoint /metrics",
    "neo4j graph retrieval mode",
    "where is /api/search implemented",
    "fusion rrf_k parameter",
]


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
        "env": {
            # Redact any key material; just record whether it is set.
            "NEO4J_URI": os.getenv("NEO4J_URI") or None,
            "NEO4J_USER": os.getenv("NEO4J_USER") or None,
            "NEO4J_PASSWORD_set": bool(os.getenv("NEO4J_PASSWORD")),
            "POSTGRES_DSN": os.getenv("POSTGRES_DSN") or None,
            "POSTGRES_HOST": os.getenv("POSTGRES_HOST") or None,
            "POSTGRES_PORT": os.getenv("POSTGRES_PORT") or None,
            "POSTGRES_DB": os.getenv("POSTGRES_DB") or None,
        },
    }


async def _benchmark_search(
    *,
    corpus_id: str,
    queries: list[str],
    iterations: int,
    warmup: int,
    include_vector: bool,
    include_sparse: bool,
    include_graph: bool,
    top_k: int | None,
) -> dict[str, Any]:
    cfg = await load_scoped_config(repo_id=corpus_id)
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    per_query: list[dict[str, Any]] = []
    all_lat_ms: list[float] = []
    total_calls = 0
    t0_all = time.perf_counter()

    for q in queries:
        q = str(q or "").strip()
        if not q:
            continue

        # Warmup
        for _ in range(max(0, int(warmup))):
            await fusion.search(
                corpus_id,
                q,
                cfg.fusion,
                include_vector=include_vector,
                include_sparse=include_sparse,
                include_graph=include_graph,
                top_k=top_k,
            )

        lat_ms: list[float] = []
        matches_counts: list[int] = []
        for _ in range(max(1, int(iterations))):
            t0 = time.perf_counter()
            matches = await fusion.search(
                corpus_id,
                q,
                cfg.fusion,
                include_vector=include_vector,
                include_sparse=include_sparse,
                include_graph=include_graph,
                top_k=top_k,
            )
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

    total_s = max(0.000001, time.perf_counter() - t0_all)
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


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="TriBridRAG benchmark runner")
    parser.add_argument("--corpus-id", default="tribrid-rag", help="Corpus ID (repo_id)")
    parser.add_argument("--corpus-path", default=".", help="Path to corpus root (indexed content)")
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
    parser.add_argument("--out-json", default="", help="Optional path to write JSON results.")
    args = parser.parse_args()

    corpus_id = str(args.corpus_id).strip()
    corpus_path = Path(str(args.corpus_path)).expanduser().resolve()
    if not corpus_path.exists():
        raise SystemExit(f"Corpus path not found: {corpus_path}")

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

    result: dict[str, Any] = {
        "env": _env_summary(),
        "corpus": {"corpus_id": corpus_id, "corpus_path": str(corpus_path)},
    }

    # Index (optional)
    if not args.skip_index:
        t0 = time.perf_counter()
        stats = await _run_index(
            repo_id=corpus_id,
            repo_path=str(corpus_path),
            force_reindex=bool(args.force_reindex),
            event_queue=None,
        )
        idx_s = time.perf_counter() - t0
        result["indexing"] = {
            "duration_seconds": float(idx_s),
            "stats": stats.model_dump(mode="serialization", by_alias=True),
        }
    else:
        result["indexing"] = {"skipped": True}

    # Search
    search = await _benchmark_search(
        corpus_id=corpus_id,
        queries=queries,
        iterations=int(args.iterations),
        warmup=int(args.warmup),
        include_vector=include_vector,
        include_sparse=include_sparse,
        include_graph=include_graph,
        top_k=int(args.top_k) if args.top_k is not None else None,
    )
    result["search"] = search

    # Output JSON
    if args.out_json:
        out_path = Path(str(args.out_json)).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    # Print markdown summary (copy/paste into README)
    idx = result.get("indexing") or {}
    idx_stats = (idx.get("stats") or {}) if isinstance(idx, dict) else {}
    search_sum = search["summary"]

    print("# TriBridRAG Benchmark Result")
    print()
    print(f"- timestamp: `{result['env']['timestamp']}`")
    print(f"- corpus_id: `{corpus_id}`")
    print(f"- corpus_path: `{corpus_path}`")
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

