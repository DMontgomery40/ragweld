#!/usr/bin/env python3
"""Deterministic catalog equality and generated UI/schema coverage checks."""
import importlib.util
import json
import sys
from pathlib import Path

def _normalize_relpath(p: Path) -> str:
    try:
        rel = p.relative_to(Path.cwd())
    except Exception:
        rel = p
    # Normalize path separators for stable output across platforms.
    return str(rel).replace("\\", "/")

def check_models_catalog_mirror_sync() -> list[str]:
    """Fail when data/models.json and web/public/models.json diverge."""
    errors: list[str] = []
    data_path = Path("data/models.json")
    web_path = Path("web/public/models.json")

    if not data_path.exists():
        errors.append("data/models.json missing (authoritative runtime catalog is required).")
        return errors
    if not web_path.exists():
        errors.append("web/public/models.json missing (legacy mirror is required for compatibility).")
        return errors

    try:
        data_obj = json.loads(data_path.read_text(errors="ignore"))
    except Exception as e:
        errors.append(f"data/models.json: failed to parse JSON ({e})")
        return errors
    try:
        web_obj = json.loads(web_path.read_text(errors="ignore"))
    except Exception as e:
        errors.append(f"web/public/models.json: failed to parse JSON ({e})")
        return errors

    if data_obj != web_obj:
        errors.append(
            "data/models.json and web/public/models.json are out of sync. "
            "Update both atomically (or use POST /api/models/upsert)."
        )
    return errors

def check_retrieval_config_surface() -> list[str]:
    """Run Retrieval UI/Pydantic surface coverage validation."""
    errors: list[str] = []
    validator_path = Path(__file__).resolve().parent / "validate_retrieval_config_surface.py"

    if not validator_path.exists():
        return [f"{_normalize_relpath(validator_path)}: Retrieval surface validator script is missing."]

    try:
        spec = importlib.util.spec_from_file_location("validate_retrieval_config_surface", validator_path)
        if spec is None or spec.loader is None:
            return [f"{_normalize_relpath(validator_path)}: Could not load validator module spec."]
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        validate_fn = getattr(module, "validate_retrieval_config_surface", None)
        if not callable(validate_fn):
            return [f"{_normalize_relpath(validator_path)}: validate_retrieval_config_surface() not found."]
        result = validate_fn()
        if not isinstance(result, list):
            return [f"{_normalize_relpath(validator_path)}: Validator returned non-list result."]
        for item in result:
            errors.append(f"{_normalize_relpath(validator_path)}: {item}")
    except Exception as e:
        return [f"{_normalize_relpath(validator_path)}: Validator execution failed ({e})."]

    return errors

def main() -> int:
    errors = check_models_catalog_mirror_sync() + check_retrieval_config_surface()
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Contract integrity: {len(errors)} error(s)")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
