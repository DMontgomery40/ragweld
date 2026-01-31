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


def _load_models() -> list[dict[str, Any]]:
    """Load models from JSON file."""
    if not MODELS_PATH.exists():
        raise HTTPException(status_code=500, detail=f"models.json not found at {MODELS_PATH}")
    data = json.loads(MODELS_PATH.read_text())
    # models.json has nested structure with "models" key
    if isinstance(data, dict) and "models" in data:
        return list(data["models"])
    return list(data)


@router.get("")
async def get_all_models() -> list[dict[str, Any]]:
    """
    Return ALL model definitions from models.json.

    This is THE source of truth for all model selection in the UI.
    Every dropdown (embedding, generation, reranker) MUST use this endpoint.
    """
    return _load_models()


@router.get("/by-type/{component_type}")
async def get_models_by_type(component_type: str) -> list[dict[str, Any]]:
    """
    Return models filtered by component type.

    Args:
        component_type: One of EMB, GEN, RERANK (case-insensitive)

    Returns:
        List of models that support the given component type
    """
    models = _load_models()
    comp = component_type.upper()
    if comp not in ("EMB", "GEN", "RERANK"):
        raise HTTPException(status_code=400, detail=f"Invalid component_type: {component_type}. Must be EMB, GEN, or RERANK")
    return [m for m in models if comp in m.get("components", [])]


@router.get("/providers")
async def get_providers() -> list[str]:
    """Return unique list of providers, sorted alphabetically."""
    models = _load_models()
    providers = sorted(set(m.get("provider", "unknown") for m in models))
    return providers


@router.get("/providers/{provider}")
async def get_models_for_provider(provider: str) -> list[dict[str, Any]]:
    """Return all models for a specific provider."""
    models = _load_models()
    return [m for m in models if m.get("provider", "").lower() == provider.lower()]
