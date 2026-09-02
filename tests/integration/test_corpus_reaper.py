"""The test-corpus reaper deletes stale leaks and nothing else.

Directions, against live Postgres:
- a stale row with a test-corpus prefix is reaped, together with the staging rows
  (``__staging__<corpus>__<run>``) its dead runs left, exactly as the production
  ``delete_corpus_with_data`` cascade does;
- a fresh row with the same prefix is kept (a concurrent session may own it), its
  staging rows with it, and no non-test row — the operator's real corpora
  included — is ever touched;
- an aged-out row a session is still USING is kept: a session that runs longer
  than the age threshold has an old parent row and a live run under it, seen
  either as a fresh staging row or as an unexpired index-run fence. Both rails
  release once the run is provably dead.

Only prefixed (reapable) rows are ever created here, so a hard crash mid-test
cannot leave behind a row the reaper itself would not later clean up.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from server.db.postgres import PostgresClient
from server.indexing.generations import IndexRunFence, staging_repo_id
from tests.corpus_reaper import (
    INDEX_FENCE_LEASE_SECONDS,
    REAP_MAX_AGE_SECONDS,
    TEST_CORPUS_PREFIX,
    is_test_corpus_id,
    reap_stale_test_corpora,
)
from tests.service_requirements import require_env


def test_real_corpus_names_are_not_reap_eligible() -> None:
    # The operator's real corpora (as seen in the live registry) must never match a
    # test-corpus prefix -- this fixture deletes from live Postgres on every run.
    for real in ("ragweld_code", "recall_default", "nasa-apollo-11", "epstein-files-public"):
        assert not is_test_corpus_id(real), real
    assert is_test_corpus_id(f"{TEST_CORPUS_PREFIX}anything")


async def _present(dsn: str, repo_ids: list[str]) -> set[str]:
    """Which of ``repo_ids`` have a ``corpora`` row, read raw: the registry listing
    (``list_corpora``) hides staging rows, so it cannot prove a staging row's fate."""
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT repo_id FROM corpora WHERE repo_id = ANY($1::text[]);", repo_ids)
    finally:
        await conn.close()
    return {str(row["repo_id"]) for row in rows}


async def _set_created_at(dsn: str, repo_id: str, when: datetime) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("UPDATE corpora SET created_at = $2 WHERE repo_id = $1;", repo_id, when)
    finally:
        await conn.close()


async def _database_now(dsn: str) -> datetime:
    """The database clock -- fence heartbeats are written from it, so they are compared to it."""
    conn = await asyncpg.connect(dsn)
    try:
        now = await conn.fetchval("SELECT now();")
    finally:
        await conn.close()
    assert isinstance(now, datetime)
    return now


async def _write_index_fence(dsn: str, repo_id: str, raw_fence: object) -> None:
    """Put ``raw_fence`` on ``corpora.meta.index_run``, where the production fence lives.

    Written as SQL rather than through ``acquire_index_fence``: that path refuses to fence a
    corpus whose generation manifest cannot be read, and these rows have no manifest. The
    durable shape is what the reaper reads, so the durable shape is what the test writes.
    """
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "UPDATE corpora SET meta = COALESCE(meta, '{}'::jsonb) || "
            "jsonb_build_object('index_run', $2::jsonb) WHERE repo_id = $1;",
            repo_id,
            json.dumps(raw_fence),
        )
    finally:
        await conn.close()


