from __future__ import annotations

import json
from pathlib import Path


async def test_scoped_feedback_logs_are_mineable(client, tmp_path: Path) -> None:
    corpus_id = f"test-mine-{tmp_path.name}"
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)

    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"

    # Create corpus
    r = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_root)},
    )
    assert r.status_code == 200

    try:
        # Ensure this corpus writes logs/triplets to our tmp paths (so tests don't contaminate global files).
        r = await client.request(
            "PATCH",
            f"/api/config/tracing?corpus_id={corpus_id}",
            json={"tribrid_log_path": str(log_path)},
        )
        assert r.status_code == 200

        r = await client.request(
            "PATCH",
            f"/api/config/training?corpus_id={corpus_id}",
            json={"tribrid_triplets_path": str(triplets_path)},
        )
        assert r.status_code == 200

        # Write a query event (same shape chat/search emit into the JSONL file).
        event_id = "evt_mine_scoped_1"
        log_path.write_text(
            json.dumps(
                {
                    "ts": "2026-02-04T00:00:00Z",
                    "kind": "chat",
                    "event_id": event_id,
                    "query": "Where is auth implemented?",
                    "corpus_ids": [corpus_id],
                    "top_paths": ["good.txt", "bad.txt"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Append feedback via the real API endpoint (must write into the *same* scoped log file).
        r = await client.post(
            f"/api/feedback?corpus_id={corpus_id}",
            json={"event_id": event_id, "signal": "thumbsup"},
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # Mine triplets from the scoped log file.
        r = await client.post(f"/api/reranker/mine?corpus_id={corpus_id}")
        assert r.status_code == 200
        assert r.json().get("ok") is True

        assert triplets_path.exists()
        lines = [ln for ln in triplets_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1
        t = json.loads(lines[0])
        assert t["query"] == "Where is auth implemented?"
        assert t["positive"] == "good.txt"
        assert t["negative"] == "bad.txt"

        # Sanity: feedback was logged into the same file (not global).
        log_lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert any('"kind": "feedback"' in ln and event_id in ln for ln in log_lines)
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
