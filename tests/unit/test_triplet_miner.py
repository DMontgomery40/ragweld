from __future__ import annotations

import json
from pathlib import Path

from server.training.triplet_miner import mine_triplets_from_query_log


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_replace_mode_preserves_existing_when_no_new_triplets_and_preserve_enabled(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"

    _write_jsonl(
        log_path,
        [
            {
                "kind": "search",
                "event_id": "evt_1",
                "query": "hello world",
                "top_paths": ["a.txt", "b.txt"],
            }
        ],
    )
    _write_jsonl(
        triplets_path,
        [{"query": "existing q", "positive": "p.txt", "negative": "n.txt"}],
    )

    result = mine_triplets_from_query_log(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="replace",
        preserve_existing_on_empty=True,
    )

    assert int(result.get("triplets_mined") or 0) == 0
    assert bool(result.get("preserved_existing")) is True
    lines = [ln for ln in triplets_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["query"] == "existing q"


def test_replace_mode_clears_existing_when_no_new_triplets_and_preserve_disabled(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"

    _write_jsonl(
        log_path,
        [
            {
                "kind": "search",
                "event_id": "evt_1",
                "query": "hello world",
                "top_paths": ["a.txt", "b.txt"],
            }
        ],
    )
    _write_jsonl(
        triplets_path,
        [{"query": "existing q", "positive": "p.txt", "negative": "n.txt"}],
    )

    result = mine_triplets_from_query_log(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="replace",
        preserve_existing_on_empty=False,
    )

    assert int(result.get("triplets_mined") or 0) == 0
    assert bool(result.get("preserved_existing")) is False
    lines = [ln for ln in triplets_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 0
