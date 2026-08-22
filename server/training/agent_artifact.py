"""Persisted Learning Agent adapter artifact manifest.

An agent adapter directory (`adapter.npz` + `adapter_config.json` + `manifest.json`)
is a training-only artifact: it is the baseline for later runs and lineage, and
it is never served by the chat gateway (all generation routes through LiteLLM).
The manifest is a persisted boundary, so it is validated here and every
promotion checks it against the configured base model and backend before an
artifact trained on another base can overwrite the active one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MANIFEST_FILENAME = "manifest.json"
ADAPTER_CONFIG_FILENAME = "adapter_config.json"
ADAPTER_WEIGHTS_FILENAME = "adapter.npz"
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class AgentArtifactError(RuntimeError):
    """The artifact directory does not carry a valid agent manifest."""


class RagweldAgentArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["mlx_qwen3"]
    artifact_kind: Literal["ragweld_agent"]
    base_model: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    created_at: int | None = None


class RagweldAgentAdapterConfig(BaseModel):
    """`adapter_config.json` written next to `adapter.npz` by the MLX trainer."""

    model_config = ConfigDict(extra="forbid")

    backend: Literal["mlx_qwen3"]
    artifact_kind: Literal["ragweld_agent"]
    base_model: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    lora_rank: int = Field(ge=1)
    lora_alpha: float = Field(gt=0)
    lora_dropout: float = Field(ge=0, le=1)
    target_modules: list[str] = Field(min_length=1)
    applied_modules: int = Field(ge=1)


def _read_json_model(path: Path, model: type[_ModelT], *, label: str) -> _ModelT:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AgentArtifactError(f"{path} is missing") from exc
    except (OSError, ValueError) as exc:
        raise AgentArtifactError(f"{path} is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise AgentArtifactError(f"{path} is not a valid {label}: {exc}") from exc


def load_agent_adapter_config(artifact_dir: Path) -> RagweldAgentAdapterConfig:
    return _read_json_model(Path(artifact_dir) / ADAPTER_CONFIG_FILENAME, RagweldAgentAdapterConfig, label="agent adapter config")


def validate_agent_artifact_dir(artifact_dir: Path, *, expected_run_id: str | None = None) -> RagweldAgentArtifactManifest:
    """Validate the whole adapter directory, not just its manifest.

    Requires a regular, non-empty `adapter.npz`, a valid `adapter_config.json`, a valid
    `manifest.json`, agreement between the two JSON files on backend/base/run, and
    (when given) the run the caller believes it is promoting.
    """

    directory = Path(artifact_dir)
    weights = directory / ADAPTER_WEIGHTS_FILENAME
    if not weights.is_file():
        raise AgentArtifactError(f"{weights} is missing or not a regular file")
    if weights.stat().st_size <= 0:
        raise AgentArtifactError(f"{weights} is empty")
    adapter_config = load_agent_adapter_config(directory)
    manifest = load_agent_artifact_manifest(directory)
    if (adapter_config.backend, adapter_config.artifact_kind, adapter_config.base_model, adapter_config.run_id) != (
        manifest.backend,
        manifest.artifact_kind,
        manifest.base_model,
        manifest.run_id,
    ):
        raise AgentArtifactError(
            f"{directory}: adapter_config.json ({adapter_config.backend}/{adapter_config.base_model}/{adapter_config.run_id}) "
            f"contradicts manifest.json ({manifest.backend}/{manifest.base_model}/{manifest.run_id})"
        )
    if expected_run_id is not None and manifest.run_id != str(expected_run_id):
        raise AgentArtifactError(f"{directory} belongs to run {manifest.run_id!r}, not {expected_run_id!r}")
    return manifest


def load_agent_artifact_manifest(artifact_dir: Path) -> RagweldAgentArtifactManifest:
    path = Path(artifact_dir) / MANIFEST_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AgentArtifactError(f"{path} is missing") from exc
    except (OSError, ValueError) as exc:
        raise AgentArtifactError(f"{path} is not valid JSON: {exc}") from exc
    try:
        return RagweldAgentArtifactManifest.model_validate(raw)
    except ValidationError as exc:
        raise AgentArtifactError(f"{path} is not a valid agent artifact manifest: {exc}") from exc


def agent_artifact_incompatibility(
    manifest: RagweldAgentArtifactManifest,
    *,
    base_model: str,
    backend: str,
) -> str | None:
    """Return why the artifact cannot be used with the configured agent, or None."""

    reasons: list[str] = []
    expected_backend = str(backend or "").strip()
    expected_base = str(base_model or "").strip()
    if manifest.backend != expected_backend:
        reasons.append(f"artifact backend {manifest.backend!r} != configured {expected_backend!r}")
    if manifest.base_model != expected_base:
        reasons.append(f"artifact was trained on {manifest.base_model!r}, configured base is {expected_base!r}")
    return "; ".join(reasons) or None


def write_agent_adapter_config(artifact_dir: Path, adapter_config: RagweldAgentAdapterConfig) -> Path:
    path = Path(artifact_dir) / ADAPTER_CONFIG_FILENAME
    path.write_text(json.dumps(adapter_config.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return path


def write_agent_artifact_manifest(artifact_dir: Path, manifest: RagweldAgentArtifactManifest) -> Path:
    path = Path(artifact_dir) / MANIFEST_FILENAME
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return path
