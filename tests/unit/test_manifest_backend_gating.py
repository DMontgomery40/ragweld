from __future__ import annotations

import json
from pathlib import Path

from server.reranker.mlx_qwen3 import (
    is_mlx_qwen3_artifact_compatible,
    read_manifest,
    read_manifest_backend,
)


def _write_manifest(dir_path: Path, obj: dict) -> None:
    (dir_path / "tribrid_reranker_manifest.json").write_text(json.dumps(obj) + "\n", encoding="utf-8")


def test_read_manifest_backend_missing_returns_none(tmp_path: Path) -> None:
    assert read_manifest_backend(tmp_path) is None
    assert read_manifest(tmp_path) is None


def test_read_manifest_backend_reads_backend(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"backend": "mlx_qwen3", "base_model": "Qwen/Qwen3-Reranker-0.6B"})
    assert read_manifest_backend(tmp_path) == "mlx_qwen3"


def test_is_mlx_qwen3_artifact_compatible_requires_backend_and_base_model_match(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"backend": "transformers", "base_model": "Qwen/Qwen3-Reranker-0.6B"})
    assert is_mlx_qwen3_artifact_compatible(artifact_dir=tmp_path, base_model="Qwen/Qwen3-Reranker-0.6B") is False

    _write_manifest(tmp_path, {"backend": "mlx_qwen3", "base_model": "other"})
    assert is_mlx_qwen3_artifact_compatible(artifact_dir=tmp_path, base_model="Qwen/Qwen3-Reranker-0.6B") is False

    _write_manifest(tmp_path, {"backend": "mlx_qwen3", "base_model": "Qwen/Qwen3-Reranker-0.6B"})
    assert is_mlx_qwen3_artifact_compatible(artifact_dir=tmp_path, base_model="Qwen/Qwen3-Reranker-0.6B") is True

