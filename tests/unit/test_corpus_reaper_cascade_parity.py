"""Contract: the reaper's Postgres cascade stays in lockstep with the real delete.

``tests/corpus_reaper.reap_stale_test_corpora`` deliberately inlines the delete
cascade of ``PostgresClient.delete_corpus_with_data`` (it uses a raw one-shot
asyncpg connection to avoid the shared-pool event-loop trap, so it cannot just
call the client). That intentional duplication is a drift risk: if a future
schema change adds a ``repo_id``-keyed table to the production delete but not the
reaper, the reaper silently leaves orphan rows for every reaped test corpus.

This guards the duplication by source introspection — no database — asserting the
ordered sequence of cascade steps is identical in both: every
``DELETE FROM <table> WHERE repo_id`` statement AND every shared
``_delete_corpus_*`` helper call (the staging-row sweep lives in one such helper,
which the reaper calls with its raw connection). It fails the moment either side
gains, drops, or reorders a step.
"""

from __future__ import annotations

import inspect
import re

from server.db.postgres import PostgresClient
from tests.corpus_reaper import reap_stale_test_corpora

# One regex, two alternatives, so the ORDER of table deletes relative to helper
# calls is compared too (the staging sweep runs before the exact-id deletes).
_CASCADE_STEP = re.compile(
    r"DELETE\s+FROM\s+([a-z_]+)\s+WHERE\s+repo_id|await\s+(_delete_corpus_[a-z_]+)\(",
    re.IGNORECASE,
)


def _cascade_steps(func) -> list[str]:
    return [table or f"{helper}()" for table, helper in _CASCADE_STEP.findall(inspect.getsource(func))]


def test_reaper_cascade_matches_the_production_corpus_delete() -> None:
    reaper = _cascade_steps(reap_stale_test_corpora)
    production = _cascade_steps(PostgresClient.delete_corpus_with_data)

    assert reaper, "no cascade step found in the reaper — source or regex drifted"
    assert production, (
        "no cascade step found in delete_corpus_with_data — source or regex drifted"
    )
    assert "_delete_corpus_staging_rows()" in production, (
        "delete_corpus_with_data no longer sweeps staging rows through the shared helper; "
        "update this contract deliberately, not by accident"
    )
    assert reaper == production, (
        "the reaper's Postgres cascade has drifted from "
        "PostgresClient.delete_corpus_with_data; a repo_id-keyed table or a shared "
        "_delete_corpus_* helper call was added, dropped, or reordered in one but not the "
        "other, which would leak orphan rows for every reaped test corpus. Keep the two "
        "cascades identical (same steps, same order).\n"
        f"  reaper:     {reaper}\n"
        f"  production: {production}"
    )
