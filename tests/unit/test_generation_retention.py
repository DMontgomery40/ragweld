"""Retention invariants of the generation manifest (pure model logic, real Pydantic models)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from server.indexing.generations import GenerationManifest, RetiredGeneration, build_generation

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _retired(
    run: str, collection: str | None, graph: str | None, *, age_s: int
) -> RetiredGeneration:
    return RetiredGeneration(
        run_id=run,
        qdrant_collection=collection,
        graph_repo_id=graph,
        retired_at=NOW - timedelta(seconds=age_s),
    )


def test_shared_resource_survives_while_any_holder_is_inside_its_grace() -> None:
    manifest = GenerationManifest(
        run_id="live",
        qdrant_collection="c-live",
        graph_repo_id="g-live",
        promoted_at=NOW,
        retired=[
            _retired("due", "c-due", "g-shared", age_s=7200),
            _retired("fresh", "c-fresh", "g-shared", age_s=10),
        ],
    )
    due = manifest.due_for_retirement(now=NOW, grace_seconds=3600)
    assert [(d.run_id, d.qdrant_collection, d.graph_repo_id) for d in due] == [
        ("due", "c-due", None)
    ]
    kept = manifest.without_resources(due)
    by_run = {r.run_id: r for r in kept}
    assert by_run["due"].qdrant_collection is None and by_run["due"].graph_repo_id == "g-shared"
    assert by_run["fresh"].qdrant_collection == "c-fresh"


def test_both_holders_due_releases_the_shared_resource_once() -> None:
    manifest = GenerationManifest(
        run_id="live",
        qdrant_collection="c-live",
        graph_repo_id="g-live",
        promoted_at=NOW,
        retired=[
            _retired("a", "c-a", "g-shared", age_s=7200),
            _retired("b", "c-b", "g-shared", age_s=7200),
        ],
    )
    due = manifest.due_for_retirement(now=NOW, grace_seconds=3600)
    # Each physical resource is emitted in exactly ONE retirement operation: the
    # shared graph rides with the first due holder and is masked from the second.
    assert [(d.run_id, d.qdrant_collection, d.graph_repo_id) for d in due] == [
        ("a", "c-a", "g-shared"),
        ("b", "c-b", None),
    ]
    assert [d.graph_repo_id for d in due].count("g-shared") == 1
    assert manifest.without_resources(due) == []


def test_live_resources_are_never_retired_even_when_a_due_entry_names_them() -> None:
    manifest = GenerationManifest(
        run_id="live",
        qdrant_collection="c-live",
        graph_repo_id="g-live",
        promoted_at=NOW,
        retired=[_retired("old", "c-live", "g-old", age_s=7200)],
    )
    due = manifest.due_for_retirement(now=NOW, grace_seconds=0)
    assert [(d.qdrant_collection, d.graph_repo_id) for d in due] == [(None, "g-old")]


def test_build_generation_masks_reused_ids_and_deduplicates_pairs() -> None:
    previous = GenerationManifest(
        run_id="prev",
        qdrant_collection="c-prev",
        graph_repo_id="g-shared",
        promoted_at=NOW - timedelta(seconds=60),
        retired=[_retired("older", "c-older", "g-shared", age_s=120)],
    )
    # The new generation reuses the previous graph id: the graph is masked out of
    # every retired entry, and the entry that then names nothing is dropped.
    manifest = build_generation(
        run_id="new",
        qdrant_collection="c-new",
        graph_repo_id="g-shared",
        previous=previous,
        now=NOW,
    )
    pairs = [(r.run_id, r.qdrant_collection, r.graph_repo_id) for r in manifest.retired]
    assert pairs == [("older", "c-older", None), ("prev", "c-prev", None)]
    # Nothing that names the live collection survives either.
    manifest2 = build_generation(
        run_id="new2", qdrant_collection="c-prev", graph_repo_id="g-new", previous=previous, now=NOW
    )
    assert all(r.qdrant_collection != "c-prev" for r in manifest2.retired)
    assert {r.graph_repo_id for r in manifest2.retired} == {"g-shared"}


def test_entries_converging_on_one_pair_after_masking_keep_one_with_the_latest_grace() -> None:
    # An older retired entry and the previous generation name the SAME collection
    # and graph; the new generation reuses that graph, so both mask to
    # ("c-x", None): one entry survives, stamped with the LATER retirement (the
    # shared collection never gets a shorter grace than any holder promised).
    previous = GenerationManifest(
        run_id="prev",
        qdrant_collection="c-x",
        graph_repo_id="g-shared",
        promoted_at=NOW - timedelta(seconds=60),
        retired=[_retired("older", "c-x", "g-shared", age_s=120)],
    )
    manifest = build_generation(
        run_id="new", qdrant_collection="c-new", graph_repo_id="g-shared", previous=previous, now=NOW
    )
    assert [(r.qdrant_collection, r.graph_repo_id) for r in manifest.retired] == [("c-x", None)]
    assert manifest.retired[0].retired_at == NOW, "the later retirement wins"
    assert manifest.retired[0].run_id == "prev"
    # The single surviving entry retires c-x exactly once, on the later clock.
    assert manifest.due_for_retirement(now=NOW + timedelta(seconds=59), grace_seconds=60) == []
    assert [d.qdrant_collection for d in manifest.due_for_retirement(now=NOW + timedelta(seconds=60), grace_seconds=60)] == ["c-x"]


def test_grace_zero_retires_at_the_next_commit_and_nothing_before_it() -> None:
    manifest = GenerationManifest(
        run_id="live",
        qdrant_collection="c-live",
        graph_repo_id=None,
        promoted_at=NOW,
        retired=[_retired("prev", "c-prev", None, age_s=0)],
    )
    assert manifest.due_for_retirement(now=NOW, grace_seconds=0) == [
        _retired("prev", "c-prev", None, age_s=0)
    ]
    assert manifest.due_for_retirement(now=NOW, grace_seconds=1) == []
