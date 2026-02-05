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


def has_transformers_weights(model_dir: Path) -> bool:
    """Best-effort check for a saved Transformers model directory with weights present.

    We intentionally avoid importing Transformers here; callers use this as a fast guard
    before attempting to load an artifact.
    """
    try:
        if not model_dir.exists() or not model_dir.is_dir():
            return False
    except Exception:
        return False

    # Most common single-file weight formats.
    for name in ("model.safetensors", "pytorch_model.bin", "tf_model.h5", "flax_model.msgpack"):
        try:
            if (model_dir / name).exists():
                return True
        except Exception:
            continue

    # Sharded weights (common for safetensors): model-00001-of-00002.safetensors
    # Sharded PyTorch weights: pytorch_model-00001-of-00002.bin
    try:
        for p in model_dir.iterdir():
            if not p.is_file():
                continue
            n = p.name
            if n.startswith("model-") and n.endswith(".safetensors"):
                return True
            if n.startswith("pytorch_model-") and n.endswith(".bin"):
                return True
    except Exception:
        return False

    return False


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
