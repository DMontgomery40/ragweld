#!/usr/bin/env python
"""A/B the reranker lanes over the SAME fused candidate lists, scored at the chunk level.

For each eval question the live fusion lane runs once with a capturing stand-in for the
reranker, so every condition reorders the identical fused list. Conditions:

- ``none``: fusion order.
- ``gateway``: the configured LiteLLM listwise reranker (the corpus's reranking config).
- ``jev``: one System One Noul per (query, candidate) on TypeSafe Jev.
- ``jev_batched``: the same Noul for every candidate in ONE Jev request (passage in the
  structured instructions, query in the state).
- ``laya``: one Noul per pair on a self-hosted CPU ``laya-serve`` (``--laya-base-url``).

System One scores go through the product's own blend (``Reranker._apply_cloud_scores``:
min-max, alpha, top_n, snippet chars), so the scorer is the only variable. Each condition
is scored twice with ``server.evaluation.scoring``: the reranked list itself (``list``),
and the final results after the product's shaping (dedup, per-file cap, neighbours,
boosts), obtained by replaying the condition's order through the fusion lane
(``pipeline``).

Run on LXC100 only, from an overlay, read-only against the live stores:

    set -a; . /etc/ragweld/runtime.env; set +a
    PYTHONPATH=$PWD /opt/ragweld/.venv/bin/python scripts/rerank_ab_harness.py \
        --corpus nasa-apollo-11 --figures data/eval_datasets/nasa-apollo-11-figures.json \
        --laya-base-url http://127.0.0.1:58189 --laya-pid <pid> --out /var/tmp/rerank_ab.json

Every config read is forced to persist=False and retrieval bypasses the semantic cache, so
overlay code never migrates or writes live configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.evaluation.scoring import (  # noqa: E402
    EntryScore,
    EvalCutoffs,
    aggregate_entry_scores,
    build_expectations,
    is_uninformative,
    score_entry,
)
from server.models.eval_figures import FigureEvalDataset  # noqa: E402
from server.models.system_one import SystemOneNoul, SystemOneNoulCriteria  # noqa: E402
from server.models.tribrid_config_model import (  # noqa: E402
    ChunkMatch,
    EvalDatasetItem,
    EvalExpectedLocation,
    TriBridConfig,
)
from server.services import config_store  # noqa: E402

# Read-only: every scope read, including fusion's own, must leave stored config alone.
_ORIGINAL_GET = config_store.ConfigStore.get


async def _read_only_get(self: Any, repo_id: str | None = None, *, persist: bool = True) -> TriBridConfig:
    del persist
    return await _ORIGINAL_GET(self, repo_id, persist=False)


config_store.ConfigStore.get = _read_only_get  # type: ignore[method-assign]

from server.db.postgres import PostgresClient  # noqa: E402
from server.gateway_catalog import warm_gateway_catalog  # noqa: E402
from server.retrieval import fusion as fusion_module  # noqa: E402
from server.retrieval import gateway_reranker  # noqa: E402
from server.retrieval.rerank import Reranker, RerankResult  # noqa: E402
from server.system_one.client import SystemOneClient  # noqa: E402

JEV_USD_PER_INPUT_TOKEN = 42.0 / 1_000_000_000
MAX_PRECISE_SPAN_PAGES = 3
HIT_KS = (1, 3, 5, 10)
LAYA_CONTEXT_TOKENS = 512

# System One pointwise rerank measured here (TypeSafe rerank cookbook shape). It stays in this
# harness: the A/B did not justify replacing the gateway reranker (see the decision rule).
RERANK_QUESTION_ID = "answers_query"

RERANK_QUESTION = SystemOneNoul(
    instructions="Does `candidate_passage` contain information that answers `query` or directly helps answer it?",
    criteria=SystemOneNoulCriteria(
        true=(
            "The passage states the facts, figures, names, dates, events or explanations the query asks for, "
            "or a part of the answer the query needs."
        ),
        false=(
            "The passage is about something else, only shares words or the general topic with the query, "
            "or is boilerplate such as a title page, table of contents, running header, list of figures or index."
        ),
    ),
)


@dataclass(frozen=True)
class SystemOneRerankScores:
    """Per-candidate nouls in candidate order, plus the usage the provider reported."""

    scores: list[float]
    request_input_tokens: tuple[int, ...]

    @property
    def input_tokens(self) -> int:
        return sum(self.request_input_tokens)

    @property
    def requests(self) -> int:
        return len(self.request_input_tokens)


def rerank_state(query: str, passage: str) -> dict[str, str]:
    return {"query": str(query), "candidate_passage": str(passage)}


async def score_candidates(client: SystemOneClient, *, query: str, docs: list[str]) -> SystemOneRerankScores:
    """One Noul request per candidate; any failure cancels the siblings and raises."""
    if not docs:
        return SystemOneRerankScores(scores=[], request_input_tokens=())

    async def _one(doc: str) -> tuple[float, int]:
        response = await client.ask(rerank_state(query, doc), {RERANK_QUESTION_ID: RERANK_QUESTION})
        return float(response.answers[RERANK_QUESTION_ID].noul), int(response.usage.input_tokens)

    tasks = [asyncio.ensure_future(_one(doc)) for doc in docs]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return SystemOneRerankScores(
        scores=[score for score, _ in results],
        request_input_tokens=tuple(tokens for _, tokens in results),
    )

DECISION_RULE = (
    "Replace the gateway lane with System One only if, on the same fused lists: (a) its list MRR and "
    "nDCG@10 are not below the gateway's and paired per-query reciprocal-rank losses <= wins, AND its "
    "rerank p95 is at most half the gateway's; or (b) its list MRR beats the gateway's by >= 0.05 "
    "with losses <= wins. n is small, so paired wins/losses carry as much weight as the means."
)

CONDITIONS = ("none", "gateway", "jev", "jev_batched", "laya")


# ---------------------------------------------------------------------------
# Stand-ins for the fusion lane's reranker (harness-local; the product is untouched)
# ---------------------------------------------------------------------------

_CAPTURED: dict[str, list[ChunkMatch]] = {}
_REPLAY: dict[str, list[ChunkMatch]] = {}


class _CaptureReranker:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def try_rerank(self, query: str, chunks: list[ChunkMatch]) -> RerankResult:
        _CAPTURED[query] = [c.model_copy(deep=True) for c in chunks]
        return RerankResult(chunks=chunks, ok=True, applied=False)


class _ReplayReranker:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def try_rerank(self, query: str, chunks: list[ChunkMatch]) -> RerankResult:
        del chunks
        return RerankResult(chunks=[c.model_copy(deep=True) for c in _REPLAY[query]], ok=True, applied=True)


# Gateway cost capture: wrap the generation call the gateway reranker makes.
_GATEWAY_COSTS: list[dict[str, Any]] = []
_ORIGINAL_GENERATE = gateway_reranker.generate_chat_text


async def _generate_and_record(**kwargs: Any) -> Any:
    result = await _ORIGINAL_GENERATE(**kwargs)
    summary = result.cost_summary
    _GATEWAY_COSTS.append(
        {
            "cost_usd": float(summary.estimated_cost_usd or 0.0) if summary is not None else 0.0,
            "cost_source": summary.cost_source if summary is not None else "unavailable",
            "input_tokens": int(summary.input_tokens or 0) if summary is not None else 0,
            "output_tokens": int(summary.output_tokens or 0) if summary is not None else 0,
        }
    )
    return result


gateway_reranker.generate_chat_text = _generate_and_record  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _span_pages(chunk: ChunkMatch) -> int | None:
    prov = chunk.provenance
    if prov is None or prov.page_start is None or prov.page_end is None:
        return None
    return int(prov.page_end) - int(prov.page_start) + 1


def _hits(score: EntryScore) -> list[bool]:
    return [kind in {"location", "file"} for kind in score.matches]


def _precise_hits(score: EntryScore, chunks: list[ChunkMatch]) -> list[bool]:
    out: list[bool] = []
    for hit, chunk in zip(_hits(score), chunks, strict=False):
        span = _span_pages(chunk)
        out.append(bool(hit and span is not None and span <= MAX_PRECISE_SPAN_PAGES))
    return out


def _rr(hits: list[bool]) -> float:
    return next((1.0 / rank for rank, hit in enumerate(hits, start=1) if hit), 0.0)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    idx = min(len(xs) - 1, max(0, math.ceil(p * len(xs)) - 1))
    return float(xs[idx])


@dataclass
class ConditionLog:
    latencies_s: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    input_tokens: int = 0
    requests: int = 0
    cost_usd: float = 0.0
    laya_over_context: int = 0
    laya_max_input_tokens: int = 0
    list_scores: list[EntryScore] = field(default_factory=list)
    pipeline_scores: list[EntryScore] = field(default_factory=list)
    list_rr: list[float] = field(default_factory=list)
    list_precise_rr: list[float] = field(default_factory=list)
    list_hits: list[list[bool]] = field(default_factory=list)
    list_precise_hits: list[list[bool]] = field(default_factory=list)
    pipeline_hits: list[list[bool]] = field(default_factory=list)


def _proc_stats(pid: int | None) -> dict[str, float] | None:
    if not pid:
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        ticks = os.sysconf("SC_CLK_TCK")
        cpu_s = (int(stat[13]) + int(stat[14])) / float(ticks)
        status = Path(f"/proc/{pid}/status").read_text().splitlines()
        rss = next((int(line.split()[1]) for line in status if line.startswith("VmRSS:")), 0)
        hwm = next((int(line.split()[1]) for line in status if line.startswith("VmHWM:")), 0)
        return {"cpu_s": cpu_s, "rss_mib": rss / 1024.0, "hwm_mib": hwm / 1024.0}
    except (OSError, ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def _system_one_candidates(reranker: Reranker, fused: list[ChunkMatch]) -> tuple[list[ChunkMatch], list[ChunkMatch], list[str]]:
    return reranker._cloud_candidates(fused)


async def _rerank_pairwise(
    client: SystemOneClient, reranker: Reranker, query: str, fused: list[ChunkMatch], log: ConditionLog, *, laya: bool
) -> list[ChunkMatch]:
    candidates, remainder, docs = _system_one_candidates(reranker, fused)
    started = time.perf_counter()
    result = await score_candidates(client, query=query, docs=docs)
    out = reranker._apply_cloud_scores(
        candidates=candidates, remainder=remainder, raw_scores=result.scores, provider="system_one"
    )
    log.latencies_s.append(time.perf_counter() - started)
    log.input_tokens += result.input_tokens
    log.requests += result.requests
    if laya:
        log.laya_max_input_tokens = max(log.laya_max_input_tokens, *result.request_input_tokens)
        log.laya_over_context += sum(1 for tokens in result.request_input_tokens if tokens >= LAYA_CONTEXT_TOKENS)
    return out


async def _rerank_batched(
    client: SystemOneClient, reranker: Reranker, query: str, fused: list[ChunkMatch], log: ConditionLog
) -> list[ChunkMatch]:
    candidates, remainder, docs = _system_one_candidates(reranker, fused)
    criteria = RERANK_QUESTION.criteria
    questions = {
        f"c{index:02d}": SystemOneNoul(
            instructions={
                "candidate_passage": doc,
                "question": "Does `candidate_passage` contain information that answers `query` or directly helps answer it?",
            },
            criteria=criteria,
        )
        for index, doc in enumerate(docs)
    }
    started = time.perf_counter()
    response = await client.ask({"query": query}, questions)
    scores = [float(response.answers[f"c{index:02d}"].noul) for index in range(len(docs))]
    out = reranker._apply_cloud_scores(candidates=candidates, remainder=remainder, raw_scores=scores, provider="system_one")
    log.latencies_s.append(time.perf_counter() - started)
    log.input_tokens += int(response.usage.input_tokens)
    log.requests += 1
    return out


async def _rerank_gateway(cfg: TriBridConfig, query: str, fused: list[ChunkMatch], log: ConditionLog) -> list[ChunkMatch]:
    reranker = Reranker(cfg.reranking, training_config=cfg.training, gateway_config=cfg)
    before = len(_GATEWAY_COSTS)
    started = time.perf_counter()
    result = await reranker.try_rerank(query, [c.model_copy(deep=True) for c in fused])
    log.latencies_s.append(time.perf_counter() - started)
    for entry in _GATEWAY_COSTS[before:]:
        log.cost_usd += entry["cost_usd"]
        log.input_tokens += entry["input_tokens"]
        log.requests += 1
    if not result.ok:
        raise RuntimeError(result.error or "gateway reranker failed")
    return result.chunks


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def _published_rows(api_base: str, corpus: str) -> list[EvalDatasetItem]:
    async with httpx.AsyncClient(timeout=30.0) as api:
        response = await api.get(f"{api_base.rstrip('/')}/dataset", params={"corpus_id": corpus})
        response.raise_for_status()
        return [EvalDatasetItem.model_validate(row) for row in response.json()]


def _summarize(name: str, log: ConditionLog, n: int) -> dict[str, Any]:
    list_head = aggregate_entry_scores(log.list_scores) if log.list_scores else None
    pipe_head = aggregate_entry_scores(log.pipeline_scores) if log.pipeline_scores else None

    def hit_at(rows: list[list[bool]], k: int) -> float:
        return sum(1 for hits in rows if any(hits[:k])) / float(len(rows)) if rows else 0.0

    return {
        "condition": name,
        "queries": n,
        "failures": log.failures,
        "list": {
            "mrr": list_head.mrr if list_head else None,
            "ndcg_at_10": list_head.ndcg_at_10 if list_head else None,
            "uninformative": list_head.uninformative if list_head else None,
            **{f"hit_at_{k}": hit_at(log.list_hits, k) for k in HIT_KS},
            "precise_mrr": statistics.fmean(log.list_precise_rr) if log.list_precise_rr else None,
            **{f"precise_hit_at_{k}": hit_at(log.list_precise_hits, k) for k in (3, 5)},
        },
        "pipeline": {
            "mrr": pipe_head.mrr if pipe_head else None,
            "ndcg_at_10": pipe_head.ndcg_at_10 if pipe_head else None,
            **{f"hit_at_{k}": hit_at(log.pipeline_hits, k) for k in HIT_KS},
        },
        "rerank_latency_s": {
            "p50": _percentile(log.latencies_s, 0.50),
            "p95": _percentile(log.latencies_s, 0.95),
            "max": max(log.latencies_s) if log.latencies_s else 0.0,
        },
        "requests": log.requests,
        "input_tokens": log.input_tokens,
        "cost_usd": log.cost_usd,
    }


def _paired(a: list[float], b: list[float]) -> dict[str, int]:
    wins = sum(1 for x, y in zip(a, b, strict=True) if x > y + 1e-12)
    losses = sum(1 for x, y in zip(a, b, strict=True) if x < y - 1e-12)
    return {"wins": wins, "losses": losses, "ties": len(a) - wins - losses}


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    warm_gateway_catalog()  # the live server warms it at startup; the gateway route needs it
    cfg = await config_store.get_config(args.corpus, persist=False)
    if args.gateway_alias:
        cfg.reranking.reranker_cloud_provider = "litellm"
        cfg.reranking.reranker_cloud_model = str(args.gateway_alias)
    elif str(cfg.reranking.reranker_cloud_provider) != "litellm" or not str(cfg.reranking.reranker_cloud_model).strip():
        raise SystemExit(
            f"{args.corpus} has no configured gateway reranker (provider={cfg.reranking.reranker_cloud_provider!r}, "
            f"model={cfg.reranking.reranker_cloud_model!r}); pass --gateway-alias to name one."
        )
    cfg.reranking.reranker_mode = "cloud"

    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        corpus_paths = await pg.list_indexed_file_paths(args.corpus)
    finally:
        await pg.disconnect()

    cutoffs = EvalCutoffs(
        final_k=max(1, int(cfg.retrieval.eval_final_k)),
        recall_at_5=int(cfg.evaluation.recall_at_5_k),
        recall_at_10=int(cfg.evaluation.recall_at_10_k),
        recall_at_20=int(cfg.evaluation.recall_at_20_k),
        precision_at_5=int(cfg.evaluation.precision_at_5_k),
        ndcg_at_10=int(cfg.evaluation.ndcg_at_10_k),
    )
    eval_k = cutoffs.retrieval_k

    published = await _published_rows(args.api_base, args.corpus)
    published_uninformative = sum(
        1
        for row in published
        if is_uninformative(build_expectations(row.expected_paths, row.expected_locations), corpus_paths)
    )

    questions: list[tuple[str, list[Any]]] = []
    if args.figures:
        dataset = FigureEvalDataset.model_validate_json(Path(args.figures).read_text(encoding="utf-8"))
        if dataset.corpus_id != args.corpus:
            raise SystemExit(f"{args.figures} is for {dataset.corpus_id}, not {args.corpus}")
        if len(corpus_paths) != 1:
            raise SystemExit(f"figure dataset needs a one-document corpus; {args.corpus} has {len(corpus_paths)}")
        pdf = corpus_paths[0]
        for item in dataset.items[: args.limit or None]:
            locations = [EvalExpectedLocation(path=pdf, unit="page", start=min(item.expected_pages), end=max(item.expected_pages))]
            questions.append((item.question, build_expectations([pdf], locations)))
    for row in published:
        expectations = build_expectations(row.expected_paths, row.expected_locations)
        if not is_uninformative(expectations, corpus_paths):
            questions.append((row.question, expectations))

    typesafe_cfg = cfg.system_one.model_copy(update={"provider": "typesafe", "max_concurrency": int(args.jev_concurrency)})
    laya_cfg = cfg.system_one.model_copy(
        update={"provider": "laya", "laya_base_url": args.laya_base_url, "max_concurrency": int(args.laya_concurrency)}
    )
    logs = {name: ConditionLog() for name in CONDITIONS if name in args.conditions}
    include_vector = not bool(getattr(cfg.indexing, "skip_dense", False))
    fusion = fusion_module.TriBridFusion()
    system_one_reranker = Reranker(cfg.reranking, training_config=cfg.training, gateway_config=cfg)
    laya_before = _proc_stats(args.laya_pid)
    per_query: list[dict[str, Any]] = []

    async def _search(query: str) -> list[ChunkMatch]:
        return await fusion.search(
            [args.corpus],
            query,
            cfg.fusion,
            include_vector=include_vector,
            include_sparse=True,
            include_graph=True,
            top_k=eval_k,
            cache_mode="bypass",
        )

    async with SystemOneClient(typesafe_cfg) as jev_client, SystemOneClient(laya_cfg) as laya_client:
        for index, (query, expectations) in enumerate(questions, start=1):
            fusion_module.Reranker = _CaptureReranker  # type: ignore[misc,assignment]
            none_pipeline = await _search(query)
            fused = _CAPTURED.pop(query)
            row: dict[str, Any] = {"query": query, "fused_candidates": len(fused), "conditions": {}}
            for name, log in logs.items():
                try:
                    if name == "none":
                        ordered, pipeline = fused, none_pipeline
                        log.latencies_s.append(0.0)
                    else:
                        if name == "gateway":
                            ordered = await _rerank_gateway(cfg, query, fused, log)
                        elif name == "jev":
                            ordered = await _rerank_pairwise(jev_client, system_one_reranker, query, fused, log, laya=False)
                        elif name == "jev_batched":
                            ordered = await _rerank_batched(jev_client, system_one_reranker, query, fused, log)
                        else:
                            ordered = await _rerank_pairwise(laya_client, system_one_reranker, query, fused, log, laya=True)
                        _REPLAY[query] = ordered
                        fusion_module.Reranker = _ReplayReranker  # type: ignore[misc,assignment]
                        pipeline = await _search(query)
                except Exception as exc:  # recorded per condition; the run continues
                    log.failures.append(f"q{index}: {type(exc).__name__}: {str(exc)[:300]}")
                    row["conditions"][name] = {"error": str(exc)[:300]}
                    continue
                ranked = [c for c in ordered if c.file_path][:eval_k]
                list_score = score_entry(expectations, ranked, cutoffs=cutoffs, corpus_paths=corpus_paths)
                pipe_ranked = [c for c in pipeline if c.file_path]
                pipe_score = score_entry(expectations, pipe_ranked, cutoffs=cutoffs, corpus_paths=corpus_paths)
                hits = _hits(list_score)
                precise = _precise_hits(list_score, ranked)
                log.list_scores.append(list_score)
                log.pipeline_scores.append(pipe_score)
                log.list_rr.append(list_score.reciprocal_rank)
                log.list_precise_rr.append(_rr(precise))
                log.list_hits.append(hits)
                log.list_precise_hits.append(precise)
                log.pipeline_hits.append(_hits(pipe_score))
                row["conditions"][name] = {
                    "rr": list_score.reciprocal_rank,
                    "precise_rr": _rr(precise),
                    "pipeline_rr": pipe_score.reciprocal_rank,
                    "first_hit_rank": next((r for r, h in enumerate(hits, start=1) if h), None),
                    "rerank_s": round(log.latencies_s[-1], 3),
                }
            per_query.append(row)
            bits = []
            for name in logs:
                rr = row["conditions"].get(name, {}).get("rr")
                bits.append(f"{name}={rr:.2f}" if isinstance(rr, float) else f"{name}=ERR")
            print(f"[{index:2d}/{len(questions)}] {' '.join(bits)}  {query[:60]}", file=sys.stderr, flush=True)
            if args.pace_s > 0:
                await asyncio.sleep(args.pace_s)

    laya_after = _proc_stats(args.laya_pid)
    n = len(questions)
    summary = {name: _summarize(name, log, n) for name, log in logs.items()}
    if "jev" in summary:
        summary["jev"]["cost_usd"] = logs["jev"].input_tokens * JEV_USD_PER_INPUT_TOKEN
    if "jev_batched" in summary:
        summary["jev_batched"]["cost_usd"] = logs["jev_batched"].input_tokens * JEV_USD_PER_INPUT_TOKEN
    paired: dict[str, Any] = {}
    if "gateway" in logs:
        for name in logs:
            if name == "gateway" or len(logs[name].list_rr) != len(logs["gateway"].list_rr):
                continue
            paired[f"{name}_vs_gateway"] = _paired(logs[name].list_rr, logs["gateway"].list_rr)
    if "none" in logs:
        for name in logs:
            if name == "none" or len(logs[name].list_rr) != len(logs["none"].list_rr):
                continue
            paired[f"{name}_vs_none"] = _paired(logs[name].list_rr, logs["none"].list_rr)
    laya_resources: dict[str, Any] | None = None
    if "laya" in logs:
        laya_resources = {
            "max_request_input_tokens": logs["laya"].laya_max_input_tokens,
            "requests_at_or_over_512_tokens": logs["laya"].laya_over_context,
        }
    if laya_before and laya_after:
        laya_resources = {
            **(laya_resources or {}),
            "cpu_s_used": laya_after["cpu_s"] - laya_before["cpu_s"],
            "rss_mib": laya_after["rss_mib"],
            "peak_rss_mib": laya_after["hwm_mib"],
            "cpu_s_per_request": (laya_after["cpu_s"] - laya_before["cpu_s"]) / max(1, logs["laya"].requests)
            if "laya" in logs
            else None,
        }
    return {
        "decision_rule": DECISION_RULE,
        "corpus": args.corpus,
        "corpus_documents": len(corpus_paths),
        "questions_scored": n,
        "published_rows": len(published),
        "published_rows_uninformative": published_uninformative,
        "eval_k": eval_k,
        "reranker_cloud_top_n": int(cfg.reranking.reranker_cloud_top_n),
        "rerank_input_snippet_chars": int(cfg.reranking.rerank_input_snippet_chars),
        "alpha": float(cfg.reranking.tribrid_reranker_alpha),
        "gateway_alias": str(cfg.reranking.reranker_cloud_model),
        "jev_concurrency": int(args.jev_concurrency),
        "laya_concurrency": int(args.laya_concurrency),
        "summary": summary,
        "paired_reciprocal_rank": paired,
        "laya_resources": laya_resources,
        "per_query": per_query,
    }


def _table(result: dict[str, Any]) -> str:
    lines = [
        "| condition | list MRR | list nDCG@10 | hit@1 | hit@3 | hit@5 | hit@10 | precise hit@3 | pipeline MRR | pipeline hit@3 | p50 s | p95 s | requests | input tok | cost $ | failures |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in result["summary"].items():
        lst, pipe, lat = s["list"], s["pipeline"], s["rerank_latency_s"]

        def f(value: Any) -> str:
            return "-" if value is None else f"{value:.3f}"

        lines.append(
            f"| {name} | {f(lst['mrr'])} | {f(lst['ndcg_at_10'])} | {f(lst['hit_at_1'])} | {f(lst['hit_at_3'])} | "
            f"{f(lst['hit_at_5'])} | {f(lst['hit_at_10'])} | {f(lst['precise_hit_at_3'])} | {f(pipe['mrr'])} | "
            f"{f(pipe['hit_at_3'])} | {lat['p50']:.2f} | {lat['p95']:.2f} | {s['requests']} | {s['input_tokens']} | "
            f"{s['cost_usd']:.4f} | {len(s['failures'])} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--figures", default=None, help="page-grounded FigureEvalDataset JSON for a one-document corpus")
    parser.add_argument("--api-base", default="http://127.0.0.1:58012/api")
    parser.add_argument("--gateway-alias", default=None, help="gateway alias when the corpus has none configured")
    parser.add_argument("--laya-base-url", default="http://127.0.0.1:58189")
    parser.add_argument("--laya-pid", type=int, default=None)
    parser.add_argument("--jev-concurrency", type=int, default=16)
    parser.add_argument("--laya-concurrency", type=int, default=4)
    parser.add_argument("--conditions", nargs="+", default=list(CONDITIONS), choices=CONDITIONS)
    parser.add_argument("--limit", type=int, default=0, help="cap figure questions (0 = all)")
    parser.add_argument("--pace-s", type=float, default=0.0, help="sleep between questions")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if "none" not in args.conditions:
        args.conditions = ["none", *args.conditions]
    result = asyncio.run(main_async(args))
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(_table(result))
    print(json.dumps({k: v for k, v in result.items() if k not in {"per_query", "summary"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
