from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.models.tribrid_config_model import (
    SyntheticArtifactRef,
    SyntheticRun,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.synthetic.recipes import resolve_available_synthetic_model


async def _wait_terminal(client, run_id: str, timeout_s: float = 20.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/synthetic/run/{run_id}")
        assert r.status_code == 200
        data = r.json()
        if data.get("status") in {"completed", "failed", "cancelled"}:
            return data
        await asyncio.sleep(0.1)
    raise AssertionError(f"Timed out waiting for run {run_id} to finish")


def _provider_model_for_env() -> str | None:
    cfg = TriBridConfig()
    return resolve_available_synthetic_model(cfg)


def _write_gate_failed_run(*, root: Path, corpus_id: str, run_id: str) -> Path:
    run_dir = root / "data" / "synthetic_runs" / run_id
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    eval_path = artifacts_dir / "eval_dataset.json"
    eval_path.write_text(
        json.dumps(
            [
                {
                    "question": "Who is named in this document?",
                    "expected_paths": ["notes.txt"],
                    "expected_answer": "Example",
                    "tags": ["synthetic"],
                }
            ]
        ),
        encoding="utf-8",
    )
    triplets_path = artifacts_dir / "triplets.jsonl"
    triplets_path.write_text('{"query":"q","positive":"a","negative":"b"}\n', encoding="utf-8")

    request = SyntheticRunStartRequest(
        corpus_id=corpus_id,
        provider="internal_ragweld",
        recipe="full_stack",
        generator_model="openai/gpt-4o-mini",
        judge_model="openai/gpt-4o-mini",
    )
    run = SyntheticRun(
        run_id=run_id,
        corpus_id=corpus_id,
        status="failed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        provider="internal_ragweld",
        recipe="full_stack",
        config_snapshot={},
        config={},
        request=request,
        artifacts=[
            SyntheticArtifactRef(
                kind="eval_dataset_json",
                path=str(eval_path),
                bytes=eval_path.stat().st_size,
                created_at=datetime.now(UTC),
            ),
            SyntheticArtifactRef(
                kind="triplets_jsonl",
                path=str(triplets_path),
                bytes=triplets_path.stat().st_size,
                created_at=datetime.now(UTC),
            ),
        ],
        summary=SyntheticRunSummary(
            quality_top1_accuracy=0.0,
            quality_topk_accuracy=0.0,
            quality_mrr=0.0,
            quality_sample_size=50,
            quality_gate_threshold=0.40,
            quality_gate_passed=False,
            quality_failure_reason="Quality gate failed: top1=0.000 < threshold=0.400",
        ),
        error="Quality gate failed",
    )
    run_json = run_dir / "run.json"
    run_json.write_text(json.dumps(run.model_dump(mode="json", by_alias=True), indent=2), encoding="utf-8")
    return run_dir


@pytest.mark.asyncio
async def test_synthetic_stream_route_not_shadowed(client) -> None:
    res = await client.get("/api/synthetic/run/stream")
    assert res.status_code == 422
    body = res.json()
    assert "detail" in body
    assert any("run_id" in str(item.get("loc", "")) for item in body.get("detail", []))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        (
            {
                "judge_model": "openai/gpt-4o-mini",
            },
            "generator_model",
        ),
        (
            {
                "generator_model": "openai/gpt-4o-mini",
            },
            "judge_model",
        ),
        (
            {
                "generator_model": "   ",
                "judge_model": "openai/gpt-4o-mini",
            },
            "generator_model",
        ),
        (
            {
                "generator_model": "openai/gpt-4o-mini",
                "judge_model": "   ",
            },
            "judge_model",
        ),
    ],
)
async def test_synthetic_start_requires_generator_and_judge_models(client, payload, field_name: str) -> None:
    corpus_id = f"pytest_synth_models_{uuid.uuid4().hex[:8]}"
    res = await client.post(
        "/api/synthetic/run/start",
        json={
            "corpus_id": corpus_id,
            "provider": "internal_ragweld",
            "recipe": "eval_dataset",
            **payload,
        },
    )
    assert res.status_code == 422
    detail = res.json().get("detail", [])
    assert any(field_name in str(item.get("loc", "")) for item in detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("corpus_id", ["../../tmp/pwn", "a/b", "bad corpus id"])
async def test_synthetic_start_rejects_invalid_corpus_id(client, corpus_id: str) -> None:
    res = await client.post(
        "/api/synthetic/run/start",
        json={
            "corpus_id": corpus_id,
            "provider": "internal_ragweld",
            "recipe": "eval_dataset",
            "generator_model": "openai/gpt-4o-mini",
            "judge_model": "openai/gpt-4o-mini",
        },
    )
    assert res.status_code == 422
    detail = str(res.json().get("detail", ""))
    assert "corpus_id" in detail or "repo_id" in detail


@pytest.mark.asyncio
async def test_synthetic_publish_endpoints_blocked_when_quality_gate_failed(client) -> None:
    corpus_id = f"pytest_synth_gate_{uuid.uuid4().hex[:8]}"
    run_id = f"{corpus_id}__gate_failed"
    root = Path(__file__).resolve().parents[2]
    run_dir = _write_gate_failed_run(root=root, corpus_id=corpus_id, run_id=run_id)

    try:
        resp_eval = await client.post(f"/api/synthetic/run/{run_id}/publish/eval_dataset")
        assert resp_eval.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_eval.json().get("detail", ""))

        resp_triplets = await client.post(f"/api/synthetic/run/{run_id}/publish/triplets")
        assert resp_triplets.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_triplets.json().get("detail", ""))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_synthetic_failed_gate_persists_quality_artifact_and_blocks_publish(client) -> None:
    model = _provider_model_for_env()
    if not model:
        pytest.skip("No resolvable synthetic model route in this environment")

    corpus_id = f"pytest_synth_gate_art_{uuid.uuid4().hex[:8]}"
    root = Path(__file__).resolve().parents[2]
    run_dir: Path | None = None

    try:
        start = await client.post(
            "/api/synthetic/run/start",
            json={
                "corpus_id": corpus_id,
                "provider": "internal_ragweld",
                "recipe": "keywords",
                "generator_model": model,
                "judge_model": model,
                "max_source_chunks": 10,
                "max_pairs": 10,
                "pairs_per_source": 1,
            },
        )
        assert start.status_code == 200
        run_id = str(start.json()["run_id"])
        run_dir = root / "data" / "synthetic_runs" / run_id

        terminal = await _wait_terminal(client, run_id)
        assert terminal["status"] == "failed"
        assert "Quality gate evaluation failed" in str(terminal.get("error", ""))
        assert "no eval items generated" in str(terminal.get("error", ""))
        summary = terminal.get("summary", {})
        assert summary.get("quality_gate_passed") is False
        assert "no eval items generated" in str(summary.get("quality_failure_reason", ""))

        quality_artifact = next((a for a in (terminal.get("artifacts") or []) if a.get("kind") == "quality_eval_json"), None)
        assert quality_artifact is not None
        quality_path = Path(str(quality_artifact["path"]))
        assert quality_path.exists()
        quality_payload = json.loads(quality_path.read_text(encoding="utf-8"))
        assert quality_payload.get("passed") is False
        assert float(quality_payload.get("threshold")) == pytest.approx(0.40)
        assert int(quality_payload.get("sample_size")) == 0
        assert "no eval items generated" in str(quality_payload.get("error", ""))

        resp_eval = await client.post(f"/api/synthetic/run/{run_id}/publish/eval_dataset")
        assert resp_eval.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_eval.json().get("detail", ""))

        resp_triplets = await client.post(f"/api/synthetic/run/{run_id}/publish/triplets")
        assert resp_triplets.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_triplets.json().get("detail", ""))
    finally:
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_synthetic_run_lifecycle_with_real_provider_when_available(client) -> None:
    model = _provider_model_for_env()
    if not model:
        pytest.skip("No OPENAI_API_KEY or OPENROUTER_API_KEY available for real-provider lifecycle test")

    corpus_id = f"pytest_synth_real_{uuid.uuid4().hex[:8]}"
    root = Path(__file__).resolve().parents[2]
    run_dir: Path | None = None
    try:
        start = await client.post(
            "/api/synthetic/run/start",
            json={
                "corpus_id": corpus_id,
                "provider": "internal_ragweld",
                "recipe": "eval_dataset",
                "generator_model": model,
                "judge_model": model,
                "max_source_chunks": 10,
                "max_pairs": 10,
                "pairs_per_source": 1,
            },
        )
        assert start.status_code == 200
        run_id = str(start.json()["run_id"])
        run_dir = root / "data" / "synthetic_runs" / run_id

        terminal = await _wait_terminal(client, run_id)
        assert terminal["status"] in {"completed", "failed"}

        listed = await client.get("/api/synthetic/runs", params={"corpus_id": corpus_id, "limit": 10})
        assert listed.status_code == 200
        listed_rows = listed.json().get("runs") or []
        assert any(str(r.get("run_id")) == run_id for r in listed_rows)
    finally:
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
