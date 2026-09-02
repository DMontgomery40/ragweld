"""The reaper's prefix rail: what counts as test residue, in every store's naming.

The reaper deletes from the operator's live Postgres, Neo4j and Qdrant on every
pytest session, so this pins the classification in both directions and in every
form a corpus id takes on the way through the stores:

- the plain registry id (``pytest_x``, and the names of the tests that leaked);
- its staged Neo4j/Postgres generation (``__staging__<corpus>__<run>``);
- its Qdrant collection prefix (``ragweld_chunks_<slug>_<hash>``).

The operator's real corpora must be rejected in all three forms.
"""

from __future__ import annotations

import pytest

from server.indexing.generations import staging_repo_id
from server.retrieval.qdrant_store import corpus_collection_prefix
from tests.corpus_reaper import (
    TEST_CORPUS_PREFIXES,
    is_test_corpus_id,
    qdrant_test_collection_prefixes,
    staged_corpus_of,
)

OPERATOR_CORPORA = ("epstein-files-public", "nasa-apollo-11", "ragweld_code", "recall_default")
RUN_ID = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    "repo_id",
    [
        "promoted-lane-x",  # tests/integration/test_index_promoted_lane.py (pre-rename leak)
        "relroot_x",  # tests/api/test_index_relative_corpus_root.py (pre-rename leak)
        "pytest_x",
        "test_x",
        "test-x",
        "recall_test_x",
        "ragweld-exhaustive-x",
        "heartbeat-x",
    ],
)
def test_test_corpus_names_are_reap_eligible_plain_and_staged(repo_id: str) -> None:
    assert is_test_corpus_id(repo_id), repo_id
    assert is_test_corpus_id(staging_repo_id(repo_id, RUN_ID)), (
        "a staged generation of a test corpus is test residue too"
    )


@pytest.mark.parametrize("repo_id", OPERATOR_CORPORA)
def test_operator_corpora_are_never_reap_eligible_plain_or_staged(repo_id: str) -> None:
    assert not is_test_corpus_id(repo_id), repo_id
    assert not is_test_corpus_id(staging_repo_id(repo_id, RUN_ID)), repo_id


@pytest.mark.parametrize(
    "repo_id",
    [
        "",
        "__staging____",  # empty corpus and run
        "__staging__pytest_x",  # no run separator: not a staging id at all
        "neo4j-live",
        "__staging__neo4j-live__run",  # staged, but the corpus has no test prefix
        "Pytest_x",  # prefixes are case-sensitive on purpose
    ],
)
def test_unparseable_or_unprefixed_names_are_kept(repo_id: str) -> None:
    assert not is_test_corpus_id(repo_id), repo_id


def test_staged_corpus_of_takes_everything_before_the_last_separator() -> None:
    # Run ids never contain ``__`` (delete_staged_graphs and the Postgres staging
    # sweep rely on the same fact), so a corpus id may.
    assert staged_corpus_of(staging_repo_id("a__b", "run")) == "a__b"
    assert staged_corpus_of(staging_repo_id("pytest_x", RUN_ID)) == "pytest_x"
    assert staged_corpus_of("pytest_x") is None
    assert staged_corpus_of("__staging____") is None
    assert staged_corpus_of("__staging__pytest_x__") is None
    assert staged_corpus_of("__staging____run") is None


def test_qdrant_collection_prefixes_track_the_store_naming_rule() -> None:
    """The reaper's Qdrant match set is derived from the same slug rule the store uses.

    ``corpus_collection_prefix`` rewrites the corpus id before hashing it, so the
    reaper cannot compare raw prefixes; it must map them exactly the way the
    store does. Every test prefix's collections (with any generation suffix)
    match, and no operator corpus's collection does.
    """
    mapped = qdrant_test_collection_prefixes()
    assert len(mapped) == len(TEST_CORPUS_PREFIXES)
    assert all(prefix.startswith("ragweld_chunks_") for prefix in mapped), mapped
    for prefix in TEST_CORPUS_PREFIXES:
        for sample in (f"{prefix}abc", f"{prefix}Abc-Def.ghi", f"{prefix}{'x' * 60}"):
            expected = corpus_collection_prefix(sample)
            assert expected.startswith(mapped), (sample, expected, mapped)
            assert f"{expected}__{RUN_ID}".startswith(mapped)
    for real in OPERATOR_CORPORA:
        assert not corpus_collection_prefix(real).startswith(mapped), real
