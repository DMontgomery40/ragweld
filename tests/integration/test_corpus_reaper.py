"""The test-corpus reaper deletes stale leaks and nothing else.

Two directions, against live Postgres:
- a stale row with a test-corpus prefix is reaped, together with the staging rows
  (``__staging__<corpus>__<run>``) its dead runs left, exactly as the production
  ``delete_corpus_with_data`` cascade does;
- a fresh row with the same prefix is kept (a concurrent session may own it), its
  staging rows with it, and no non-test row — the operator's real corpora
  included — is ever touched.

Only prefixed (reapable) rows are ever created here, so a hard crash mid-test
cannot leave behind a row the reaper itself would not later clean up.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from server.db.postgres import PostgresClient
from server.indexing.generations import staging_repo_id
from tests.corpus_reaper import (
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


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_reaper_deletes_stale_test_corpora_and_spares_fresh_and_real() -> None:
    dsn = require_env("POSTGRES_DSN")
    pg = PostgresClient(dsn)
    await pg.connect()

    suffix = uuid.uuid4().hex[:8]
    stale = f"{TEST_CORPUS_PREFIX}reaper_stale_{suffix}"  # prefixed + old -> reaped
    fresh = f"{TEST_CORPUS_PREFIX}reaper_fresh_{suffix}"  # prefixed + new -> kept
    # A dead run's staging row under each. Both rows are FRESH (created now), so
    # the age rail alone keeps them: the stale corpus's one may only vanish
    # through the cascade that reaps its corpus, the fresh corpus's must stay.
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
        # `fresh` keeps its default created_at (now).

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
