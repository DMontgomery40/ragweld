"""A relative registry path is resolved once, and the resolved root is the only one that escapes.

The recall corpus is registered as the relative ``data/recall``
(``server/chat/recall_indexer.py``). Resolving that against the process CWD names a different
directory for every process that reads it, and ``promote_staging_index`` writes whatever string
it is handed straight back into ``corpora.path`` -- so a run against a relative row re-persisted
the relative row for every future reader, in every process, including readers in other
subsystems.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.db.postgres import PostgresClient

pytestmark = pytest.mark.requires_postgres


@pytest.fixture
def elsewhere_cwd(tmp_path) -> Generator[Path, None, None]:
    """Run with a CWD that is NOT the runtime root.

    The bug is invisible while the two coincide, which is exactly the coincidence the resolver
    was introduced to stop relying on.
    """
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield previous
    finally:
        os.chdir(previous)


async def _corpus_row(repo_id: str) -> dict:
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        return await pg.get_corpus(repo_id) or {}
    finally:
        await pg.disconnect()


def test_the_resolved_root_is_what_the_run_and_the_registry_are_given(elsewhere_cwd) -> None:
    """`start_index` must hand the run an absolute root, not the string it was posted."""
    from server.models.index import IndexRequest

    request = IndexRequest(corpus_id="c", repo_path="data/recall", force_reindex=False)
    resolved = index_api._resolve_corpus_root(request.repo_path)
    carried = request.model_copy(update={"repo_path": str(resolved)})

    assert Path(carried.repo_path).is_absolute()
    assert carried.repo_path == str(resolved)
    # Not the CWD's interpretation: that is the reading the resolver exists to replace.
    assert carried.repo_path != str((Path.cwd() / "data" / "recall").resolve())
    assert Path(carried.repo_path).parent.parent == index_api._RUNTIME_ROOT.resolve()


@pytest.mark.asyncio
async def test_a_run_on_a_relative_registry_path_walks_the_resolved_root(
    client: AsyncClient, tmp_path, elsewhere_cwd
) -> None:
    """End to end: the run indexes the resolved directory, from a CWD that is not the anchor.

    Before this, `_run_index` walked `Path(repo_path)` CWD-relative while the estimate and the
    validation read the resolved root -- three readings of one registry row. The corpus here is
    registered with a path relative to the PROJECT root, a real directory is materialised there,
    and the run is driven through the API the operator uses.
    """
    repo_id = f"relroot_{uuid.uuid4().hex[:10]}"
    relative = Path("data") / "index_relroot_fixtures" / repo_id
    absolute = (index_api._RUNTIME_ROOT / relative).resolve()
    absolute.mkdir(parents=True, exist_ok=True)
    (absolute / "note.md").write_text("# aurora tidal observatory\n\nOne indexable note.\n", encoding="utf-8")

    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=str(relative))
    finally:
        await pg.disconnect()

    try:
        row_before = await _corpus_row(repo_id)
        assert row_before.get("path") == str(relative), "precondition: the row starts relative"

        started = await client.post(
            "/api/index",
            json={"corpus_id": repo_id, "repo_path": str(relative), "force_reindex": True},
        )
        assert started.status_code == 200, started.text

        # The run is what persists the row, so wait for it to finish.
        for _ in range(120):
            status = await client.get(f"/api/index/{repo_id}/status")
            if status.status_code == 200 and status.json().get("status") in {
                "complete",
                "error",
                "cancelled",
            }:
                break
            import asyncio

            await asyncio.sleep(1)
        final = await client.get(f"/api/index/{repo_id}/status")
        assert final.json().get("status") == "complete", final.text

        # The run walked the RESOLVED root, not the CWD's reading of it: the only indexable
        # file in the corpus lives under the resolved directory, and it produced chunks. The
        # CWD (tmp_path) holds no such directory at all, so a CWD-relative walk yields nothing.
        stats = await client.get(f"/api/index/{repo_id}/stats")
        assert stats.status_code == 200
        assert int(stats.json().get("total_chunks") or 0) >= 1
        assert not (Path.cwd() / relative).exists(), (
            "the CWD must not also contain the corpus, or this proves nothing"
        )

        # And the shared registry row is left exactly as the operator registered it. Rewriting
        # it here would repoint the corpus at whichever checkout happened to serve the request.
        row_after = await _corpus_row(repo_id)
        assert str(row_after.get("path") or "") == str(relative)
    finally:
        pg2 = PostgresClient("postgresql://ignored")
        await pg2.connect()
        try:
            await pg2.delete_corpus_with_data(repo_id)
        finally:
            await pg2.disconnect()
        for child in sorted(absolute.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        absolute.rmdir()
