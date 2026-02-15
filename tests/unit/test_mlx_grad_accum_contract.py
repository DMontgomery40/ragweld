from __future__ import annotations

from server.training.mlx_qwen3_trainer import (
    _orthogonalize_direction_dict,
    _iter_trainable_named_params,
    accumulate_grads,
    average_grads,
)


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


def test_iter_trainable_named_params_accepts_variable_tuple_shapes() -> None:
    class FakeTensor:
        def __init__(self, shape: tuple[int, ...]) -> None:
            self.shape = shape

    class FakeModel:
        def trainable_parameters(self):  # noqa: ANN201
            return [
                ("lora_a", "meta", FakeTensor((2, 3))),
                ("lora_b", FakeTensor((5,))),
                ("bad_only_name",),
                "bad_not_tuple",
                ["layer0", "lora_c", "meta", FakeTensor((7, 11))],
                ("meta", object(), "still_bad"),
            ]

    got = list(_iter_trainable_named_params(FakeModel()))
    assert got[0][0] == "lora_a.meta"
    assert got[0][1].shape == (2, 3)
    assert got[1][0] == "lora_b"
    assert got[1][1].shape == (5,)
    assert got[2][0] == "layer0.lora_c.meta"
    assert got[2][1].shape == (7, 11)
    assert len(got) == 3


def test_iter_trainable_named_params_flattens_nested_tree_shape() -> None:
    class FakeTensor:
        def __init__(self, shape: tuple[int, ...]) -> None:
            self.shape = shape
            self.size = 1

    class FakeModel:
        def trainable_parameters(self):  # noqa: ANN201
            return {
                "model": {
                    "layers": [
                        {"self_attn": {"q_proj": {"lora_A": FakeTensor((2, 4))}}},
                        {"mlp": {"up_proj": {"lora_B": FakeTensor((4, 2))}}},
                    ]
                }
            }

    got = list(_iter_trainable_named_params(FakeModel()))
    names = [n for n, _ in got]
    assert "model.layers.0.self_attn.q_proj.lora_A" in names
    assert "model.layers.1.mlp.up_proj.lora_B" in names
    assert len(got) == 2


def test_orthogonalize_direction_dict_removes_parallel_component() -> None:
    d1 = {"a": 1.0, "b": -2.0, "c": 0.5}
    d2 = {"a": 3.0, "b": 4.0, "c": -1.0}

    def dot_fn(x: dict[str, float], y: dict[str, float]) -> float:
        return float(sum(float(x[k]) * float(y.get(k, 0.0)) for k in x))

    out = _orthogonalize_direction_dict(d1, d2, dot_fn=dot_fn)
    assert abs(dot_fn(d1, out)) < 1e-9
