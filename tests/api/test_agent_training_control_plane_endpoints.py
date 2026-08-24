from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from server.api import agent as agent_api
from server.models.tribrid_config_model import AgentTrainRun, TriBridConfig


@pytest.mark.asyncio
async def test_agent_train_control_plane_status_endpoint_reports_legacy_local_defaults(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/agent/train/control-plane/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["lane"] == "legacy_local"
    assert body["ready"] is False
    assert body["workflow_backend"] == "local"
    assert body["tracking_backend"] == "local"
    assert body["execution_backend"] == "mlx_qwen3"
    assert isinstance(body["components"], list)


@pytest.mark.asyncio
async def test_agent_train_cancel_of_a_finished_run_is_an_explicit_no_op(client: AsyncClient) -> None:
    corpus_id = "pytest_agent_cancel_noop"
    started_at = datetime.now(UTC) - timedelta(minutes=10)
    run_id = f"{corpus_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"
    run_dir = agent_api._RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg = TriBridConfig()
    run = AgentTrainRun(
        run_id=run_id,
        corpus_id=corpus_id,
        status="completed",
        started_at=started_at,
        completed_at=started_at + timedelta(minutes=5),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
    )
    (run_dir / "run.json").write_text(
        json.dumps(run.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )
    (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")

    try:
        response = await client.post(f"/api/agent/train/run/{run_id}/cancel")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert "nothing to cancel" in str(body.get("message") or "")
        assert "completed" in str(body.get("message") or "")
        # nothing was written: no cancellation events, the record stayed completed
        assert (run_dir / "metrics.jsonl").read_text(encoding="utf-8") == ""
        after = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert after["status"] == "completed"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
