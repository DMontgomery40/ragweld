from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.lineage import load_asset
from server.models.tribrid_config_model import (
    AgentTrainRun,
    CorpusEvalProfile,
    RerankerTrainRun,
    TriBridConfig,
)
from server.training.artifact_store import resolve_active_artifact_dir

pytestmark = pytest.mark.requires_postgres


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _create_corpus(client: AsyncClient, *, corpus_id: str, path: Path) -> None:
    response = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(path), "description": None},
    )
    assert response.status_code == 200


def _write_reranker_run(root: Path, corpus_id: str, run_id: str) -> Path:
    run_dir = root / "data" / "reranker_train_runs" / run_id
    model_dir = run_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "adapter.npz").write_bytes(b"adapter")
    (model_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tribrid_reranker_manifest.json").write_text(
        json.dumps(
            {
                "backend": "mlx_qwen3",
                "base_model": "Qwen/Qwen3-Reranker-0.6B",
                "run_id": run_id,
                "yes_token_id": 1,
                "no_token_id": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = TriBridConfig()
    profile = CorpusEvalProfile(
        repo_id=corpus_id,
        label_kind="pairwise",
        avg_relevant_per_query=1.0,
        p95_relevant_per_query=1.0,
        recommended_metric="mrr",
        recommended_k=10,
        rationale="promotion-test",
    )
    run = RerankerTrainRun(
        run_id=run_id,
        corpus_id=corpus_id,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
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
    (run_dir / "run.json").write_text(
        json.dumps(run.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
    return run_dir


def _write_agent_run(
    root: Path,
    corpus_id: str,
    run_id: str,
    *,
    base_model: str = "mlx-community/Qwen3-4B-Instruct-2507-4bit",
) -> Path:
    run_dir = root / "data" / "agent_train_runs" / run_id
    model_dir = run_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "adapter.npz").write_bytes(b"adapter")
    (model_dir / "adapter_config.json").write_text(
        json.dumps(
            {
                "backend": "mlx_qwen3",
                "artifact_kind": "ragweld_agent",
                "base_model": base_model,
                "run_id": run_id,
                "lora_rank": 16,
                "lora_alpha": 32.0,
                "lora_dropout": 0.05,
                "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
                "applied_modules": 144,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (model_dir / "manifest.json").write_text(
        json.dumps(
            {
                "backend": "mlx_qwen3",
                "artifact_kind": "ragweld_agent",
                "base_model": base_model,
                "run_id": run_id,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = TriBridConfig()
    run = AgentTrainRun(
        run_id=run_id,
        corpus_id=corpus_id,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric="eval_loss",
        primary_goal="minimize",
        metrics_available=["train_loss", "eval_loss"],
        epochs=1,
        batch_size=1,
        lr=1e-4,
        warmup_ratio=0.0,
        max_length=128,
    )
    (run_dir / "run.json").write_text(
        json.dumps(run.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
    return run_dir


@pytest.mark.asyncio
async def test_reranker_promote_moves_promoted_alias_and_updates_run_lineage(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_reranker_promote_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    active_dir = tmp_path / "reranker-active"
    config_resp = await client.request(
        "PATCH",
        "/api/config/training",
        params={"corpus_id": corpus_id},
        json={"tribrid_reranker_model_path": str(active_dir)},
    )
    assert config_resp.status_code == 200

    root = _repo_root()
    run_id = f"{corpus_id}__completed"
    run_dir = _write_reranker_run(root, corpus_id, run_id)

    try:
        promote = await client.post(f"/api/reranker/train/run/{run_id}/promote")
        assert promote.status_code == 200
        assert promote.json()["ok"] is True

        run = await client.get(f"/api/reranker/train/run/{run_id}")
        assert run.status_code == 200
        body = run.json()
        assert body["promoted_bundle_id"]
        assert body["bundle_id"] == body["promoted_bundle_id"]
        assert body["lineage_ref"]["kind"] == "reranker_train_run"
        assert body["model_artifact_ref"]["kind"] == "reranker_model_artifact"

        asset = load_asset(body["lineage_ref"]["version_id"])
        assert asset.payload["model_artifact_ref"]["kind"] == "reranker_model_artifact"
        assert asset.payload["promotion"]["promoted"] is True

        aliases = await client.get("/api/lineage/aliases", params={"corpus_id": corpus_id})
        assert aliases.status_code == 200
        alias_rows = aliases.json()["aliases"]
        assert any(row["alias"] == "promoted" and row["bundle_id"] == body["promoted_bundle_id"] for row in alias_rows)
        assert any(row["alias"] == "current" and row["bundle_id"] == body["promoted_bundle_id"] for row in alias_rows)
        active_version = resolve_active_artifact_dir(active_dir)
        assert active_version is not None
        assert active_version.name == run_id  # the pointer names the promoted run's version
        assert (active_version / "adapter.npz").exists()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        shutil.rmtree(active_dir, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_agent_promote_moves_promoted_alias_and_updates_run_lineage(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_agent_promote_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    active_dir = tmp_path / "agent-active"
    config_resp = await client.request(
        "PATCH",
        "/api/config/training",
        params={"corpus_id": corpus_id},
        json={"ragweld_agent_model_path": str(active_dir)},
    )
    assert config_resp.status_code == 200

    root = _repo_root()
    run_id = f"{corpus_id}__completed"
    run_dir = _write_agent_run(root, corpus_id, run_id)

    try:
        promote = await client.post(f"/api/agent/train/run/{run_id}/promote")
        assert promote.status_code == 200
        assert promote.json()["ok"] is True

        run = await client.get(f"/api/agent/train/run/{run_id}")
        assert run.status_code == 200
        body = run.json()
        assert body["promoted_bundle_id"]
        assert body["bundle_id"] == body["promoted_bundle_id"]
        assert body["lineage_ref"]["kind"] == "agent_train_run"
        assert body["model_artifact_ref"]["kind"] == "agent_model_artifact"

        asset = load_asset(body["lineage_ref"]["version_id"])
        assert asset.payload["model_artifact_ref"]["kind"] == "agent_model_artifact"
        assert asset.payload["promotion"]["promoted"] is True

        aliases = await client.get("/api/lineage/aliases", params={"corpus_id": corpus_id})
        assert aliases.status_code == 200
        alias_rows = aliases.json()["aliases"]
        assert any(row["alias"] == "promoted" and row["bundle_id"] == body["promoted_bundle_id"] for row in alias_rows)
        assert any(row["alias"] == "current" and row["bundle_id"] == body["promoted_bundle_id"] for row in alias_rows)
        active_version = resolve_active_artifact_dir(active_dir)
        assert active_version is not None
        assert active_version.name == run_id  # the pointer names the promoted run's version
        assert (active_version / "adapter.npz").exists()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        shutil.rmtree(active_dir, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_agent_promote_refuses_artifacts_trained_on_another_base(client: AsyncClient, tmp_path: Path) -> None:
    """A historical run trained on the retired 1.7B base must never overwrite the active 4B adapter."""
    corpus_id = f"pytest_agent_promote_mismatch_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    active_dir = tmp_path / "agent-active"
    active_dir.mkdir()
    sentinel = active_dir / "adapter.npz"
    sentinel.write_bytes(b"current-adapter")
    config_resp = await client.request(
        "PATCH",
        "/api/config/training",
        params={"corpus_id": corpus_id},
        json={"ragweld_agent_model_path": str(active_dir)},
    )
    assert config_resp.status_code == 200

    root = _repo_root()
    run_id = f"{corpus_id}__retired_base"
    run_dir = _write_agent_run(root, corpus_id, run_id, base_model="mlx-community/Qwen3-1.7B-4bit")

    try:
        promote = await client.post(f"/api/agent/train/run/{run_id}/promote")
        assert promote.status_code == 409
        detail = promote.json()["detail"]
        assert "mlx-community/Qwen3-1.7B-4bit" in detail
        assert "mlx-community/Qwen3-4B-Instruct-2507-4bit" in detail

        # The active artifact is untouched and the run was not marked promoted.
        assert sentinel.read_bytes() == b"current-adapter"
        run = await client.get(f"/api/agent/train/run/{run_id}")
        assert run.status_code == 200
        assert not run.json().get("promoted_bundle_id")

        # A manifest that names another run (foreign artifact) is rejected.
        foreign_manifest = json.loads((run_dir / "model" / "manifest.json").read_text(encoding="utf-8"))
        foreign_manifest["base_model"] = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
        foreign_manifest["run_id"] = "some_other_run"
        (run_dir / "model" / "manifest.json").write_text(json.dumps(foreign_manifest) + "\n", encoding="utf-8")
        foreign = await client.post(f"/api/agent/train/run/{run_id}/promote")
        assert foreign.status_code == 409
        assert "not promotable" in foreign.json()["detail"]
        assert sentinel.read_bytes() == b"current-adapter"

        # Missing adapter weights are rejected even with a compatible manifest.
        compatible_dir = _write_agent_run(root, corpus_id, f"{corpus_id}__no_weights")
        try:
            (compatible_dir / "model" / "adapter.npz").unlink()
            no_weights = await client.post(f"/api/agent/train/run/{corpus_id}__no_weights/promote")
            assert no_weights.status_code == 409
            assert "adapter.npz" in no_weights.json()["detail"]
            assert sentinel.read_bytes() == b"current-adapter"
        finally:
            shutil.rmtree(compatible_dir, ignore_errors=True)

        # An artifact without a valid manifest is rejected the same way.
        (run_dir / "model" / "manifest.json").write_text("{}", encoding="utf-8")
        broken = await client.post(f"/api/agent/train/run/{run_id}/promote")
        assert broken.status_code == 409
        assert "not promotable" in broken.json()["detail"]
        assert sentinel.read_bytes() == b"current-adapter"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")
