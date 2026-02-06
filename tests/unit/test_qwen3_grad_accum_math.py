"""Structural contract tests for gradient accumulation math.

Verifies that:
1. accumulate_grads sums gradients correctly
2. average_grads divides by step count
3. The product (accumulate N → average N) matches the expected average

These tests do NOT require MLX — the functions operate on plain Python structures
via tree_map, so we test with dict/list nesting.
"""

from __future__ import annotations

import math


def _make_grad(val: float) -> dict[str, list[float]]:
    """Helper: create a simple nested grad structure."""
    return {"layer1": [val, val * 2], "layer2": [val * 3]}


def test_accumulate_grads_sums_two_grad_trees() -> None:
    from server.training.mlx_qwen3_trainer import accumulate_grads

    g1 = _make_grad(1.0)
    g2 = _make_grad(2.0)

    acc = accumulate_grads(None, g1)
    assert acc["layer1"][0] == 1.0
    assert acc["layer1"][1] == 2.0
    assert acc["layer2"][0] == 3.0

    acc = accumulate_grads(acc, g2)
    assert acc["layer1"][0] == 3.0   # 1+2
    assert acc["layer1"][1] == 6.0   # 2+4
    assert acc["layer2"][0] == 9.0   # 3+6


def test_average_grads_divides_by_step_count() -> None:
    from server.training.mlx_qwen3_trainer import average_grads

    g = _make_grad(10.0)
    avg = average_grads(g, steps=5)
    assert math.isclose(avg["layer1"][0], 2.0, rel_tol=1e-9)
    assert math.isclose(avg["layer1"][1], 4.0, rel_tol=1e-9)
    assert math.isclose(avg["layer2"][0], 6.0, rel_tol=1e-9)


def test_average_grads_clamps_steps_to_minimum_one() -> None:
    from server.training.mlx_qwen3_trainer import average_grads

    g = _make_grad(10.0)
    avg = average_grads(g, steps=0)
    assert math.isclose(avg["layer1"][0], 10.0, rel_tol=1e-9)


def test_accumulate_then_average_gives_mean() -> None:
    """Accumulate N grads then average by N: result == mean."""
    from server.training.mlx_qwen3_trainer import accumulate_grads, average_grads

    grads = [_make_grad(float(i + 1)) for i in range(8)]
    acc = None
    for g in grads:
        acc = accumulate_grads(acc, g)

    avg = average_grads(acc, steps=8)

    # Expected mean of [1..8] for layer1[0]
    expected_mean = sum(float(i + 1) for i in range(8)) / 8.0
    assert math.isclose(avg["layer1"][0], expected_mean, rel_tol=1e-9)

    # layer1[1] is 2x, layer2[0] is 3x
    assert math.isclose(avg["layer1"][1], expected_mean * 2, rel_tol=1e-9)
    assert math.isclose(avg["layer2"][0], expected_mean * 3, rel_tol=1e-9)


def test_triplets_to_pairs_caps_negative_ratio() -> None:
    """Negative ratio is capped at 5 regardless of config."""
    from server.training.mlx_qwen3_trainer import LabeledPair, triplets_to_pairs
    from server.training.reranker_trainer import MaterializedTriplet

    triplets = [
        MaterializedTriplet(query=f"q{i}", positive_text=f"pos{i}", negative_text=f"neg{i}")
        for i in range(10)
    ]

    pairs = triplets_to_pairs(triplets, negative_ratio=20)  # request 20, should cap at 5

    positives = [p for p in pairs if p.label == 1]
    negatives = [p for p in pairs if p.label == 0]
    assert len(positives) == 10
    # Each triplet should generate at most 5 negatives
    assert len(negatives) <= 10 * 5


def test_deterministic_split_is_reproducible() -> None:
    from server.training.mlx_qwen3_trainer import deterministic_split

    items = list(range(100))
    train1, dev1 = deterministic_split(items, dev_split=0.1, seed=0)
    train2, dev2 = deterministic_split(items, dev_split=0.1, seed=0)

    assert train1 == train2
    assert dev1 == dev2
    assert len(dev1) == 10  # 10% of 100
    assert len(train1) == 90
