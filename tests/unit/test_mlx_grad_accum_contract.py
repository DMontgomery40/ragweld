from __future__ import annotations

from server.training.mlx_qwen3_trainer import accumulate_grads, average_grads


def test_accumulate_grads_sums_tree_then_average_divides() -> None:
    g1 = {"a": 1.0, "b": [2.0, 3.0], "c": (4.0,)}
    g2 = {"a": 10.0, "b": [20.0, 30.0], "c": (40.0,)}

    acc = accumulate_grads(None, g1)
    assert acc == g1

    acc2 = accumulate_grads(acc, g2)
    assert acc2["a"] == 11.0
    assert acc2["b"] == [22.0, 33.0]
    assert acc2["c"] == (44.0,)

    avg = average_grads(acc2, steps=2)
    assert avg["a"] == 5.5
    assert avg["b"] == [11.0, 16.5]
    assert avg["c"] == (22.0,)

