from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.api.eval import _run_path as _eval_run_path
from server.models.tribrid_config_model import EvalMetrics, EvalResult, EvalRun

pytestmark = pytest.mark.requires_postgres


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


def _persist_eval_run(*, corpus_id: str, run_id: str, results: list[EvalResult]) -> Path:
    """Persist a real EvalRun artifact the way /api/eval/run does (data/eval_runs/<run_id>.json)."""
    now = datetime.now(UTC)
    total = len(results)
    run = EvalRun(
        run_id=run_id,
        repo_id=corpus_id,
        dataset_id="default",
        config_snapshot={},
        config={},
        total=total,
        top1_hits=sum(1 for r in results if r.top1_hit),
        topk_hits=sum(1 for r in results if r.topk_hit),
        top1_accuracy=(sum(1 for r in results if r.top1_hit) / total) if total else 0.0,
        topk_accuracy=(sum(1 for r in results if r.topk_hit) / total) if total else 0.0,
        duration_secs=0.1,
        use_multi=False,
        final_k=5,
        metrics=EvalMetrics(
            mrr=0.5,
            recall_at_5=0.5,
            recall_at_10=0.5,
            recall_at_20=0.5,
            precision_at_5=0.1,
            ndcg_at_10=0.5,
            latency_p50_ms=1.0,
            latency_p95_ms=1.0,
        ),
        results=results,
        started_at=now,
        completed_at=now,
    )
    path = _eval_run_path(run_id)
    path.write_text(json.dumps(run.model_dump(mode="json", by_alias=True), indent=2), encoding="utf-8")
    return path


def _eval_result(*, entry_id: str, question: str, expected_paths: list[str], retrieved_paths: list[str]) -> EvalResult:
    hit = bool(retrieved_paths) and retrieved_paths[0] in expected_paths
    return EvalResult(
        entry_id=entry_id,
        question=question,
        retrieved_paths=retrieved_paths,
        expected_paths=expected_paths,
        top_paths=retrieved_paths[:5],
        top1_path=retrieved_paths[:1],
        top1_hit=hit,
        topk_hit=any(p in expected_paths for p in retrieved_paths[:5]),
        reciprocal_rank=1.0 if hit else 0.5,
        recall=1.0 if any(p in expected_paths for p in retrieved_paths) else 0.0,
        latency_ms=1.0,
    )


async def _scoped_corpus(client, tmp_path: Path, corpus_id: str) -> tuple[Path, Path]:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"
    r = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_root)},
    )
    assert r.status_code == 200
    r = await client.request(
        "PATCH",
        f"/api/config/tracing?corpus_id={corpus_id}",
        json={"tribrid_log_path": str(log_path)},
    )
    assert r.status_code == 200
    r = await client.request(
        "PATCH",
        f"/api/config/training?corpus_id={corpus_id}",
        json={"tribrid_triplets_path": str(triplets_path), "learning_reranker_negative_ratio": 2},
    )
    assert r.status_code == 200
    return log_path, triplets_path


