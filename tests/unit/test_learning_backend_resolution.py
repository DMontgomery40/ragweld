from __future__ import annotations

from server.models.tribrid_config_model import TrainingConfig
from server.reranker.mlx_qwen3 import mlx_is_available
from server.retrieval.rerank import resolve_learning_backend


def test_resolve_learning_backend_transformers_forced() -> None:
    cfg = TrainingConfig(learning_reranker_backend="transformers")
    assert resolve_learning_backend(cfg) == "transformers"


def test_resolve_learning_backend_mlx_forced() -> None:
    cfg = TrainingConfig(learning_reranker_backend="mlx_qwen3")
    assert resolve_learning_backend(cfg) == "mlx_qwen3"


def test_resolve_learning_backend_auto_prefers_mlx_when_available() -> None:
    cfg = TrainingConfig(learning_reranker_backend="auto")
    expected = "mlx_qwen3" if mlx_is_available() else "transformers"
    assert resolve_learning_backend(cfg) == expected

