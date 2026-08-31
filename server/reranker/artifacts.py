from __future__ import annotations

from pathlib import Path

# Repo-root path resolution lives in one module; re-exported here so the existing
# `from server.reranker.artifacts import resolve_project_path` sites keep working.
from server.project_paths import resolve_project_path

__all__ = ["has_mlx_adapter_weights", "resolve_project_path"]


def has_mlx_adapter_weights(adapter_dir: Path) -> bool:
    """Best-effort check for an MLX LoRA adapter directory.

    We treat the presence of `adapter.npz` as the canonical signal.
    Keep this module import-safe (no MLX imports).
    """
    try:
        if not adapter_dir.exists() or not adapter_dir.is_dir():
            return False
    except Exception:
        return False

    try:
        return (adapter_dir / "adapter.npz").exists()
    except Exception:
        return False
