"""API endpoints for model definitions.

This module serves models.json - THE source of truth for all model selection
in the UI. Every dropdown (embedding, generation, reranker) MUST use this endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from server.models.tribrid_config_model import (
    CorpusScope,
    ModelCatalogEntry,
    ModelCatalogResponse,
    ModelCatalogUpsertRequest,
    ModelCatalogUpsertResponse,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(prefix="/api/models", tags=["models"])

MODELS_PATH = Path(__file__).parent.parent.parent / "data" / "models.json"
WEB_MODELS_PATH = Path(__file__).parent.parent.parent / "web" / "public" / "models.json"

logger = logging.getLogger(__name__)

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()
_CATALOG_WRITE_LOCK = asyncio.Lock()


def _provider_default_base_url(provider: str) -> str | None:
    p = (provider or "").strip().lower()
    defaults = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com",
        "google": "https://generativelanguage.googleapis.com",
        "cohere": "https://api.cohere.ai/v2",
        "voyage": "https://api.voyageai.com/v1",
        "jina": "https://api.jina.ai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "mistral": "https://api.mistral.ai/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "ollama": "http://127.0.0.1:11434",
        "local": "http://127.0.0.1:11434",
    }
    return defaults.get(p)


def _normalized_components(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for c in raw:
        v = str(c or "").strip().upper()
        if not v:
            continue
        out.append(v)
    return out


def _family_components(family: str, existing_components: list[str]) -> list[str]:
    fam = family.strip().lower()
    if fam == "gen":
        return ["GEN"]
    if fam == "embed":
        return ["EMB"]
    if fam == "rerank":
        return ["RERANK"]
    # misc: preserve previous components when editing; otherwise empty.
    return existing_components


def _validate_upsert_payload(payload: ModelCatalogUpsertRequest) -> None:
    fam = payload.family
    unit = payload.unit

    if fam == "gen":
        if unit != "1k_tokens":
            raise HTTPException(
                status_code=422,
                detail="GEN models must use unit=1k_tokens",
            )
        if payload.input_per_1k is None or payload.output_per_1k is None:
            raise HTTPException(
                status_code=422,
                detail="GEN models require input_per_1k and output_per_1k",
            )
        if payload.embed_per_1k is not None or payload.rerank_per_1k is not None or payload.per_request is not None:
            raise HTTPException(
                status_code=422,
                detail="GEN models only support input_per_1k/output_per_1k pricing",
            )
    elif fam == "embed":
        if unit != "1k_tokens":
            raise HTTPException(
                status_code=422,
                detail="EMB models must use unit=1k_tokens",
            )
        if payload.embed_per_1k is None:
            raise HTTPException(
                status_code=422,
                detail="EMB models require embed_per_1k",
            )
        if (
            payload.input_per_1k is not None
            or payload.output_per_1k is not None
            or payload.rerank_per_1k is not None
            or payload.per_request is not None
        ):
            raise HTTPException(
                status_code=422,
                detail="EMB models only support embed_per_1k pricing",
            )
    elif fam == "rerank":
        if unit == "request" and payload.per_request is None:
            raise HTTPException(
                status_code=422,
                detail="RERANK models with unit=request require per_request",
            )
        if unit == "1k_tokens" and payload.rerank_per_1k is None:
            raise HTTPException(
                status_code=422,
                detail="RERANK models with unit=1k_tokens require rerank_per_1k",
            )
        if payload.input_per_1k is not None or payload.output_per_1k is not None or payload.embed_per_1k is not None:
            raise HTTPException(
                status_code=422,
                detail="RERANK models only support rerank_per_1k or per_request pricing",
            )
        if unit == "request" and payload.rerank_per_1k is not None:
            raise HTTPException(
                status_code=422,
                detail="RERANK models with unit=request cannot set rerank_per_1k",
            )
        if unit == "1k_tokens" and payload.per_request is not None:
            raise HTTPException(
                status_code=422,
                detail="RERANK models with unit=1k_tokens cannot set per_request",
            )


def _provider_existing_base_url(catalog: dict[str, Any], provider: str) -> str | None:
    p = (provider or "").strip().lower()
    if not p:
        return None
    for row in _catalog_models(catalog):
        if str(row.get("provider", "")).strip().lower() != p:
            continue
        base_url = str(row.get("base_url") or "").strip()
        if base_url:
            return base_url
    return None


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


async def _resolve_ragweld_base_model(scope: CorpusScope | None) -> str | None:
    repo_id: str | None = None
    try:
        repo_id = scope.resolved_repo_id if scope is not None else None
    except Exception:
        repo_id = None

    cfg = None
    if repo_id:
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
        except CorpusNotFoundError as e:
            # Don't break clients if a UI passes a stale corpus id.
            logger.warning("models catalog: corpus not found for scope repo_id=%s (%s)", repo_id, e)
            cfg = None
        except Exception as e:
            logger.warning("models catalog: failed to load scoped config for repo_id=%s (%s)", repo_id, e)
            cfg = None

    if cfg is None:
        try:
            cfg = await load_scoped_config(repo_id=None)
        except Exception as e:
            logger.warning("models catalog: failed to load global config (%s)", e)
            return None

    base = str(getattr(getattr(cfg, "training", None), "ragweld_agent_base_model", "") or "").strip()
    if base.startswith("ragweld:"):
        base = base.split(":", 1)[1].strip()
    return base or None


def _augment_catalog_with_ragweld(catalog: dict[str, Any], ragweld_base_model: str | None) -> dict[str, Any]:
    if not ragweld_base_model:
        return catalog

    model_id = f"ragweld:{ragweld_base_model}"
    models = catalog.get("models")
    if not isinstance(models, list):
        models = []
        catalog["models"] = models

    for m in models:
        if isinstance(m, dict) and str(m.get("model") or "") == model_id:
            return catalog

    models.append(
        {
            "provider": "ragweld",
            "family": ragweld_base_model,
            "model": model_id,
            "components": ["GEN"],
            "context": 0,
            "unit": "1k_tokens",
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "base_url": "",
            "notes": "Ragweld in-process MLX model (Qwen3 base + hot-swappable LoRA adapter; context unknown)",
        }
    )
    return catalog


def _load_catalog() -> dict[str, Any]:
    """Load the full models.json catalog."""
    if not MODELS_PATH.exists():
        raise HTTPException(status_code=500, detail=f"models.json not found at {MODELS_PATH}")
    data: Any = json.loads(MODELS_PATH.read_text())
    if isinstance(data, dict):
        if not isinstance(data.get("models"), list):
            data["models"] = []
        return data
    if isinstance(data, list):
        return {"models": data}
    return {"models": []}


def _catalog_models(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    models = catalog.get("models")
    if isinstance(models, list):
        return [m for m in models if isinstance(m, dict)]
    return []


async def _augmented_catalog(scope: CorpusScope | None) -> dict[str, Any]:
    catalog = _load_catalog()
    base = await _resolve_ragweld_base_model(scope)
    return _augment_catalog_with_ragweld(catalog, base)


@router.get("", response_model=ModelCatalogResponse)
async def get_all_models(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> ModelCatalogResponse:
    """
    Return the full models.json catalog (metadata + models list).

    This is THE source of truth for all model selection in the UI.
    Every dropdown (embedding, generation, reranker) MUST use this endpoint.
    """
    catalog = await _augmented_catalog(scope)
    return ModelCatalogResponse.model_validate(catalog)


@router.get("/by-type/{component_type}", response_model=list[ModelCatalogEntry])
async def get_models_by_type(component_type: str, scope: CorpusScope = _CORPUS_SCOPE_DEP) -> list[ModelCatalogEntry]:
    """Return models filtered by component type."""
    comp = component_type.upper()
    if comp not in ("EMB", "GEN", "RERANK"):
        raise HTTPException(status_code=400, detail=f"Invalid component_type: {component_type}. Must be EMB, GEN, or RERANK")
    catalog = await _augmented_catalog(scope)
    models = _catalog_models(catalog)
    return [
        ModelCatalogEntry.model_validate(m)
        for m in models
        if comp in _normalized_components(m.get("components"))
    ]


@router.get("/providers", response_model=list[str])
async def get_providers(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> list[str]:
    """Return unique list of providers, sorted alphabetically."""
    catalog = await _augmented_catalog(scope)
    models = _catalog_models(catalog)
    providers = sorted(set(str(m.get("provider", "unknown")) for m in models))
    return providers


@router.get("/providers/{provider}", response_model=list[ModelCatalogEntry])
async def get_models_for_provider(provider: str, scope: CorpusScope = _CORPUS_SCOPE_DEP) -> list[ModelCatalogEntry]:
    """Return all models for a specific provider."""
    catalog = await _augmented_catalog(scope)
    models = _catalog_models(catalog)
    p = provider.strip().lower()
    return [ModelCatalogEntry.model_validate(m) for m in models if str(m.get("provider", "")).strip().lower() == p]


@router.post("/upsert", response_model=ModelCatalogUpsertResponse)
async def upsert_model(payload: ModelCatalogUpsertRequest) -> ModelCatalogUpsertResponse:
    """Create or update a model catalog row atomically."""
    _validate_upsert_payload(payload)

    provider = payload.provider.strip().lower()
    model = payload.model.strip()
    if not provider or not model:
        raise HTTPException(status_code=422, detail="provider and model are required")

    async with _CATALOG_WRITE_LOCK:
        catalog = _load_catalog()
        models = _catalog_models(catalog)

        existing_idx: int | None = None
        existing_entry: dict[str, Any] | None = None
        for i, row in enumerate(models):
            if str(row.get("provider", "")).strip().lower() == provider and str(row.get("model", "")).strip() == model:
                existing_idx = i
                existing_entry = dict(row)
                break

        existing_components = _normalized_components((existing_entry or {}).get("components"))
        components = _family_components(payload.family, existing_components)
        base_url = (payload.base_url or "").strip() or str((existing_entry or {}).get("base_url") or "").strip()
        if not base_url:
            base_url = _provider_existing_base_url(catalog, provider) or ""
        if not base_url:
            # Prefer a provider-default URL for newly added models.
            base_url = _provider_default_base_url(provider) or ""

        merged: dict[str, Any] = dict(existing_entry or {})
        merged.update(
            {
                "provider": provider,
                "family": payload.family if payload.family != "misc" else str((existing_entry or {}).get("family") or "misc"),
                "model": model,
                "components": components,
                "unit": payload.unit,
                "input_per_1k": payload.input_per_1k,
                "output_per_1k": payload.output_per_1k,
                "embed_per_1k": payload.embed_per_1k,
                "rerank_per_1k": payload.rerank_per_1k,
                "per_request": payload.per_request,
                "context": payload.context if payload.context is not None else (existing_entry or {}).get("context"),
                "dimensions": payload.dimensions if payload.dimensions is not None else (existing_entry or {}).get("dimensions"),
                "notes": payload.notes if payload.notes is not None else (existing_entry or {}).get("notes"),
            }
        )
        if base_url:
            merged["base_url"] = base_url
        else:
            merged.pop("base_url", None)

        # Drop nulls so the serialized catalog remains compact and consistent.
        merged = {k: v for k, v in merged.items() if v is not None}

        validated = ModelCatalogEntry.model_validate(merged)
        action = "updated" if existing_idx is not None else "created"
        if existing_idx is not None:
            models[existing_idx] = validated.model_dump(mode="json")
        else:
            models.append(validated.model_dump(mode="json"))

        catalog["models"] = models
        catalog["last_updated"] = datetime_now_iso()

        _atomic_write_json(MODELS_PATH, catalog)
        # Keep legacy static mirror in sync even though runtime should use /api/models.
        _atomic_write_json(WEB_MODELS_PATH, catalog)

        # Best-effort: clear cached cost catalog after mutation.
        try:
            from server.api.cost import _load_models_catalog

            _load_models_catalog.cache_clear()
        except Exception:
            pass

        return ModelCatalogUpsertResponse(ok=True, action=action, model=validated)


def datetime_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).date().isoformat()
