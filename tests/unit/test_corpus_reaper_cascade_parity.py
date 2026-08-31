"""Contract: the reaper's Postgres cascade stays in lockstep with the real delete.

``tests/corpus_reaper.reap_stale_test_corpora`` deliberately inlines the delete
cascade of ``PostgresClient.delete_corpus_with_data`` (it uses a raw one-shot
asyncpg connection to avoid the shared-pool event-loop trap, so it cannot just
call the client). That intentional duplication is a drift risk: if a future
schema change adds a ``repo_id``-keyed table to the production delete but not the
reaper, the reaper silently leaves orphan rows for every reaped test corpus.

This guards the duplication by source introspection — no database — asserting the
ordered list of ``DELETE FROM <table> WHERE repo_id`` statements is identical in
both. It fails the moment either side gains, drops, or reorders a table.
"""

from __future__ import annotations

import inspect
import re

from server.db.postgres import PostgresClient
from tests.corpus_reaper import reap_stale_test_corpora

_DELETE_BY_REPO = re.compile(r"DELETE\s+FROM\s+([a-z_]+)\s+WHERE\s+repo_id", re.IGNORECASE)


def _cascade_tables(func) -> list[str]:
    return _DELETE_BY_REPO.findall(inspect.getsource(func))


def test_reaper_cascade_matches_the_production_corpus_delete() -> None:
    reaper = _cascade_tables(reap_stale_test_corpora)
    production = _cascade_tables(PostgresClient.delete_corpus_with_data)

    assert reaper, "no DELETE ... WHERE repo_id found in the reaper — source or regex drifted"
    assert production, (
        "no DELETE ... WHERE repo_id found in delete_corpus_with_data — source or regex drifted"
    )
    assert reaper == production, (
        "the reaper's Postgres cascade has drifted from "
        "PostgresClient.delete_corpus_with_data; a repo_id-keyed table was added, dropped, or "
        "reordered in one but not the other, which would leak orphan rows for every reaped "
        "test corpus. Keep the two cascades identical (same tables, same order).\n"
        f"  reaper:     {reaper}\n"
        f"  production: {production}"
    )
