from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.lineage.registry import lineage_root
from server.models.tribrid_config_model import (
    SyntheticArtifactRef,
    SyntheticRun,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
)
from server.synthetic.storage import runs_dir as synthetic_runs_dir

pytestmark = pytest.mark.requires_postgres


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _create_corpus(client: AsyncClient, *, corpus_id: str, path: Path) -> None:
    response = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(path), "description": None},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_lineage_current_and_prompt_update_refresh_bundle(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_lineage_prompt_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        current_before = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_before.status_code == 200
        before = current_before.json()
        assert before["prompt_set"]["version_id"]
        assert before["config_snapshot"]["version_id"]

        prompts = await client.get("/api/prompts", params={"corpus_id": corpus_id})
        assert prompts.status_code == 200
        original = str(prompts.json()["prompts"]["query_rewrite"])

        updated = await client.put(
            "/api/prompts/query_rewrite",
            params={"corpus_id": corpus_id},
            json={"value": original + "\n\n# lineage"},
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["prompt_set_ref"]["kind"] == "prompt_set"
        assert body["bundle_id"]

        current_after = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_after.status_code == 200
        after = current_after.json()
        assert after["bundle_id"] == body["bundle_id"]
        assert after["prompt_set"]["version_id"] == body["prompt_set_ref"]["version_id"]
        assert after["bundle_id"] != before["bundle_id"]
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_config_benchmark_and_alias_endpoints(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_lineage_bundle_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        current_before = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_before.status_code == 200
        before = current_before.json()

        patched = await client.request(
            "PATCH",
            "/api/config/tokenization",
            params={"corpus_id": corpus_id},
            json={"normalize_unicode": False},
        )
        assert patched.status_code == 200

        current_after_patch = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_after_patch.status_code == 200
        after_patch = current_after_patch.json()
        assert after_patch["bundle_id"] != before["bundle_id"]
        assert after_patch["config_snapshot"]["version_id"] != before["config_snapshot"]["version_id"]

        benchmark = await client.post(
            "/api/benchmark/run",
            params={"corpus_id": corpus_id},
            json={
                "prompt": "How often is the salinity sensor array on each buoy calibrated?",
                "models": ["openrouter:openai/gpt-4o-mini", "openrouter:openai/gpt-4o-mini"],
            },
        )
        assert benchmark.status_code == 200
        run = benchmark.json()
        assert run["input_bundle_id"]
        assert run["bundle_id"]
        assert run["lineage_ref"]["kind"] == "benchmark_run"
        assert len(run["results"]) == 2

        current_after_benchmark = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_after_benchmark.status_code == 200
        bundle = current_after_benchmark.json()
        assert any(ref["version_id"] == run["lineage_ref"]["version_id"] for ref in bundle["benchmark_runs"])

        missing = await client.post(
            "/api/lineage/aliases/baseline",
            params={"corpus_id": corpus_id},
            json={"bundle_id": "bundle__missing"},
        )
        assert missing.status_code == 404

        aliased = await client.post(
            "/api/lineage/aliases/baseline",
            params={"corpus_id": corpus_id},
            json={"bundle_id": bundle["bundle_id"]},
        )
        assert aliased.status_code == 200
        aliases = aliased.json()["aliases"]
        assert any(alias["alias"] == "baseline" and alias["bundle_id"] == bundle["bundle_id"] for alias in aliases)
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_refresh_drops_old_run_refs_after_prompt_change(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_lineage_refresh_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        prompts = await client.get("/api/prompts", params={"corpus_id": corpus_id})
        assert prompts.status_code == 200
        original = str(prompts.json()["prompts"]["query_rewrite"])

        benchmark = await client.post(
            "/api/benchmark/run",
            params={"corpus_id": corpus_id},
            json={
                "prompt": "How often is the salinity sensor array on each buoy calibrated?",
                "models": ["openrouter:openai/gpt-4o-mini", "openrouter:openai/gpt-4o-mini"],
            },
        )
        assert benchmark.status_code == 200
        benchmark_body = benchmark.json()
        benchmark_version_id = benchmark_body["lineage_ref"]["version_id"]

        current_after_benchmark = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_after_benchmark.status_code == 200
        assert any(
            ref["version_id"] == benchmark_version_id
            for ref in current_after_benchmark.json()["benchmark_runs"]
        )

        updated = await client.put(
            "/api/prompts/query_rewrite",
            params={"corpus_id": corpus_id},
            json={"value": original + "\n\n# refresh lineage"},
        )
        assert updated.status_code == 200

        current_after_prompt = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_after_prompt.status_code == 200
        assert not any(
            ref["version_id"] == benchmark_version_id
            for ref in current_after_prompt.json()["benchmark_runs"]
        )
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_current_alias_round_trips_without_read_side_effects(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_lineage_current_alias_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        current_before = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_before.status_code == 200
        before = current_before.json()

        prompts = await client.get("/api/prompts", params={"corpus_id": corpus_id})
        assert prompts.status_code == 200
        original = str(prompts.json()["prompts"]["query_rewrite"])
        updated = await client.put(
            "/api/prompts/query_rewrite",
            params={"corpus_id": corpus_id},
            json={"value": original + "\n\n# alias roundtrip"},
        )
        assert updated.status_code == 200
        after = updated.json()
        assert after["bundle_id"] != before["bundle_id"]

        set_current = await client.post(
            "/api/lineage/aliases/current",
            params={"corpus_id": corpus_id},
            json={"bundle_id": before["bundle_id"]},
        )
        assert set_current.status_code == 200
        current_alias = next(row for row in set_current.json()["aliases"] if row["alias"] == "current")
        assert current_alias["bundle_id"] == before["bundle_id"]

        aliases = await client.get("/api/lineage/aliases", params={"corpus_id": corpus_id})
        assert aliases.status_code == 200
        alias_rows = aliases.json()["aliases"]
        assert any(row["alias"] == "current" and row["bundle_id"] == before["bundle_id"] for row in alias_rows)

        current_again = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_again.status_code == 200
        assert current_again.json()["bundle_id"] == before["bundle_id"]
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_current_returns_typed_503_when_current_alias_storage_is_invalid(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    corpus_id = f"pytest_lineage_invalid_current_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        current = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current.status_code == 200

        alias_path = lineage_root() / "aliases" / corpus_id / "current.json"
        alias_path.write_text('{"alias": [}\n', encoding="utf-8")

        broken = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert broken.status_code == 503
        detail = broken.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "lineage_store"
        assert detail["retryable"] is True
        assert detail["operator_hint"]
        assert str(alias_path) not in json.dumps(broken.json())
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_bundle_endpoint_preserves_404_for_missing_bundle(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_lineage_missing_bundle_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        missing = await client.get("/api/lineage/bundle/bundle__missing", params={"corpus_id": corpus_id})
        assert missing.status_code == 404
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_bundle_endpoint_returns_typed_503_when_bundle_storage_is_invalid(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    corpus_id = f"pytest_lineage_invalid_bundle_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        current = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current.status_code == 200
        bundle_id = current.json()["bundle_id"]

        bundle_path = lineage_root() / "bundles" / corpus_id / f"{bundle_id}.json"
        bundle_path.write_text('{"bundle_id": 7}\n', encoding="utf-8")

        broken = await client.get(f"/api/lineage/bundle/{bundle_id}", params={"corpus_id": corpus_id})
        assert broken.status_code == 503
        detail = broken.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "lineage_store"
        assert detail["retryable"] is True
        assert detail["operator_hint"]
        assert str(bundle_path) not in json.dumps(broken.json())
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_aliases_returns_typed_503_when_alias_storage_is_invalid(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    corpus_id = f"pytest_lineage_invalid_alias_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    try:
        current = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current.status_code == 200

        alias_path = lineage_root() / "aliases" / corpus_id / "current.json"
        alias_path.write_text('{"repo_id": "broken"}\n', encoding="utf-8")

        broken = await client.get("/api/lineage/aliases", params={"corpus_id": corpus_id})
        assert broken.status_code == 503
        detail = broken.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "lineage_store"
        assert detail["retryable"] is True
        assert detail["operator_hint"]
        assert str(alias_path) not in json.dumps(broken.json())
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_lineage_dataset_and_synthetic_publish_refresh_current_bundle(client: AsyncClient, tmp_path: Path) -> None:
    corpus_id = f"pytest_lineage_dataset_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)

    run_id = f"{corpus_id}__publish_eval"
    # The API under test resolves runs through `runs_dir()`, which pytest points at a
    # disposable directory (conftest); writing anywhere else would be a live-store leak.
    run_dir = synthetic_runs_dir() / run_id
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    eval_payload = [
        {
            "question": "What is implemented here?",
            "expected_paths": ["src/app.py"],
            "expected_answer": "Example",
            "tags": ["lineage"],
        }
    ]
    eval_path = artifact_dir / "eval_dataset.json"
    eval_path.write_text(json.dumps(eval_payload, indent=2), encoding="utf-8")

    request = SyntheticRunStartRequest(
        corpus_id=corpus_id,
        provider="grounded_qa",
        recipe="eval_dataset",
        generator_model="ragweld-local",
        judge_model="ragweld-local",
    )
    run = SyntheticRun(
        run_id=run_id,
        corpus_id=corpus_id,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        provider="grounded_qa",
        recipe="eval_dataset",
        config_snapshot={},
        config={},
        request=request,
        artifacts=[
            SyntheticArtifactRef(
                kind="eval_dataset_json",
                path=str(eval_path),
                bytes=eval_path.stat().st_size,
                created_at=datetime.now(UTC),
            )
        ],
        summary=SyntheticRunSummary(
            quality_gate_passed=True,
            quality_gate_threshold=0.40,
            quality_sample_size=1,
            quality_top1_accuracy=1.0,
            quality_topk_accuracy=1.0,
            quality_mrr=1.0,
        ),
        error=None,
    )
    (run_dir / "run.json").write_text(
        json.dumps(run.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    try:
        add_entry = await client.post(
            "/api/dataset",
            params={"corpus_id": corpus_id},
            json={
                "entry_id": "lineage-entry",
                "question": "Where is the lineage code?",
                "expected_paths": ["server/lineage/registry.py"],
                "expected_answer": "registry",
                "tags": ["lineage"],
            },
        )
        assert add_entry.status_code == 200

        current_after_dataset = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_after_dataset.status_code == 200
        assert current_after_dataset.json()["eval_dataset"]["version_id"]

        publish = await client.post(f"/api/synthetic/run/{run_id}/publish/eval_dataset")
        assert publish.status_code == 200
        body = publish.json()
        assert body["bundle_id"]
        assert body["lineage_ref"]["kind"] == "published_artifact"

        current_after_publish = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
        assert current_after_publish.status_code == 200
        bundle = current_after_publish.json()
        assert any(ref["version_id"] == body["lineage_ref"]["version_id"] for ref in bundle["published_artifacts"])
        assert bundle["eval_dataset"]["version_id"]
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_deleting_a_corpus_removes_its_lineage_state(client: AsyncClient, tmp_path: Path) -> None:
    """Corpus deletion takes the corpus-scoped lineage records with it.

    Playwright and pytest corpora used to leave `data/lineage/aliases/<corpus>/` and
    `bundles/<corpus>/` behind after `DELETE /api/corpora/{id}` (the e2e-* orphans found
    on 2026-08-24). Shared asset versions are content-addressed and must survive.
    """
    corpus_id = f"pytest_lineage_delete_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id=corpus_id, path=tmp_path)
    root = lineage_root()
    aliases_dir = root / "aliases" / corpus_id
    bundles_dir = root / "bundles" / corpus_id
    lock_path = root / "locks" / f"{corpus_id}.lock"

    patched = await client.request(
        "PATCH",
        "/api/config/tokenization",
        params={"corpus_id": corpus_id},
        json={"normalize_unicode": False},
    )
    assert patched.status_code == 200
    current = await client.get("/api/lineage/current", params={"corpus_id": corpus_id})
    assert current.status_code == 200
    bundle_id = current.json()["bundle_id"]
    aliased = await client.post(
        "/api/lineage/aliases/canary",
        params={"corpus_id": corpus_id},
        json={"bundle_id": bundle_id},
    )
    assert aliased.status_code == 200
    assert (aliases_dir / "canary.json").exists()
    assert (bundles_dir / f"{bundle_id}.json").exists()
    assert lock_path.exists()
    asset_files_before = sorted(p for p in (root / "assets").rglob("*.json"))
    assert asset_files_before, "the bundle must have captured shared asset versions"

    deleted = await client.delete(f"/api/corpora/{corpus_id}")
    assert deleted.status_code == 200, deleted.text

    assert not aliases_dir.exists()
    assert not bundles_dir.exists()
    # The lock inode is kept on purpose (unlinking a held lock breaks mutual exclusion).
    assert lock_path.exists()
    assert sorted(p for p in (root / "assets").rglob("*.json")) == asset_files_before

    # The corpus is gone from the registry, so its lineage reads answer 404 and,
    # crucially, do not recreate the directories as a side effect.
    aliases = await client.get("/api/lineage/aliases", params={"corpus_id": corpus_id})
    assert aliases.status_code == 404
    assert not aliases_dir.exists()
    again = await client.delete(f"/api/corpora/{corpus_id}")
    assert again.status_code == 404
