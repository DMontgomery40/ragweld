from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
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
from server.synthetic.recipes import resolve_synthetic_route
from server.synthetic.storage import runs_dir as synthetic_runs_dir


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
    """Test-local gate: the gateway alias is usable only if its route resolves for real."""
    cfg = TriBridConfig()
    litellm = cfg.chat.litellm
    alias = str(litellm.default_model or "").strip()
    if not (bool(litellm.enabled) and str(litellm.base_url or "").strip() and alias):
        return None
    model = f"litellm:{alias}"
    try:
        resolve_synthetic_route(cfg=cfg, model=model)
    except Exception:
        return None
    return model


def _write_gate_failed_run(*, corpus_id: str, run_id: str) -> Path:
    return _write_full_stack_run(corpus_id=corpus_id, run_id=run_id, gate_passed=False)


_VALID_TRIPLET_LINE = (
    '{"query":"Who received the email about the Aurora salinity sensor recalibration?",'
    '"positive":"notes.txt","negative":"other.txt"}\n'
)


def _write_full_stack_run(
    *,
    corpus_id: str,
    run_id: str,
    gate_passed: bool,
    triplets_text: str = _VALID_TRIPLET_LINE,
    bundle_id: str | None = None,
) -> Path:
    run_dir = synthetic_runs_dir() / run_id
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
    triplets_path.write_text(triplets_text, encoding="utf-8")

    request = SyntheticRunStartRequest(
        corpus_id=corpus_id,
        provider="grounded_qa",
        recipe="full_stack",
        generator_model="litellm:synthetic-quality",
        judge_model="litellm:synthetic-quality",
    )
    run = SyntheticRun(
        run_id=run_id,
        corpus_id=corpus_id,
        status="completed" if gate_passed else "failed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        provider="grounded_qa",
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
            quality_top1_accuracy=0.8 if gate_passed else 0.0,
            quality_topk_accuracy=0.9 if gate_passed else 0.0,
            quality_mrr=0.85 if gate_passed else 0.0,
            quality_sample_size=50,
            quality_gate_threshold=0.40,
            quality_gate_passed=gate_passed,
            quality_failure_reason=None if gate_passed else "Quality gate failed: top1=0.000 < threshold=0.400",
        ),
        error=None if gate_passed else "Quality gate failed",
        bundle_id=bundle_id,
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
                "judge_model": "litellm:synthetic-quality",
            },
            "generator_model",
        ),
        (
            {
                "generator_model": "litellm:synthetic-quality",
            },
            "judge_model",
        ),
        (
            {
                "generator_model": "   ",
                "judge_model": "litellm:synthetic-quality",
            },
            "generator_model",
        ),
        (
            {
                "generator_model": "litellm:synthetic-quality",
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
            "provider": "grounded_qa",
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
            "provider": "grounded_qa",
            "recipe": "eval_dataset",
            "generator_model": "litellm:synthetic-quality",
            "judge_model": "litellm:synthetic-quality",
        },
    )
    assert res.status_code == 422
    detail = str(res.json().get("detail", ""))
    assert "corpus_id" in detail or "repo_id" in detail


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["internal_ragweld", "unknown_provider", ""])
async def test_synthetic_start_schema_rejects_every_provider_except_grounded_qa(client, provider: str) -> None:
    corpus_id = f"pytest_synth_policy_{uuid.uuid4().hex[:8]}"
    res = await client.post(
        "/api/synthetic/run/start",
        json={
            "corpus_id": corpus_id,
            "provider": provider,
            "recipe": "eval_dataset",
            "generator_model": "litellm:synthetic-quality",
            "judge_model": "litellm:synthetic-quality",
        },
    )
    assert res.status_code == 422
    assert "provider" in str(res.json().get("detail", ""))


