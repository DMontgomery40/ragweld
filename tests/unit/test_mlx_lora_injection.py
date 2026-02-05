from __future__ import annotations

import pytest


def test_apply_lora_layers_wraps_target_linear_modules() -> None:
    mlx = pytest.importorskip("mlx")  # only runs on Apple Silicon dev envs with MLX installed
    pytest.importorskip("mlx.nn")
    pytest.importorskip("mlx.core")

    import mlx.core as mx
    import mlx.nn as nn

    from server.reranker.mlx_qwen3 import apply_lora_layers

    class Tiny(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.q_proj = nn.Linear(8, 8)
            self.other = nn.Linear(8, 8)

        def __call__(self, x: mx.array) -> mx.array:
            # Use both so named_modules contains them and the wrapper is exercised.
            return self.q_proj(x) + self.other(x)

    m = Tiny()
    wrapped = apply_lora_layers(m, rank=4, alpha=8.0, dropout=0.0, target_modules=["q_proj"])
    assert wrapped == 1

    # q_proj is now a LoRA-wrapped module with trainable matrices.
    assert hasattr(m.q_proj, "lora_A")
    assert hasattr(m.q_proj, "lora_B")
    assert tuple(m.q_proj.lora_A.shape) == (4, 8)
    assert tuple(m.q_proj.lora_B.shape) == (8, 4)

    # Sanity: forward still works.
    x = mx.ones((2, 8))
    y = m(x)
    mx.eval(y)
    assert tuple(y.shape) == (2, 8)

