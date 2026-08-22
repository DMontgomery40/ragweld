from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.training.agent_artifact import (
    AgentArtifactError,
    RagweldAgentAdapterConfig,
    RagweldAgentArtifactManifest,
    agent_artifact_incompatibility,
    load_agent_artifact_manifest,
    validate_agent_artifact_dir,
    write_agent_adapter_config,
    write_agent_artifact_manifest,
)

CURRENT_BASE = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
RETIRED_BASE = "mlx-community/Qwen3-1.7B-4bit"


def _manifest(base_model: str = CURRENT_BASE, **overrides: object) -> RagweldAgentArtifactManifest:
    payload = {
        "backend": "mlx_qwen3",
        "artifact_kind": "ragweld_agent",
        "base_model": base_model,
        "run_id": "aurora_acceptance__20260822_190536",
        "created_at": 1787425561,
    }
    payload.update(overrides)
    return RagweldAgentArtifactManifest.model_validate(payload)


def test_manifest_round_trips_through_the_artifact_directory(tmp_path: Path) -> None:
    written = write_agent_artifact_manifest(tmp_path, _manifest())
    assert written.name == "manifest.json"
    loaded = load_agent_artifact_manifest(tmp_path)
    assert loaded == _manifest()


@pytest.mark.parametrize(
    "raw",
    [
        {"backend": "transformers", "artifact_kind": "ragweld_agent", "base_model": CURRENT_BASE, "run_id": "r"},
        {"backend": "mlx_qwen3", "artifact_kind": "reranker", "base_model": CURRENT_BASE, "run_id": "r"},
        {"backend": "mlx_qwen3", "artifact_kind": "ragweld_agent", "base_model": "", "run_id": "r"},
        {"backend": "mlx_qwen3", "artifact_kind": "ragweld_agent", "base_model": CURRENT_BASE},
        {"backend": "mlx_qwen3", "artifact_kind": "ragweld_agent", "base_model": CURRENT_BASE, "run_id": "r", "served": True},
    ],
    ids=["wrong-backend", "wrong-kind", "empty-base", "missing-run-id", "unknown-field"],
)
def test_invalid_manifests_are_rejected(tmp_path: Path, raw: dict[str, object]) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(AgentArtifactError, match="not a valid agent artifact manifest"):
        load_agent_artifact_manifest(tmp_path)


def test_missing_and_malformed_manifest_files_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(AgentArtifactError, match="is missing"):
        load_agent_artifact_manifest(tmp_path)
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(AgentArtifactError, match="not valid JSON"):
        load_agent_artifact_manifest(tmp_path)


def test_compatibility_requires_the_configured_base_and_backend() -> None:
    assert agent_artifact_incompatibility(_manifest(), base_model=CURRENT_BASE, backend="mlx_qwen3") is None

    retired = agent_artifact_incompatibility(_manifest(RETIRED_BASE), base_model=CURRENT_BASE, backend="mlx_qwen3")
    assert retired is not None
    assert RETIRED_BASE in retired and CURRENT_BASE in retired

    backend = agent_artifact_incompatibility(_manifest(), base_model=CURRENT_BASE, backend="unsloth")
    assert backend is not None
    assert "'mlx_qwen3'" in backend and "'unsloth'" in backend

    both = agent_artifact_incompatibility(_manifest(RETIRED_BASE), base_model=CURRENT_BASE, backend="unsloth")
    assert both is not None
    assert both.count(";") == 1


def _adapter_config(base_model: str = CURRENT_BASE, run_id: str = "aurora_acceptance__20260822_190536") -> RagweldAgentAdapterConfig:
    return RagweldAgentAdapterConfig(
        backend="mlx_qwen3",
        artifact_kind="ragweld_agent",
        base_model=base_model,
        run_id=run_id,
        lora_rank=16,
        lora_alpha=32.0,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        applied_modules=144,
    )


def _write_artifact(directory: Path, *, weights: bytes = b"\x00" * 64) -> None:
    (directory / "adapter.npz").write_bytes(weights)
    write_agent_adapter_config(directory, _adapter_config())
    write_agent_artifact_manifest(directory, _manifest())


def test_whole_directory_validation_accepts_a_complete_consistent_artifact(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    manifest = validate_agent_artifact_dir(tmp_path, expected_run_id="aurora_acceptance__20260822_190536")
    assert manifest.base_model == CURRENT_BASE


def test_missing_or_empty_weights_fail_closed(tmp_path: Path) -> None:
    write_agent_adapter_config(tmp_path, _adapter_config())
    write_agent_artifact_manifest(tmp_path, _manifest())
    with pytest.raises(AgentArtifactError, match="adapter.npz is missing"):
        validate_agent_artifact_dir(tmp_path)
    (tmp_path / "adapter.npz").write_bytes(b"")
    with pytest.raises(AgentArtifactError, match="adapter.npz is empty"):
        validate_agent_artifact_dir(tmp_path)
    (tmp_path / "adapter.npz").unlink()
    (tmp_path / "adapter.npz").mkdir()
    with pytest.raises(AgentArtifactError, match="not a regular file"):
        validate_agent_artifact_dir(tmp_path)


def test_contradictory_adapter_config_and_manifest_fail_closed(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    write_agent_adapter_config(tmp_path, _adapter_config(base_model=RETIRED_BASE))
    with pytest.raises(AgentArtifactError, match="contradicts manifest.json"):
        validate_agent_artifact_dir(tmp_path)


def test_invalid_adapter_config_fails_closed(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    (tmp_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AgentArtifactError, match="not a valid agent adapter config"):
        validate_agent_artifact_dir(tmp_path)


def test_foreign_run_artifacts_cannot_be_promoted_as_another_run(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    with pytest.raises(AgentArtifactError, match="belongs to run"):
        validate_agent_artifact_dir(tmp_path, expected_run_id="aurora_acceptance__20260821_205703")