@pytest.mark.asyncio
async def test_synthetic_start_rejects_direct_provider_model(client) -> None:
    corpus_id = f"pytest_synth_policy_{uuid.uuid4().hex[:8]}"
    res = await client.post(
        "/api/synthetic/run/start",
        json={
            "corpus_id": corpus_id,
            "provider": "grounded_qa",
            "recipe": "eval_dataset",
            "generator_model": "openai/gpt-4o-mini",
            "judge_model": "litellm:synthetic-quality",
        },
    )
    assert res.status_code == 422
    assert "LiteLLM alias" in str(res.json().get("detail", ""))


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["baseline", "canary", "current", "promoted"])
async def test_synthetic_promote_is_refused_for_a_failed_run(client, alias: str) -> None:
    """M-12: a failed run (produced nothing, gate never passed) cannot be promoted. The four
    lineage aliases are gated server-side with a typed 409, whichever alias is targeted."""
    corpus_id = f"pytest_synth_promote_{uuid.uuid4().hex[:8]}"
    run_id = f"{corpus_id}__gate_failed"
    run_dir = _write_gate_failed_run(corpus_id=corpus_id, run_id=run_id)
    try:
        res = await client.post(f"/api/synthetic/run/{run_id}/promote/{alias}")
        assert res.status_code == 409, res.text
        detail = str(res.json().get("detail", ""))
        assert "PROMOTION_BLOCKED" in detail
        assert "failed" in detail
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_synthetic_promote_is_refused_when_the_run_has_no_bundle(client) -> None:
    """M-12: even a completed run that was never attached to a lineage bundle has no promotion
    target — the endpoint refuses rather than aliasing an empty string."""
    corpus_id = f"pytest_synth_promote_{uuid.uuid4().hex[:8]}"
    run_id = f"{corpus_id}__no_bundle"
    run_dir = _write_full_stack_run(corpus_id=corpus_id, run_id=run_id, gate_passed=True, bundle_id=None)
    try:
        res = await client.post(f"/api/synthetic/run/{run_id}/promote/current")
        assert res.status_code == 409, res.text
        assert "not attached to a lineage bundle" in str(res.json().get("detail", ""))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_synthetic_promote_missing_run_is_404(client) -> None:
    res = await client.post("/api/synthetic/run/pytest_synth_promote_absent__x/promote/current")
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_synthetic_promote_points_alias_at_a_completed_run_bundle(client) -> None:
    """M-12: a completed, gate-passed run that is attached to a real bundle promotes; the alias
    now points at that bundle. Exercised against the isolated lineage root the conftest provides,
    with a real bundle written through the lineage registry (no mocks)."""
    from server.lineage import create_or_update_bundle, list_aliases

    corpus_id = f"pytest_synth_promote_{uuid.uuid4().hex[:8]}"
    bundle, _aliases = create_or_update_bundle(repo_id=corpus_id, metadata={"source": "pytest-m12"})
    run_id = f"{corpus_id}__passed"
    run_dir = _write_full_stack_run(
        corpus_id=corpus_id, run_id=run_id, gate_passed=True, bundle_id=bundle.bundle_id
    )
    try:
        res = await client.post(f"/api/synthetic/run/{run_id}/promote/canary")
        assert res.status_code == 200, res.text
        aliases = {row["alias"]: row["bundle_id"] for row in res.json().get("aliases", [])}
        assert aliases.get("canary") == bundle.bundle_id, aliases
        # Persisted through the store, not just echoed.
        persisted = {a.alias: a.bundle_id for a in list_aliases(repo_id=corpus_id)}
        assert persisted.get("canary") == bundle.bundle_id, persisted
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_synthetic_publish_endpoints_blocked_when_quality_gate_failed(client) -> None:
    corpus_id = f"pytest_synth_gate_{uuid.uuid4().hex[:8]}"
    run_id = f"{corpus_id}__gate_failed"
    run_dir = _write_gate_failed_run(corpus_id=corpus_id, run_id=run_id)

    try:
        resp_eval = await client.post(f"/api/synthetic/run/{run_id}/publish/eval_dataset")
        assert resp_eval.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_eval.json().get("detail", ""))

        resp_triplets = await client.post(f"/api/synthetic/run/{run_id}/publish/triplets")
        assert resp_triplets.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_triplets.json().get("detail", ""))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_synthetic_run_without_indexed_chunks_fails_closed_and_blocks_publish(client, tmp_path: Path) -> None:
    """A registered corpus with nothing indexed cannot generate rows: the run fails with the exact
    reason before any gateway call, writes no artifacts, and the quality-gated publish endpoints stay closed."""
    model = "litellm:openai.gpt-5.6-luna"

    corpus_id = f"pytest_synth_gate_art_{uuid.uuid4().hex[:8]}"
    run_dir: Path | None = None
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    created = await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_root)})
    assert created.status_code == 200, created.text

    try:
        start = await client.post(
            "/api/synthetic/run/start",
            json={
                "corpus_id": corpus_id,
                "provider": "grounded_qa",
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
        run_dir = synthetic_runs_dir() / run_id

        terminal = await _wait_terminal(client, run_id)
        assert terminal["status"] == "failed"
        assert "No indexed source chunks found" in str(terminal.get("error", ""))
        assert terminal.get("artifacts") == []
        summary = terminal.get("summary", {})
        assert summary.get("quality_gate_passed") is None
        assert summary.get("items_generated") == 0

        resp_eval = await client.post(f"/api/synthetic/run/{run_id}/publish/eval_dataset")
        assert resp_eval.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_eval.json().get("detail", ""))

        resp_triplets = await client.post(f"/api/synthetic/run/{run_id}/publish/triplets")
        assert resp_triplets.status_code == 409
        assert "QUALITY_GATE_FAILED" in str(resp_triplets.json().get("detail", ""))
    finally:
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_synthetic_start_refuses_an_unknown_corpus_instead_of_using_global_config(client) -> None:
    res = await client.post(
        "/api/synthetic/run/start",
        json={
            "corpus_id": f"pytest_synth_missing_{uuid.uuid4().hex[:8]}",
            "provider": "grounded_qa",
            "recipe": "eval_dataset",
            "generator_model": "litellm:openai.gpt-5.6-luna",
            "judge_model": "litellm:openai.gpt-5.6-luna",
        },
    )
    assert res.status_code == 404, res.text


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_publish_triplets_replaces_the_live_file_through_the_validated_boundary(client, tmp_path: Path) -> None:
    """Publishing crosses the run artifact into the training boundary: rows are validated as
    TripletRows and swapped in atomically; a corrupt artifact is a 409 and an empty one a 400,
    and neither touches the live triplets file."""
    corpus_id = f"pytest_synth_publish_{uuid.uuid4().hex[:8]}"
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    live = tmp_path / "triplets.jsonl"
    live.write_text(
        json.dumps({"query": "Which buoy reported the largest salinity drift in March?", "positive": "a.txt", "negative": "b.txt"})
        + "\n",
        encoding="utf-8",
    )
    created = await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_root)})
    assert created.status_code == 200, created.text
    run_dirs: list[Path] = []
    try:
        patched = await client.request(
            "PATCH", f"/api/config/training?corpus_id={corpus_id}", json={"tribrid_triplets_path": str(live)}
        )
        assert patched.status_code == 200, patched.text

        good_run = f"{corpus_id}__good"
        run_dirs.append(_write_full_stack_run(corpus_id=corpus_id, run_id=good_run, gate_passed=True))
        os.chmod(live, 0o600)  # codex pass 17: the operator's restrictive mode survives the parked replacement
        published = await client.post(f"/api/synthetic/run/{good_run}/publish/triplets")
        assert published.status_code == 200, published.text
        assert stat.S_IMODE(live.stat().st_mode) == 0o600
        assert published.json()["target_path"] == str(live)
        assert "Published 1 triplets" in published.json()["message"]
        rows = [json.loads(ln) for ln in live.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert [r["negative"] for r in rows] == ["other.txt"], rows  # replaced, not appended
        assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]

        corrupt_run = f"{corpus_id}__corrupt"
        run_dirs.append(
            _write_full_stack_run(
                corpus_id=corpus_id,
                run_id=corrupt_run,
                gate_passed=True,
                triplets_text=_VALID_TRIPLET_LINE + '{"query": "broken\n',
            )
        )
        refused = await client.post(f"/api/synthetic/run/{corrupt_run}/publish/triplets")
        assert refused.status_code == 409, refused.text
        assert "TRIPLETS_ARTIFACT_CORRUPT" in refused.json()["detail"]

        byte_corrupt_run = f"{corpus_id}__bytes"
        run_dirs.append(
            _write_full_stack_run(corpus_id=corpus_id, run_id=byte_corrupt_run, gate_passed=True)
        )
        (run_dirs[-1] / "artifacts" / "triplets.jsonl").write_bytes(_VALID_TRIPLET_LINE.encode("utf-8") + b"\xff\xfe\n")
        refused_bytes = await client.post(f"/api/synthetic/run/{byte_corrupt_run}/publish/triplets")
        assert refused_bytes.status_code == 409, refused_bytes.text
        assert "TRIPLETS_ARTIFACT_CORRUPT" in refused_bytes.json()["detail"]

        empty_run = f"{corpus_id}__empty"
        run_dirs.append(
            _write_full_stack_run(corpus_id=corpus_id, run_id=empty_run, gate_passed=True, triplets_text="\n")
        )
        refused_empty = await client.post(f"/api/synthetic/run/{empty_run}/publish/triplets")
        assert refused_empty.status_code == 400, refused_empty.text
        assert "EMPTY_ARTIFACT" in refused_empty.json()["detail"]

        rows_after = [json.loads(ln) for ln in live.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert rows_after == rows  # the refused publishes left the live file exactly as the good one wrote it

        # Codex pass 12: lineage failure after the file was replaced used to leave the new dataset
        # live with no published bundle. A regular file where the alias directory must be created
        # makes the lineage write fail for real; the previous rows must come back.
        from server.lineage.registry import lineage_root

        alias_dir = lineage_root() / "aliases" / corpus_id
        current_alias = alias_dir / "current.json"
        saved_alias = current_alias.read_text(encoding="utf-8") if current_alias.is_file() else None
        if current_alias.exists():
            current_alias.unlink()
        current_alias.mkdir(parents=True)  # a directory where the alias file must be renamed into place
        try:
            second_run = f"{corpus_id}__second"
            run_dirs.append(
                _write_full_stack_run(
                    corpus_id=corpus_id,
                    run_id=second_run,
                    gate_passed=True,
                    triplets_text=_VALID_TRIPLET_LINE.replace("other.txt", "third.txt"),
                )
            )
            failed = await client.post(f"/api/synthetic/run/{second_run}/publish/triplets")
            # Codex pass 16: a lineage-store failure after rollback is a typed 503, not a client error
            assert failed.status_code == 503, failed.text
            assert failed.json()["detail"]["dependency"] == "lineage_store", failed.text
            restored = [json.loads(ln) for ln in live.read_text(encoding="utf-8").splitlines() if ln.strip()]
            assert restored == rows, restored  # the previous dataset is back, not the un-recorded new one
            # Codex pass 13: a corrupt previous file must come back byte-for-byte too (it was lost before)
            corrupt_bytes = b'{"query": "broken\n\xff\xfe'
            live.write_bytes(corrupt_bytes)
            failed_again = await client.post(f"/api/synthetic/run/{second_run}/publish/triplets")
            assert failed_again.status_code == 503, failed_again.text
            assert live.read_bytes() == corrupt_bytes
            assert not [p for p in live.parent.iterdir() if p.name.endswith(".prev")]  # parked file put back, nothing stranded
        finally:
            shutil.rmtree(current_alias, ignore_errors=True)
            if saved_alias is not None:
                current_alias.write_text(saved_alias, encoding="utf-8")
    finally:
        for run_dir in run_dirs:
            shutil.rmtree(run_dir, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_synthetic_runs_listing_reports_unreadable_run_directories_instead_of_hiding_them(client) -> None:
    """A run.json that no longer validates (here: a provider that was replaced) is reported in
    `unreadable`, and the readable runs of the corpus still list normally."""
    corpus_id = f"pytest_synth_unreadable_{uuid.uuid4().hex[:8]}"
    good_dir = _write_full_stack_run(corpus_id=corpus_id, run_id=f"{corpus_id}__good", gate_passed=True)
    stale_dir = synthetic_runs_dir() / f"{corpus_id}__stale_provider"
    stale_dir.mkdir(parents=True, exist_ok=True)
    stale = json.loads((good_dir / "run.json").read_text(encoding="utf-8"))
    stale["run_id"] = f"{corpus_id}__stale_provider"
    stale["provider"] = "synthetic_data_kit"  # the replaced provider: not a valid SyntheticProvider any more
    stale["request"]["provider"] = "synthetic_data_kit"
    (stale_dir / "run.json").write_text(json.dumps(stale), encoding="utf-8")
    other_corpus = f"{corpus_id}_other"
    other_dir = synthetic_runs_dir() / f"{other_corpus}__stale_provider"
    other_dir.mkdir(parents=True, exist_ok=True)
    other = dict(stale, run_id=f"{other_corpus}__stale_provider", corpus_id=other_corpus)
    (other_dir / "run.json").write_text(json.dumps(other), encoding="utf-8")
    garbage_dir = synthetic_runs_dir() / f"{corpus_id}__garbage"
    garbage_dir.mkdir(parents=True, exist_ok=True)
    (garbage_dir / "run.json").write_text("{not json", encoding="utf-8")
    orphan_dir = synthetic_runs_dir() / f"{corpus_id}__orphan"
    (orphan_dir / "artifacts").mkdir(parents=True, exist_ok=True)  # crashed before run.json was committed
    try:
        res = await client.get(f"/api/synthetic/runs?corpus_id={corpus_id}&limit=10")
        assert res.status_code == 200, res.text
        body = res.json()
        assert [r["run_id"] for r in body["runs"]] == [f"{corpus_id}__good"]
        unreadable = {u["run_id"]: u for u in body["unreadable"]}
        assert f"{corpus_id}__stale_provider" in unreadable, body
        assert "provider" in unreadable[f"{corpus_id}__stale_provider"]["reason"]
        assert unreadable[f"{corpus_id}__stale_provider"]["corpus_id"] == corpus_id
        # a malformed run that still names another corpus is that corpus' problem ...
        assert f"{other_corpus}__stale_provider" not in unreadable, body
        # ... but one whose payload cannot be read at all is shown under every filter
        assert unreadable[f"{corpus_id}__garbage"]["corpus_id"] is None
        # a run directory with no run.json at all is reported, not hidden (codex pass 8)
        assert unreadable[f"{corpus_id}__orphan"]["reason"] == "run.json is missing"
    finally:
        shutil.rmtree(good_dir, ignore_errors=True)
        shutil.rmtree(stale_dir, ignore_errors=True)
        shutil.rmtree(other_dir, ignore_errors=True)
        shutil.rmtree(garbage_dir, ignore_errors=True)
        shutil.rmtree(orphan_dir, ignore_errors=True)