def _fence(*, run_id: str, heartbeat_at: datetime, started_at: datetime) -> dict:
    return IndexRunFence(
        run_id=run_id,
        owner="pytest:0",
        started_at=started_at,
        heartbeat_at=heartbeat_at,
        staged_graph_repo_id=None,
        staged_qdrant_collection=None,
    ).model_dump(mode="json")


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_reaper_deletes_stale_test_corpora_and_spares_fresh_and_real() -> None:
    dsn = require_env("POSTGRES_DSN")
    pg = PostgresClient(dsn)
    await pg.connect()

    suffix = uuid.uuid4().hex[:8]
    stale = f"{TEST_CORPUS_PREFIX}reaper_stale_{suffix}"  # prefixed + old -> reaped
    fresh = f"{TEST_CORPUS_PREFIX}reaper_fresh_{suffix}"  # prefixed + new -> kept
    # A dead run's staging row under each. The stale corpus's staging row is aged with
    # its parent: a FRESH staging row means a live run is writing a generation into the
    # corpus, and the reaper now refuses the parent for exactly that reason (a session
    # outliving the age threshold used to be reaped out from under itself). The fresh
    # corpus's staging row stays fresh and must survive with its parent.
    stale_staging = staging_repo_id(stale, uuid.uuid4().hex)
    fresh_staging = staging_repo_id(fresh, uuid.uuid4().hex)

    try:
        # Snapshot the non-test rows present now; none may be deleted by the reaper.
        non_test_before = {
            str(row.get("repo_id"))
            for row in await pg.list_corpora()
            if not is_test_corpus_id(str(row.get("repo_id") or ""))
        }

        await pg.upsert_corpus(stale, name=stale, root_path=".")
        await pg.upsert_corpus(fresh, name=fresh, root_path=".")
        await pg.upsert_corpus(stale_staging, name=stale_staging, root_path=".")
        await pg.upsert_corpus(fresh_staging, name=fresh_staging, root_path=".")
        assert await _present(dsn, [stale_staging, fresh_staging]) == {stale_staging, fresh_staging}
        old = datetime.now(UTC) - timedelta(seconds=REAP_MAX_AGE_SECONDS + 3600)
        await _set_created_at(dsn, stale, old)
        await _set_created_at(dsn, stale_staging, old)
        # `fresh` and its staging row keep their default created_at (now).

        reaped = await reap_stale_test_corpora(dsn)

        assert stale in reaped, reaped
        assert fresh not in reaped, reaped

        remaining = {str(row.get("repo_id")) for row in await pg.list_corpora()}
        assert stale not in remaining
        assert fresh in remaining
        staging_left = await _present(dsn, [stale_staging, fresh_staging])
        assert stale_staging not in staging_left, (
            "the reaped corpus's staging row survived: the reaper's cascade lags "
            "delete_corpus_with_data's staging sweep"
        )
        assert fresh_staging in staging_left, "a fresh corpus's staging row was swept"
        # Every pre-existing non-test corpus survived the reap.
        assert non_test_before <= remaining, non_test_before - remaining
    finally:
        for cid in (stale, fresh, stale_staging, fresh_staging):
            with contextlib.suppress(Exception):
                await pg.delete_corpus_with_data(cid)
        await pg.disconnect()


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_reaper_spares_an_aged_corpus_a_live_run_is_still_staging_into() -> None:
    """A long session's corpus ages out while its run is still indexing into it.

    Eligibility used to be the parent row's age alone, so another session's reaper could
    delete the corpus (and its config, chunks and documents) out from under a run that was
    writing a generation at that moment. A staging row younger than the age threshold is that
    run, and it now keeps its parent -- until the run is over and its residue ages out too.
    """
    dsn = require_env("POSTGRES_DSN")
    pg = PostgresClient(dsn)
    await pg.connect()

    suffix = uuid.uuid4().hex[:8]
    corpus = f"{TEST_CORPUS_PREFIX}reaper_staging_{suffix}"
    staging = staging_repo_id(corpus, uuid.uuid4().hex)
    old = datetime.now(UTC) - timedelta(seconds=REAP_MAX_AGE_SECONDS + 3600)
    try:
        await pg.upsert_corpus(corpus, name=corpus, root_path=".")
        await pg.upsert_corpus(staging, name=staging, root_path=".")
        await _set_created_at(dsn, corpus, old)
        # The staging row keeps `now()`: a generation is being written right now.

        reaped = await reap_stale_test_corpora(dsn)
        assert corpus not in reaped, "an aged corpus with a live run staging into it was reaped"
        assert await _present(dsn, [corpus, staging]) == {corpus, staging}

        # The run finishes and its residue ages out: nothing is fresh, so the corpus goes.
        await _set_created_at(dsn, staging, old)
        reaped = await reap_stale_test_corpora(dsn)
        assert corpus in reaped, reaped
        assert await _present(dsn, [corpus, staging]) == set()
    finally:
        for cid in (corpus, staging):
            with contextlib.suppress(Exception):
                await pg.delete_corpus_with_data(cid)
        await pg.disconnect()


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_reaper_spares_an_aged_corpus_whose_index_fence_is_still_leased() -> None:
    """The durable index-run fence is the other proof that a run owns the corpus.

    A run that has claimed the fence but not yet written a staging row is just as live, so the
    reaper reads ``corpora.meta.index_run`` and applies the production staleness predicate
    against the DATABASE clock the heartbeats come from. A fence that does not validate cannot
    prove the run is dead, so it counts as held too.
    """
    dsn = require_env("POSTGRES_DSN")
    pg = PostgresClient(dsn)
    await pg.connect()

    suffix = uuid.uuid4().hex[:8]
    corpus = f"{TEST_CORPUS_PREFIX}reaper_fence_{suffix}"
    old = datetime.now(UTC) - timedelta(seconds=REAP_MAX_AGE_SECONDS + 3600)
    try:
        await pg.upsert_corpus(corpus, name=corpus, root_path=".")
        await _set_created_at(dsn, corpus, old)
        db_now = await _database_now(dsn)
        run_id = uuid.uuid4().hex

        # 1. A heartbeat from a moment ago: the run holds the fence.
        await _write_index_fence(
            dsn, corpus, _fence(run_id=run_id, heartbeat_at=db_now, started_at=db_now)
        )
        assert corpus not in await reap_stale_test_corpora(dsn)
        assert await _present(dsn, [corpus]) == {corpus}

        # 2. A fence that will not validate: unknown, so still held.
        await _write_index_fence(dsn, corpus, {"run_id": "", "owner": "pytest:0"})
        assert corpus not in await reap_stale_test_corpora(dsn)
        assert await _present(dsn, [corpus]) == {corpus}

        # 3. A heartbeat older than the lease: the worker is gone and the corpus is reapable.
        dead = db_now - timedelta(seconds=INDEX_FENCE_LEASE_SECONDS + 60)
        await _write_index_fence(
            dsn, corpus, _fence(run_id=run_id, heartbeat_at=dead, started_at=dead)
        )
        reaped = await reap_stale_test_corpora(dsn)
        assert corpus in reaped, reaped
        assert await _present(dsn, [corpus]) == set()
    finally:
        with contextlib.suppress(Exception):
            await pg.delete_corpus_with_data(corpus)
        await pg.disconnect()
