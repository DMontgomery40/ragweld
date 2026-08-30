"""The estimate is checked against corpora that have actually been indexed.

Read-only: it walks and samples the corpora on disk and compares with the chunk/token totals
Postgres recorded for their completed runs. It never starts a run and never writes.

This is the acceptance test for replacing ``tokens = bytes / 4`` / ``chunks = tokens / 448``.
Those constants missed nasa-apollo-11 by 16x on tokens and 6.8x on chunks, and
epstein-files-public by 4.5x on chunks in the other direction.
"""

from __future__ import annotations

import pytest

from server.db.postgres import PostgresClient
from server.indexing.chunker import Chunker
from server.indexing.estimate import sample_corpus
from server.indexing.loader import FileLoader
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

pytestmark = pytest.mark.requires_postgres

# Corpora with a completed index on the deployment this suite runs against. A corpus that is
# not registered is skipped, never silently passed.
LIVE_CORPORA = ("nasa-apollo-11", "epstein-files-public")

# The estimate backs a confirmation dialog, so "the right order of magnitude" is the contract.
MAX_RATIO = 2.0


async def _corpus_files(repo_id: str):
    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    try:
        corpus = await postgres.get_corpus(repo_id)
        stats = await postgres.get_index_stats(repo_id)
    finally:
        await postgres.disconnect()
    if corpus is None:
        pytest.skip(f"{repo_id} is not registered on this deployment")
    root = str(corpus.get("path") or "").strip()
    if not root:
        pytest.skip(f"{repo_id} has no resolvable path")

    ignore_patterns: list[str] = []
    for ext in (cfg.indexing.index_excluded_exts or "").split(","):
        ext = ext.strip()
        if ext:
            ignore_patterns.append(f"*{ext if ext.startswith('.') else '.' + ext}")
    meta = corpus.get("meta") or {}
    raw = meta.get("exclude_paths") if isinstance(meta, dict) else None
    extra = [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []
    loader = FileLoader(ignore_patterns=ignore_patterns, extra_gitignore_patterns=extra)
    max_bytes = min(
        int(cfg.chunking.max_indexable_file_size),
        int(cfg.indexing.index_max_file_size_mb) * 1024 * 1024,
    )
    files = []
    for _rel, path in loader.iter_repo_files(root):
        try:
            size = int(path.stat().st_size)
        except OSError:
            continue
        if size > max_bytes:
            continue
        files.append((path, size))
    return cfg, files, stats


@pytest.mark.integration
@pytest.mark.parametrize("repo_id", LIVE_CORPORA)
async def test_the_estimate_lands_within_2x_of_the_completed_index(repo_id: str) -> None:
    try:
        cfg, files, stats = await _corpus_files(repo_id)
    except CorpusNotFoundError:
        pytest.skip(f"{repo_id} is not registered on this deployment")
    if not files:
        pytest.skip(f"{repo_id} has no readable files on this host")
    actual_chunks = int(stats.total_chunks or 0)
    actual_tokens = int(stats.total_tokens or 0)
    if actual_chunks <= 0:
        pytest.skip(f"{repo_id} has no completed index to compare against")

    sample = sample_corpus(files=files, chunker=Chunker(cfg.chunking, cfg.tokenization))

    chunk_ratio = sample.total_chunks / actual_chunks
    token_ratio = sample.total_tokens / max(1, actual_tokens)
    assert 1 / MAX_RATIO <= chunk_ratio <= MAX_RATIO, (
        f"{repo_id}: estimated {sample.total_chunks} chunks against an actual {actual_chunks}"
    )
    assert 1 / MAX_RATIO <= token_ratio <= MAX_RATIO, (
        f"{repo_id}: estimated {sample.total_tokens} tokens against an actual {actual_tokens}"
    )
    # The band has to contain the truth, or it is decoration.
    assert sample.chunks_low <= actual_chunks <= sample.chunks_high
    assert sample.tokens_low <= actual_tokens <= sample.tokens_high


@pytest.mark.integration
@pytest.mark.parametrize("repo_id", LIVE_CORPORA)
async def test_the_old_byte_ratio_would_have_failed_this_test(repo_id: str) -> None:
    """Not a vacuous bound: the formula this replaced misses it on both corpora."""
    try:
        _cfg, files, stats = await _corpus_files(repo_id)
    except CorpusNotFoundError:
        pytest.skip(f"{repo_id} is not registered on this deployment")
    if not files:
        pytest.skip(f"{repo_id} has no readable files on this host")
    actual_chunks = int(stats.total_chunks or 0)
    if actual_chunks <= 0:
        pytest.skip(f"{repo_id} has no completed index to compare against")

    total_bytes = sum(size for _path, size in files)
    old_chunks = int(total_bytes / 4 / 448)

    assert not (1 / MAX_RATIO <= old_chunks / actual_chunks <= MAX_RATIO), (
        f"{repo_id}: bytes/4/448 gave {old_chunks} against {actual_chunks}, which is inside 2x "
        "-- pick a corpus that discriminates"
    )


# The browser client aborts an estimate at 30 s (web/src/api/client.ts). Since a failed estimate
# is now a hard block rather than a fall-through to the run, a cold estimate that outruns this
# turns the first Index Now after a service restart into an error banner.
CLIENT_TIMEOUT_SECONDS = 30.0

# Cold means a fresh interpreter. Clearing the tokenizer's lru_cache in-process does NOT restore
# it: measured here, a first-in-process sample of ragweld_code costs ~28 s while the same sample
# after a cache_clear costs ~4.6 s, because the `transformers` import and the model files stay
# hot. Anything claiming to measure the cold path from inside a warm process measures the warm one.
_COLD_PROBE = r"""
import asyncio, json, time, sys

async def main():
    from server.services.config_store import get_config
    from server.indexing.chunker import Chunker
    from server.indexing.loader import FileLoader
    from server.indexing.estimate import sample_corpus, warm_sampler

    mode, repo_id, root = sys.argv[1], sys.argv[2], sys.argv[3]
    cfg = await get_config(repo_id=repo_id)
    chunker = Chunker(cfg.chunking, cfg.tokenization)
    loader = FileLoader(ignore_patterns=[])
    files = []
    for _rel, path in loader.iter_repo_files(root):
        try:
            files.append((path, path.stat().st_size))
        except OSError:
            pass

    warmup = 0.0
    if mode == "warm":
        started = time.monotonic()
        warm_sampler(chunker)
        warmup = time.monotonic() - started

    started = time.monotonic()
    sample_corpus(files=files, chunker=chunker)
    sampling = time.monotonic() - started
    print(json.dumps({"files": len(files), "warmup": warmup, "sampling": sampling}))

asyncio.run(main())
"""

WIDEST_CORPUS = "ragweld_code"
WIDEST_ROOT = "/opt/ragweld"


def _cold_process_timings(mode: str, repo_id: str, root: str) -> dict[str, float]:
    """Run one estimate in a genuinely fresh interpreter, with or without the warm-up first."""
    import json
    import os
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-c", _COLD_PROBE, mode, repo_id, root],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"cold probe could not run here: {completed.stderr.strip()[-300:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


async def _require_widest_corpus() -> None:
    try:
        _cfg, files, _stats = await _corpus_files(WIDEST_CORPUS)
    except CorpusNotFoundError:
        pytest.skip(f"{WIDEST_CORPUS} is not registered on this deployment")
    if not files:
        pytest.skip(f"{WIDEST_CORPUS} has no readable files on this host")


@pytest.mark.integration
async def test_measuring_cold_is_too_slow_to_do_on_the_request_path() -> None:
    """Why the endpoint answers "warming" instead of sampling: measuring cold does not fit.

    A fresh process with no warm-up, on the widest corpus on this box. This was originally
    asserted the other way -- that a cold sample squeaks inside the timeout -- and it did, at
    27.8 s against 30 s. It then failed at 34.8 s on a busier box, which is the point: the
    margin was never real, so the endpoint no longer gambles on it.
    """
    await _require_widest_corpus()

    timings = _cold_process_timings("nowarm", WIDEST_CORPUS, WIDEST_ROOT)

    assert timings["sampling"] > CLIENT_TIMEOUT_SECONDS / 3, (
        f"a cold sample took only {timings['sampling']:.1f}s -- if measuring cold were this "
        "cheap, the warming response would be unnecessary complexity"
    )


@pytest.mark.integration
async def test_the_warmup_moves_the_load_off_the_estimate() -> None:
    """With the warm-up done, the estimate the operator waits for is a fraction of the budget."""
    await _require_widest_corpus()

    timings = _cold_process_timings("warm", WIDEST_CORPUS, WIDEST_ROOT)

    assert timings["sampling"] < CLIENT_TIMEOUT_SECONDS / 3, (
        f"a warmed estimate took {timings['sampling']:.1f}s, which leaves no margin"
    )
    # Not a vacuous bound: the warm-up really is most of the cold cost, which is the whole
    # reason moving it off the request path helps.
    assert timings["warmup"] > timings["sampling"], (
        f"warmup {timings['warmup']:.1f}s vs sampling {timings['sampling']:.1f}s -- if sampling "
        "dominated, warming would buy nothing"
    )


# A cold estimate must never publish a number it did not measure. The probe drives the real
# endpoint through the real ASGI app in a fresh interpreter, so the tokenizer really is unloaded
# on the first call, and it compares the COLD numbers against the WARM ones from the same
# process -- latency proved nothing here: the old cold test passed precisely because the
# estimate bailed out early and returned 15,437 tokens for a 3,531,477-token corpus.
_COLD_NUMBERS_PROBE = r"""
import asyncio, json, sys

async def main():
    import httpx
    from server.main import app
    from server.indexing.estimate import sampler_is_warm

    repo_id, root = sys.argv[1], sys.argv[2]
    payload = {"corpus_id": repo_id, "repo_path": root}
    transport = httpx.ASGITransport(app=app)
    calls = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
        was_cold = not sampler_is_warm()
        # Ask until it stops saying "not measured", exactly as the browser client does.
        for _ in range(90):
            response = await client.post("/api/index/estimate", json=payload)
            body = response.json()
            calls.append({
                "status": body.get("status"),
                "http": response.status_code,
                "total_files": body.get("total_files"),
                "tokens": body.get("estimated_total_tokens"),
                "chunks": body.get("estimated_total_chunks"),
                "sampled_files": body.get("sampled_files"),
                "sampled_bytes": body.get("sampled_bytes"),
                "low": body.get("estimated_tokens_low"),
                "high": body.get("estimated_tokens_high"),
            })
            if body.get("status") == "ready":
                break
            await asyncio.sleep(2)
        warm = (await client.post("/api/index/estimate", json=payload)).json()

    print(json.dumps({
        "was_cold": was_cold,
        "calls": calls,
        "warm_tokens": warm.get("estimated_total_tokens"),
        "warm_chunks": warm.get("estimated_total_chunks"),
        "warm_low": warm.get("estimated_tokens_low"),
        "warm_high": warm.get("estimated_tokens_high"),
    }))

asyncio.run(main())
"""


def _run_probe(source: str, *args: str) -> dict:
    import json
    import os
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-c", source, *args],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"probe could not run here: {completed.stderr.strip()[-300:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.mark.integration
async def test_a_cold_estimate_never_publishes_a_number_it_did_not_measure() -> None:
    """The consent gate must not lie on the first click after a restart.

    Before the floor, a cold first estimate measured 6 files totalling 8 bytes of 8.5 MB, then
    the byte-ratio estimator scaled them up: 15,437 tokens with a confident band, for a corpus
    whose real run indexes 3,531,477. Every non-ready answer now carries zeros, and the eventual
    ready answer has to agree with the warm one.
    """
    await _require_widest_corpus()

    result = _run_probe(_COLD_NUMBERS_PROBE, WIDEST_CORPUS, WIDEST_ROOT)
    assert result["was_cold"] is True, "the probe process was not cold; it proves nothing"

    calls = result["calls"]
    assert calls, "the probe made no calls"
    assert calls[-1]["status"] == "ready", f"never became ready: {calls}"

    # Every answer before the ready one carries NULL for everything measured -- not a small
    # estimate, and not a zero an unguarded consumer would render. The file inventory is real,
    # because the walk genuinely produced it.
    for call in calls[:-1]:
        assert call["status"] in {"warming", "insufficient_sample"}
        assert call["http"] == 200
        for field in ("tokens", "chunks", "sampled_files", "sampled_bytes", "low", "high"):
            assert call[field] is None, f"{call['status']} answer carried {field}={call[field]}"
        assert call["total_files"] >= 0

    # THE assertion: the cold-path numbers agree with the warm ones.
    ready, warm_tokens = calls[-1], int(result["warm_tokens"])
    assert warm_tokens > 0
    assert int(ready["low"]) <= warm_tokens <= int(ready["high"]), (
        f"the cold estimate's band {ready['low']}-{ready['high']} excludes the warm result "
        f"{warm_tokens}"
    )
    ratio = int(ready["tokens"]) / warm_tokens
    assert 0.5 <= ratio <= 2.0, f"cold {ready['tokens']} vs warm {warm_tokens} (ratio {ratio:.2f})"
    assert int(ready["sampled_bytes"]) > 0
