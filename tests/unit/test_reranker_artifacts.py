from __future__ import annotations

from pathlib import Path

from server.reranker.artifacts import has_mlx_adapter_weights, resolve_project_path


def test_resolve_project_path_resolves_relative_against_repo_root() -> None:
    p = resolve_project_path("data")
    assert p.is_absolute()
    assert p.name == "data"


def test_has_mlx_adapter_weights_false_when_missing(tmp_path: Path) -> None:
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    assert has_mlx_adapter_weights(adapter_dir) is False


def test_has_mlx_adapter_weights_true_when_adapter_npz_present(tmp_path: Path) -> None:
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "adapter.npz").write_bytes(b"")
    assert has_mlx_adapter_weights(adapter_dir) is True
