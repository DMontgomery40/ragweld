from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from server.api.dataset import _dataset_path_for_corpus


@pytest.mark.asyncio
async def test_dataset_reads_legacy_and_writes_canonical(client) -> None:
    corpus_id = f"pytest_dataset_migrate_{uuid.uuid4().hex[:8]}"
    root = Path(__file__).resolve().parents[2]
    legacy = root / "data" / "eval_dataset" / f"{corpus_id}.json"
    canonical = root / "data" / "eval_datasets" / f"{corpus_id}.json"
    payload = [{"question": "q1", "expected_paths": ["a.py"]}]

    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    canonical.unlink(missing_ok=True)

    try:
        r = await client.get("/api/dataset", params={"corpus_id": corpus_id})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["question"] == "q1"
        assert canonical.exists(), "Expected canonical dataset file to be created on legacy read"

        r2 = await client.post("/api/dataset", params={"corpus_id": corpus_id}, json={"question": "q2", "expected_paths": ["b.py"]})
        assert r2.status_code == 200
        canonical_data = json.loads(canonical.read_text(encoding="utf-8"))
        assert len(canonical_data) == 2

        legacy_data = json.loads(legacy.read_text(encoding="utf-8"))
        assert len(legacy_data) == 1, "Legacy file should not be rewritten after migration"
    finally:
        legacy.unlink(missing_ok=True)
        canonical.unlink(missing_ok=True)


def test_dataset_path_mapping_is_collision_resistant() -> None:
    assert _dataset_path_for_corpus("a/b").name != _dataset_path_for_corpus("a_b").name
    assert _dataset_path_for_corpus(".foo").name != _dataset_path_for_corpus("foo").name
