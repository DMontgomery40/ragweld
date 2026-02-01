"""API endpoints for model definitions.

This module serves models.json - THE source of truth for all model selection
in the UI. Every dropdown (embedding, generation, reranker) MUST use this endpoint.

NO HARDCODED MODEL LISTS ANYWHERE ELSE.
"""
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/models", tags=["models"])

MODELS_PATH = Path(__file__).parent.parent.parent / "data" / "models.json"


def _load_catalog() -> dict[str, Any]:
    """Load the full models.json catalog.

    models.json is a dict with metadata + a `models` list. The UI expects the
    full object at GET /api/models.
    """
    if not MODELS_PATH.exists():
        raise HTTPException(status_code=500, detail=f"models.json not found at {MODELS_PATH}")
    data: Any = json.loads(MODELS_PATH.read_text())
    if isinstance(data, dict):
        return data
    # Backward-compat: allow a raw list file, wrap it.
    if isinstance(data, list):
        return {"models": data}
    return {"models": []}


def _catalog_models(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    models = catalog.get("models")
    if isinstance(models, list):
        return [m for m in models if isinstance(m, dict)]
    return []


@router.get("")
async def get_all_models() -> dict[str, Any]:
    """
    Return the full models.json catalog (metadata + models list).

    This is THE source of truth for all model selection in the UI.
    Every dropdown (embedding, generation, reranker) MUST use this endpoint.
    """
    return _load_catalog()


@router.get("/by-type/{component_type}")
async def get_models_by_type(component_type: str) -> list[dict[str, Any]]:
    """
    Return models filtered by component type.

    Args:
        component_type: One of EMB, GEN, RERANK (case-insensitive)

    Returns:
        List of models that support the given component type
    """
    catalog = _load_catalog()
    models = _catalog_models(catalog)
    comp = component_type.upper()
    if comp not in ("EMB", "GEN", "RERANK"):
        raise HTTPException(status_code=400, detail=f"Invalid component_type: {component_type}. Must be EMB, GEN, or RERANK")
    return [m for m in models if comp in m.get("components", [])]


@router.get("/providers")
async def get_providers() -> list[str]:
    """Return unique list of providers, sorted alphabetically."""
    catalog = _load_catalog()
    models = _catalog_models(catalog)
    providers = sorted(set(str(m.get("provider", "unknown")) for m in models))
    return providers


@router.get("/providers/{provider}")
async def get_models_for_provider(provider: str) -> list[dict[str, Any]]:
    """Return all models for a specific provider."""
    catalog = _load_catalog()
    models = _catalog_models(catalog)
    return [m for m in models if m.get("provider", "").lower() == provider.lower()]
