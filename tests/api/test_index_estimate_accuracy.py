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


# A cold estimate must ANSWER, not block. The probe drives the real endpoint through the real
# ASGI app in a fresh interpreter, so the tokenizer really is unloaded on the first call.
_WARMING_PROBE = r"""
import asyncio, json, time, sys

async def main():
    import httpx
    from server.main import app
    from server.indexing.estimate import sampler_is_warm, warm_sampler
    from server.services.config_store import get_config
    from server.indexing.chunker import Chunker

    repo_id, root = sys.argv[1], sys.argv[2]
    payload = {"corpus_id": repo_id, "repo_path": root}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        cold_was_warm = sampler_is_warm()
        started = time.monotonic()
        first = await client.post("/api/index/estimate", json=payload)
        first_seconds = time.monotonic() - started
        first_body = first.json()

        # The endpoint kicks the warm-up off in the background; wait for it the way the browser
        # does, then ask again.
        cfg = await get_config(repo_id=repo_id)
        await asyncio.to_thread(warm_sampler, Chunker(cfg.chunking, cfg.tokenization))
        second = await client.post("/api/index/estimate", json=payload)
        second_body = second.json()

    print(json.dumps({
        "cold_was_warm": cold_was_warm,
        "first_status": first_body.get("status"),
        "first_seconds": first_seconds,
        "first_remaining": first_body.get("warmup_seconds_remaining"),
        "first_files": first_body.get("total_files"),
        "first_chunks": first_body.get("estimated_total_chunks"),
        "second_status": second_body.get("status"),
        "second_chunks": second_body.get("estimated_total_chunks"),
        "second_tokens": second_body.get("estimated_total_tokens"),
    }))

asyncio.run(main())
"""


@pytest.mark.integration
async def test_a_cold_estimate_answers_warming_instead_of_blocking() -> None:
    """The operator's first Index Now after a restart gets an answer, not a 30 s gamble."""
    await _require_widest_corpus()

    import json
    import os
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-c", _WARMING_PROBE, WIDEST_CORPUS, WIDEST_ROOT],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"warming probe could not run here: {completed.stderr.strip()[-300:]}")
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["cold_was_warm"] is False, "the probe process was not cold; it proves nothing"
    # Answers fast, and says why it has no numbers.
    assert result["first_status"] == "warming"
    assert result["first_seconds"] < 2.0, f"the warming answer took {result['first_seconds']:.1f}s"
    assert result["first_chunks"] == 0
    assert float(result["first_remaining"] or 0) > 0
    # It still counted what is cheap to count, so the wait is not information-free.
    assert int(result["first_files"]) > 0

    # Once warm, the same request is a real estimate.
    assert result["second_status"] == "ready"
    assert int(result["second_chunks"]) > 0
    assert int(result["second_tokens"]) > 0
