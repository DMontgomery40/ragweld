from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(path_str: str) -> Path:
    """Resolve a potentially-relative path against the repo root.

    Notes:
    - Mirrors the backend pattern used for config paths (relative => project root).
    - Pure-stdlib to keep this module import-safe for optional ML backends.
    """
    p = Path(str(path_str or "")).expanduser()
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


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