async def test_mine_uses_the_latest_eval_run_retrieval_results_as_hard_negatives(client, tmp_path: Path) -> None:
    corpus_id = f"test-mine-eval-{tmp_path.name}"
    log_path, triplets_path = await _scoped_corpus(client, tmp_path, corpus_id)
    log_path.write_text("", encoding="utf-8")
    older = f"{corpus_id}__20260101_000000"
    newest = f"{corpus_id}__20260822_120000"
    persisted: list[Path] = []
    try:
        persisted.append(
            _persist_eval_run(
                corpus_id=corpus_id,
                run_id=older,
                results=[
                    _eval_result(
                        entry_id="old",
                        question="When was the Aurora salinity sensor array last recalibrated?",
                        expected_paths=["sensor-calibration.md"],
                        retrieved_paths=["observatory-overview.md", "sensor-calibration.md"],
                    )
                ],
            )
        )
        persisted.append(
            _persist_eval_run(
                corpus_id=corpus_id,
                run_id=newest,
                results=[
                    _eval_result(
                        entry_id="q1",
                        question="How often is the Aurora salinity sensor array calibrated?",
                        expected_paths=["sensor-calibration.md"],
                        retrieved_paths=[
                            "observatory-overview.md",
                            "sensor-calibration.md",
                            "incident-playbook.md",
                            "data-pipeline.md",
                        ],
                    ),
                    _eval_result(
                        entry_id="q2",
                        question="Which team owns the Aurora incident playbook escalation steps?",
                        expected_paths=["incident-playbook.md"],
                        retrieved_paths=["incident-playbook.md"],
                    ),
                ],
            )
        )

        r = await client.post(f"/api/reranker/mine?corpus_id={corpus_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["eval_run_id"] == newest
        assert body["triplets_from_feedback"] == 0
        assert body["triplets_from_eval_run"] == 2
        assert body["triplets_mined"] == 2
        assert body["triplets_total"] == 2

        rows = [json.loads(ln) for ln in triplets_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert [(row["positive"], row["negative"]) for row in rows] == [
            ("sensor-calibration.md", "observatory-overview.md"),
            ("sensor-calibration.md", "incident-playbook.md"),
        ]
        assert {row["source"] for row in rows} == {f"eval_run:{newest}"}
        assert all(row["query"] == "How often is the Aurora salinity sensor array calibrated?" for row in rows)

        count = await client.get(f"/api/reranker/triplets/count?corpus_id={corpus_id}")
        assert count.status_code == 200
        assert count.json()["count"] == 2
    finally:
        for path in persisted:
            path.unlink(missing_ok=True)
        await client.delete(f"/api/corpora/{corpus_id}")


async def test_mine_rejects_an_eval_run_from_another_corpus_and_unknown_ids(client, tmp_path: Path) -> None:
    corpus_id = f"test-mine-guard-{tmp_path.name}"
    _log_path, _triplets_path = await _scoped_corpus(client, tmp_path, corpus_id)
    foreign = f"other-corpus__{tmp_path.name}"
    persisted = _persist_eval_run(
        corpus_id="other-corpus",
        run_id=foreign,
        results=[
            _eval_result(
                entry_id="x",
                question="What does the Aurora data pipeline do with rejected sensor frames?",
                expected_paths=["data-pipeline.md"],
                retrieved_paths=["incident-playbook.md", "data-pipeline.md"],
            )
        ],
    )
    try:
        mismatch = await client.post(f"/api/reranker/mine?corpus_id={corpus_id}&eval_run_id={foreign}")
        assert mismatch.status_code == 422, mismatch.text
        missing = await client.post(f"/api/reranker/mine?corpus_id={corpus_id}&eval_run_id=does-not-exist__1")
        assert missing.status_code == 404, missing.text
    finally:
        persisted.unlink(missing_ok=True)
        await client.delete(f"/api/corpora/{corpus_id}")


async def test_mine_requires_a_corpus_and_rejects_traversal_run_ids(client, tmp_path: Path) -> None:
    corpus_id = f"test-mine-guard2-{tmp_path.name}"
    await _scoped_corpus(client, tmp_path, corpus_id)
    try:
        unscoped = await client.post("/api/reranker/mine")
        assert unscoped.status_code == 422, unscoped.text
        traversal = await client.post(f"/api/reranker/mine?corpus_id={corpus_id}&eval_run_id=../../tribrid_config")
        assert traversal.status_code == 422, traversal.text
        assert "invalid eval run id" in str(traversal.json().get("detail", ""))
        status = await client.get("/api/reranker/status")
        assert status.status_code == 200
        assert status.json().get("running") is False
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


async def test_mine_reports_an_unknown_corpus_as_404(client, tmp_path: Path) -> None:
    missing = await client.post(f"/api/reranker/mine?corpus_id=test-mine-missing-{tmp_path.name}")
    assert missing.status_code == 404, missing.text
    status = await client.get("/api/reranker/status")
    assert status.status_code == 200
    assert status.json().get("running") is False
