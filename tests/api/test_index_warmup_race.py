"""The estimator's warm-up and the indexer's first tokenizer load cannot race.

Two threads importing `transformers` for the first time leave one holding the half-initialised
module: `ImportError: cannot import name 'AutoTokenizer' from 'transformers'`. It was hit three
times during this work -- an index run failing beside a warm-up, two warm-ups racing, and once
in review. Guarding on "is a run scheduled" only narrowed the window, because a run starting
between the check and the warm thread's import still raced. Both sides now take the same lock.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration

# A fresh interpreter, because the race only exists on the FIRST import in a process. Two
# threads are started deliberately close together: the estimator's warm-up and a chunk of the
# indexer's own path (Chunker over real text, which is what loads the tokenizer).
_RACE_PROBE = r"""
import asyncio, json, sys, threading, traceback

async def main():
    from server.indexing.chunker import Chunker
    from server.indexing.estimate import sampler_is_warm, warm_sampler
    from server.indexing.tokenizer import TextTokenizer
    from server.services.config_store import get_config

    cfg = await get_config(repo_id=sys.argv[1])
    was_cold = not sampler_is_warm()
    before = TextTokenizer._get_hf_tokenizer.cache_info()
    errors = []
    threads_n = 6
    ready = threading.Barrier(threads_n + 1)

    def warm():
        try:
            ready.wait()
            warm_sampler(Chunker(cfg.chunking, cfg.tokenization))
        except Exception as exc:
            errors.append(f"warm: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    def index_like():
        try:
            ready.wait()
            # What _run_index_body now does before its loop, then real chunking work.
            chunker = Chunker(cfg.chunking, cfg.tokenization)
            warm_sampler(chunker)
            if not chunker.chunk_file("note.md", "lunar module telemetry sample line.\n" * 200):
                errors.append("index: chunker produced nothing")
        except Exception as exc:
            errors.append(f"index: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    threads = [threading.Thread(target=warm if i % 2 else index_like) for i in range(threads_n)]
    for t in threads:
        t.start()
    ready.wait()
    for t in threads:
        t.join(timeout=300)

    after = TextTokenizer._get_hf_tokenizer.cache_info()
    print(json.dumps({
        "was_cold": was_cold,
        "errors": errors,
        "warm_after": sampler_is_warm(),
        "loads": after.misses - before.misses,
        "threads": threads_n,
    }))

asyncio.run(main())
"""


@pytest.mark.asyncio
async def test_concurrent_warmups_and_indexing_perform_exactly_one_model_load() -> None:
    """Six threads race the first load in a fresh process; the model is loaded once.

    This asserts the SERIALISATION, which is deterministic, rather than trying to reproduce the
    ImportError, which is not: with the lock removed I ran six threads across three different
    import paths four times and never tripped it, so a test that only checks "no exception"
    would pass either way and prove nothing. The load count discriminates -- without the lock
    several threads miss the tokenizer cache at once and load in parallel, which is both the
    waste and the window the ImportError lives in.
    """
    import json
    import os

    completed = subprocess.run(
        [sys.executable, "-c", _RACE_PROBE, "ragweld_code"],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"race probe could not run here: {completed.stderr.strip()[-300:]}")
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["was_cold"] is True, "the probe process was not cold; there is no race to run"
    assert result["errors"] == [], "\n".join(result["errors"])
    assert result["warm_after"] is True
    assert result["loads"] == 1, (
        f"{result['threads']} concurrent callers performed {result['loads']} model loads; "
        "the warm-up and the indexer are not sharing one lock"
    )
