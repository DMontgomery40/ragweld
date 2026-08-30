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
