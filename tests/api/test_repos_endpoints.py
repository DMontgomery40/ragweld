"""PATCH /api/corpora/{id} answers with the whole corpus, whatever the update touched.

`pg.update_corpus` used to answer in two different shapes: `RETURNING *` (a raw row, with
`root_path`) when something changed, and `get_corpus`'s renamed row (`path`) when nothing
did. `update_repo` read `updated["root_path"]`, so an update that changed nothing raised
KeyError -- a 500 on the one PATCH that is always safe -- and the response dropped the
corpus description on the paths that did work.

These run against the real Postgres the API uses; nothing here is stubbed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.requires_postgres]

DESCRIPTION = "a corpus the PATCH response must not forget"


@pytest.fixture
async def corpus(client: AsyncClient, tmp_path: Path) -> AsyncIterator[dict[str, object]]:
    corpus_id = f"test_repos_patch_{uuid.uuid4().hex[:10]}"
    root = tmp_path / corpus_id
    root.mkdir()
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(root), "description": DESCRIPTION},
    )
    assert created.status_code == 200, created.text
    try:
        yield dict(created.json())
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_a_patch_that_changes_nothing_still_answers_with_the_corpus(
    client: AsyncClient,
    corpus: dict[str, object],
) -> None:
    """The KeyError path: no field set, so the row comes back through `get_corpus`."""
    corpus_id = str(corpus["corpus_id"])

    response = await client.patch(f"/api/corpora/{corpus_id}", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["corpus_id"] == corpus_id
    assert body["path"] == corpus["path"]
    assert body["description"] == DESCRIPTION
    assert body["internal"] is False


@pytest.mark.asyncio
async def test_a_patch_answers_in_the_same_shape_as_a_read(
    client: AsyncClient,
    corpus: dict[str, object],
) -> None:
    """One shape for one row: whatever the update touched, the answer is a whole Corpus."""
    corpus_id = str(corpus["corpus_id"])

    renamed = await client.patch(f"/api/corpora/{corpus_id}", json={"name": "renamed"})
    unchanged = await client.patch(f"/api/corpora/{corpus_id}", json={})
    read = await client.get(f"/api/corpora/{corpus_id}")

    assert [renamed.status_code, unchanged.status_code, read.status_code] == [200, 200, 200]
    assert sorted(renamed.json()) == sorted(read.json()) == sorted(unchanged.json())
    assert renamed.json()["name"] == "renamed"
    # The rename did not cost the corpus its description, and the read agrees with the write.
    assert renamed.json()["description"] == DESCRIPTION
    assert read.json() == renamed.json()
