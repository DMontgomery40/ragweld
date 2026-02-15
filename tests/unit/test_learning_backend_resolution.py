from __future__ import annotations

import platform

import pytest

from server.models.tribrid_config_model import TrainingConfig
from server.reranker.mlx_qwen3 import mlx_is_available
from server.retrieval.rerank import resolve_learning_backend


def test_resolve_learning_backend_transformers_forced() -> None:
    cfg = TrainingConfig(learning_reranker_backend="transformers")
    assert resolve_learning_backend(cfg) == "transformers"


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
    expected = "mlx_qwen3" if mlx_is_available() else "transformers"
    assert resolve_learning_backend(cfg) == expected
