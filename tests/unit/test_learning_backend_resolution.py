from __future__ import annotations

import platform

import pytest

from server.models.tribrid_config_model import TrainingConfig
from server.reranker.mlx_qwen3 import mlx_is_available
from server.retrieval.rerank import resolve_learning_backend, resolve_learning_backend_with_reason


def test_resolve_learning_backend_transformers_forced() -> None:
    cfg = TrainingConfig(learning_reranker_backend="transformers")
    assert resolve_learning_backend(cfg) == "transformers"


def test_resolve_learning_backend_mlx_forced() -> None:
    is_apple_silicon = platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    cfg = TrainingConfig(learning_reranker_backend="mlx_qwen3")
    if is_apple_silicon and mlx_is_available():
        assert resolve_learning_backend(cfg) == "mlx_qwen3"
    else:
        with pytest.raises(RuntimeError, match="mlx_qwen3"):
            resolve_learning_backend(cfg)


def test_resolve_learning_backend_auto_prefers_mlx_when_available() -> None:
    cfg = TrainingConfig(learning_reranker_backend="auto")
    expected = "mlx_qwen3" if mlx_is_available() else "transformers"
    assert resolve_learning_backend(cfg) == expected


def test_resolve_learning_backend_mlx_forced_unsupported_platform() -> None:
    """Forcing mlx_qwen3 on a non-macOS-arm64 platform must raise RuntimeError."""
    is_apple_silicon = platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    if is_apple_silicon and mlx_is_available():
        pytest.skip("Running on Apple Silicon with MLX — cannot test unsupported platform error path")

    cfg = TrainingConfig(learning_reranker_backend="mlx_qwen3")
    with pytest.raises(RuntimeError, match="mlx_qwen3"):
        resolve_learning_backend(cfg)


def test_resolve_learning_backend_with_reason_returns_reason_string() -> None:
    cfg = TrainingConfig(learning_reranker_backend="transformers")
    backend, reason = resolve_learning_backend_with_reason(cfg)
    assert backend == "transformers"
    assert "forced by config" in reason


def test_resolve_learning_backend_with_reason_auto() -> None:
    cfg = TrainingConfig(learning_reranker_backend="auto")
    backend, reason = resolve_learning_backend_with_reason(cfg)
    assert backend in {"mlx_qwen3", "transformers"}
    assert "auto:" in reason


def test_resolve_learning_backend_none_config_defaults_to_auto() -> None:
    backend, reason = resolve_learning_backend_with_reason(None)
    assert backend in {"mlx_qwen3", "transformers"}
    assert "auto:" in reason

