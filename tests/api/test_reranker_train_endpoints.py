import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.models.tribrid_config_model import CorpusEvalProfile, RerankerTrainMetricEvent, RerankerTrainRun, TriBridConfig


@pytest.fixture
def patch_scoped_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid requiring a live Postgres for scoped config in API tests."""

    async def _fake_load_scoped_config(repo_id: str | None = None) -> TriBridConfig:  # noqa: ARG001
        return TriBridConfig()

    monkeypatch.setattr("server.api.reranker.load_scoped_config", _fake_load_scoped_config)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dataset_path(corpus_id: str) -> Path:
    root = _repo_root()
    d = root / "data" / "eval_dataset"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{corpus_id}.json"


def _runs_dir() -> Path:
    return _repo_root() / "data" / "reranker_train_runs"


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _pstdev(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return var**0.5


@pytest.mark.asyncio
async def test_reranker_train_stream_route_not_shadowed(client: AsyncClient) -> None:
    """Regression test for FastAPI route ordering.

    `/api/reranker/train/run/stream` MUST route to the SSE handler, not the dynamic
    `/api/reranker/train/run/{run_id}` handler (which would treat "stream" as a run_id).
    """
    res = await client.get("/api/reranker/train/run/stream")
    assert res.status_code == 422
    body = res.json()
    assert "detail" in body
    assert any("run_id" in str(item.get("loc", "")) for item in body.get("detail", []))


@pytest.mark.asyncio
async def test_reranker_train_profile_deterministic(client: AsyncClient, patch_scoped_config: None) -> None:  # noqa: ARG001
    corpus_id = "pytest_reranker_train_profile"
    path = _dataset_path(corpus_id)
    path.write_text(
        json.dumps(
            [
                {"question": "q1", "expected_paths": ["a.py"]},
                {"question": "q2", "expected_paths": ["b.py", "c.py"]},
            ],
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    try:
        res = await client.get(f"/api/reranker/train/profile?corpus_id={corpus_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["corpus_id"] == corpus_id
        assert data["recommended_metric"] == "ndcg"
        assert int(data["recommended_k"]) == 10
        rationale = str(data.get("rationale") or "")
        assert "avg=1.50" in rationale
        assert "p95=2.0" in rationale
        assert "nDCG@10" in rationale
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_reranker_train_start_persists_run_and_metrics(client: AsyncClient, patch_scoped_config: None) -> None:  # noqa: ARG001
    corpus_id = "pytest_reranker_train_start"
    dataset_path = _dataset_path(corpus_id)
    dataset_path.write_text(
        json.dumps(
            [
                {"question": "q1", "expected_paths": ["a.py"]},
                {"question": "q2", "expected_paths": ["b.py"]},
            ],
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    run_id: str | None = None
    run_dir: Path | None = None

    try:
        res = await client.post("/api/reranker/train/start", json={"corpus_id": corpus_id})
        assert res.status_code == 200
        body = res.json()
        assert body.get("ok") is True
        run_id = str(body["run_id"])
        assert run_id.startswith(f"{corpus_id}__")

        run_dir = _runs_dir() / run_id
        run_json = run_dir / "run.json"
        metrics_path = run_dir / "metrics.jsonl"
        assert run_json.exists()
        assert metrics_path.exists()

        raw_run = json.loads(run_json.read_text(encoding="utf-8"))
        assert raw_run["corpus_id"] == corpus_id
        assert raw_run["primary_metric"] == "mrr"
        assert int(raw_run["primary_k"]) == 10
        assert raw_run["metric_profile"]["corpus_id"] == corpus_id

        lines = [ln for ln in metrics_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert first["run_id"] == run_id
        assert first["type"] in {"state", "log"}
    finally:
        dataset_path.unlink(missing_ok=True)
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_reranker_train_diff_computes_and_rejects_incompatible(client: AsyncClient, patch_scoped_config: None) -> None:  # noqa: ARG001
    corpus_id = "pytest_reranker_train_diff"
    dataset_path = _dataset_path(corpus_id)
    dataset_path.write_text(
        json.dumps(
            [
                {"question": "q1", "expected_paths": ["a.py"]},
                {"question": "q2", "expected_paths": ["b.py"]},
                {"question": "q3", "expected_paths": ["c.py"]},
            ],
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    run_dirs: list[Path] = []
    try:
        # Create two compatible runs (same primary metric + k)
        b = await client.post("/api/reranker/train/start", json={"corpus_id": corpus_id})
        c = await client.post("/api/reranker/train/start", json={"corpus_id": corpus_id})
        assert b.status_code == 200
        assert c.status_code == 200
        baseline_run_id = str(b.json()["run_id"])
        current_run_id = str(c.json()["run_id"])

        baseline_dir = _runs_dir() / baseline_run_id
        current_dir = _runs_dir() / current_run_id
        run_dirs.extend([baseline_dir, current_dir])

        baseline_json = json.loads((baseline_dir / "run.json").read_text(encoding="utf-8"))
        current_json = json.loads((current_dir / "run.json").read_text(encoding="utf-8"))
        assert baseline_json["primary_metric"] == "mrr"
        assert int(baseline_json["primary_k"]) == 10
        assert current_json["primary_metric"] == "mrr"
        assert int(current_json["primary_k"]) == 10

        b_started = _parse_dt(str(baseline_json["started_at"]))
        c_started = _parse_dt(str(current_json["started_at"]))

        b_metrics = baseline_dir / "metrics.jsonl"
        c_metrics = current_dir / "metrics.jsonl"

        # Append deterministic metrics events
        b_vals = [0.2, 0.4, 0.35]
        c_vals = [0.25, 0.5, 0.45]
        b_times = [5, 10, 20]
        c_times = [3, 8, 15]

        for i, (t, v) in enumerate(zip(b_times, b_vals, strict=True), start=1):
            ev = {
                "type": "metrics",
                "ts": _iso(b_started + timedelta(seconds=t)),
                "run_id": baseline_run_id,
                "step": i,
                "epoch": float(i) / 10.0,
                "metrics": {"mrr@10": v, "ndcg@10": v, "map": v},
            }
            b_metrics.write_text(b_metrics.read_text(encoding="utf-8") + json.dumps(ev) + "\n", encoding="utf-8")

        for i, (t, v) in enumerate(zip(c_times, c_vals, strict=True), start=1):
            ev = {
                "type": "metrics",
                "ts": _iso(c_started + timedelta(seconds=t)),
                "run_id": current_run_id,
                "step": i,
                "epoch": float(i) / 10.0,
                "metrics": {"mrr@10": v, "ndcg@10": v, "map": v},
            }
            c_metrics.write_text(c_metrics.read_text(encoding="utf-8") + json.dumps(ev) + "\n", encoding="utf-8")

        # Compatible diff
        diff = await client.post(
            "/api/reranker/train/diff",
            json={"baseline_run_id": baseline_run_id, "current_run_id": current_run_id},
        )
        assert diff.status_code == 200
        d = diff.json()
        assert d["compatible"] is True
        assert d["primary_metric"] == "mrr"
        assert int(d["primary_k"]) == 10
        assert d["baseline_primary_best"] == pytest.approx(0.4)
        assert d["current_primary_best"] == pytest.approx(0.5)
        assert d["delta_primary_best"] == pytest.approx(0.1)
        assert d["baseline_time_to_best_secs"] == pytest.approx(10.0)
        assert d["current_time_to_best_secs"] == pytest.approx(8.0)
        assert d["delta_time_to_best_secs"] == pytest.approx(-2.0)
        assert d["baseline_stability_stddev"] == pytest.approx(_pstdev(b_vals))
        assert d["current_stability_stddev"] == pytest.approx(_pstdev(c_vals))
        assert d["delta_stability_stddev"] == pytest.approx(_pstdev(c_vals) - _pstdev(b_vals))

        # Incompatible diff (different k)
        inc = await client.post("/api/reranker/train/start", json={"corpus_id": corpus_id, "primary_k": 20})
        assert inc.status_code == 200
        inc_run_id = str(inc.json()["run_id"])
        inc_dir = _runs_dir() / inc_run_id
        run_dirs.append(inc_dir)

        diff2 = await client.post(
            "/api/reranker/train/diff",
            json={"baseline_run_id": baseline_run_id, "current_run_id": inc_run_id},
        )
        assert diff2.status_code == 200
        d2 = diff2.json()
        assert d2["compatible"] is False
        assert "Incompatible" in str(d2.get("reason") or "")
    finally:
        dataset_path.unlink(missing_ok=True)
        for d in run_dirs:
            shutil.rmtree(d, ignore_errors=True)


@pytest.mark.asyncio
async def test_reranker_train_reconciles_legacy_stub_runs(client: AsyncClient) -> None:
    corpus_id = "pytest_reranker_stub"
    started_at = datetime.now(UTC) - timedelta(hours=6)
    run_id = f"{corpus_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"

    run_dir = _runs_dir() / run_id
    run_json = run_dir / "run.json"
    metrics_path = run_dir / "metrics.jsonl"
    run_dir.mkdir(parents=True, exist_ok=True)

    cfg = TriBridConfig()
    profile = CorpusEvalProfile(
        repo_id=corpus_id,
        label_kind="pairwise",
        avg_relevant_per_query=0.0,
        p95_relevant_per_query=0.0,
        recommended_metric="mrr",
        recommended_k=10,
        rationale="stub",
    )
    run = RerankerTrainRun(
        run_id=run_id,
        repo_id=corpus_id,
        status="running",
        started_at=started_at,
        completed_at=None,
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric="mrr",
        primary_k=10,
        metrics_available=["mrr@10", "ndcg@10", "map"],
        metric_profile=profile,
        epochs=1,
        batch_size=1,
        lr=1e-4,
        warmup_ratio=0.0,
        max_length=128,
    )
    run_json.write_text(json.dumps(run.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True), encoding="utf-8")

    ev1 = RerankerTrainMetricEvent(
        type="state",
        ts=started_at,
        run_id=run_id,
        message="Primary metric locked: mrr@10",
        status="running",
    )
    ev2 = RerankerTrainMetricEvent(
        type="log",
        ts=started_at + timedelta(seconds=1),
        run_id=run_id,
        message="Training task is a stub (no background training is running yet). Run left in status=running.",
    )
    metrics_path.write_text(
        json.dumps(ev1.model_dump(mode="json", by_alias=True)) + "\n" + json.dumps(ev2.model_dump(mode="json", by_alias=True)) + "\n",
        encoding="utf-8",
    )

    try:
        # Loading the run should reconcile and persist it as cancelled.
        res = await client.get(f"/api/reranker/train/run/{run_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["run_id"] == run_id
        assert body["status"] == "cancelled"
        assert body.get("completed_at")

        # Listing runs should reflect the reconciled status too (UI left-rail).
        res_list = await client.get("/api/reranker/train/runs", params={"corpus_id": corpus_id, "scope": "corpus"})
        assert res_list.status_code == 200
        runs = res_list.json().get("runs") or []
        match = next((r for r in runs if r.get("run_id") == run_id), None)
        assert match is not None
        assert match.get("status") == "cancelled"

        # run.json is updated on disk.
        raw_after = json.loads(run_json.read_text(encoding="utf-8"))
        assert raw_after["status"] == "cancelled"
        assert raw_after.get("completed_at")
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
