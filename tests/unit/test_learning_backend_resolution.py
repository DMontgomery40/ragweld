from __future__ import annotations

import platform

import pytest
from pydantic import ValidationError

from server.models.tribrid_config_model import TrainingConfig
from server.retrieval.mlx_qwen3 import mlx_is_available
from server.retrieval.rerank import resolve_learning_backend


@pytest.mark.parametrize("legacy_backend", ["transformers", "hf", "mlx"])
def test_learning_backend_aliases_are_rejected_by_the_schema(legacy_backend: str) -> None:
    """Only the real backend ids exist; stale aliases fail validation instead of being normalized."""
    with pytest.raises(ValidationError):
        TrainingConfig(learning_reranker_backend=legacy_backend)


def test_resolve_learning_backend_mlx_forced() -> None:
    cfg = TrainingConfig(learning_reranker_backend="mlx_qwen3")
    supported_platform = platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    if supported_platform and mlx_is_available():
        assert resolve_learning_backend(cfg) == "mlx_qwen3"
        return

    with pytest.raises(RuntimeError):
        resolve_learning_backend(cfg)


def test_resolve_learning_backend_auto_prefers_mlx_when_available() -> None:
    cfg = TrainingConfig(learning_reranker_backend="auto")
    supported_platform = platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    if supported_platform and mlx_is_available():
        assert resolve_learning_backend(cfg) == "mlx_qwen3"
        return
    with pytest.raises(RuntimeError):
        resolve_learning_backend(cfg)
