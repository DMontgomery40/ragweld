"""The commit-outcome decision after an interrupted promotion await (pure function, no stores).

Codex pass 8 #2: a second cancellation while the promotion transaction is
still pending must never be read as a definitive negative.
"""

from __future__ import annotations

from datetime import UTC, datetime

from server.api.index import _classify_commit_outcome
from server.indexing.generations import (
    DeletionIncompleteError,
    DeletionTombstone,
    IndexFenceLostError,
    PersistedStateCorruptError,
)


def test_pending_transaction_is_unknown_whatever_the_manifest_says() -> None:
    for manifest in (True, False, None):
        assert _classify_commit_outcome(
            promote_done=False,
            promote_cancelled=False,
            promote_exception=None,
            manifest_names_run=manifest,
        ) == (False, True)


def test_returned_transaction_is_committed() -> None:
    assert _classify_commit_outcome(
        promote_done=True, promote_cancelled=False, promote_exception=None, manifest_names_run=None
    ) == (True, False)


def test_refusals_before_writing_are_definitive_negatives() -> None:
    tombstone = DeletionTombstone(created_at=datetime.now(UTC), revision="r" * 8)
    for exc in (
        IndexFenceLostError("c", "run", None),
        DeletionIncompleteError("c", tombstone),
        PersistedStateCorruptError("c", "generation", {"bad": 1}),
    ):
        assert _classify_commit_outcome(
            promote_done=True,
            promote_cancelled=False,
            promote_exception=exc,
            manifest_names_run=None,
        ) == (False, False)


def test_other_failures_defer_to_the_manifest() -> None:
    err = ConnectionResetError("connection lost after COMMIT")
    assert _classify_commit_outcome(
        promote_done=True, promote_cancelled=False, promote_exception=err, manifest_names_run=True
    ) == (True, False)
    assert _classify_commit_outcome(
        promote_done=True, promote_cancelled=False, promote_exception=err, manifest_names_run=False
    ) == (False, False)
    assert _classify_commit_outcome(
        promote_done=True, promote_cancelled=False, promote_exception=err, manifest_names_run=None
    ) == (False, True)


def test_cancelled_transaction_task_defers_to_the_manifest() -> None:
    assert _classify_commit_outcome(
        promote_done=True, promote_cancelled=True, promote_exception=None, manifest_names_run=None
    ) == (False, True)
    assert _classify_commit_outcome(
        promote_done=True, promote_cancelled=True, promote_exception=None, manifest_names_run=True
    ) == (True, False)
