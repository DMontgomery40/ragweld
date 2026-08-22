from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from server.gateway_catalog import gateway_rows_snapshot
from server.models.tribrid_config_model import TraceCostSummary

_MODELS_PATH = Path(__file__).resolve().parents[2] / "data" / "models.json"


def _norm_key(value: str | None) -> str:
    return str(value or "").strip().lower()


@lru_cache(maxsize=1)
def _load_models_catalog() -> list[dict[str, Any]]:
    try:
        raw = json.loads(_MODELS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw, dict):
        models = raw.get("models")
        if isinstance(models, list):
            return [item for item in models if isinstance(item, dict)]
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def warm_costing_catalog() -> int:
    """Load the pricing catalog into the process cache (blocking; call off the loop)."""

    return len(_load_models_catalog())


def reset_costing_catalog() -> None:
    _load_models_catalog.cache_clear()


def _find_model_spec(*, provider: str | None, model: str | None) -> dict[str, Any] | None:
    models = _load_models_catalog()
    provider_key = _norm_key(provider)
    model_key = _norm_key(model)
    if provider_key and model_key:
        for item in models:
            if _norm_key(item.get("provider")) == provider_key and _norm_key(item.get("model")) == model_key:
                return item
    if model_key:
        for item in models:
            if _norm_key(item.get("model")) == model_key:
                return item
    return None


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed != parsed:
        return None
    return parsed


def _to_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return max(0, parsed)


def _extract_usage_tokens(usage: dict[str, Any] | None) -> tuple[int | None, int | None, int | None]:
    usage = usage or {}
    input_tokens = _to_int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("promptTokens")
        or usage.get("inputTokens")
    )
    output_tokens = _to_int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("completionTokens")
        or usage.get("outputTokens")
    )
    total_tokens = _to_int(
        usage.get("total_tokens")
        or usage.get("totalTokens")
        or (
            (int(input_tokens or 0) + int(output_tokens or 0))
            if input_tokens is not None or output_tokens is not None
            else None
        )
    )
    return input_tokens, output_tokens, total_tokens


def _parse_provider_cost(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("response_cost", "cost", "usd", "value"):
            parsed = _parse_provider_cost(raw.get(key))
            if parsed is not None:
                return parsed
        return None
    if isinstance(raw, (list, tuple)):
        for item in raw:
            parsed = _parse_provider_cost(item)
            if parsed is not None:
                return parsed
        return None
    return _to_float(raw)


def extract_provider_cost(data: dict[str, Any] | None) -> float | None:
    payload = data or {}
    for key in (
        "response_cost",
        "cost",
        "responseCost",
        "responseCostUsd",
        "x_response_cost",
    ):
        parsed = _parse_provider_cost(payload.get(key))
        if parsed is not None:
            return parsed

    hidden = payload.get("hidden_params")
    parsed = _parse_provider_cost(hidden)
    if parsed is not None:
        return parsed

    usage = payload.get("usage")
    parsed = _parse_provider_cost(usage)
    if parsed is not None:
        return parsed

    metadata = payload.get("metadata")
    parsed = _parse_provider_cost(metadata)
    if parsed is not None:
        return parsed

    return None


def _find_gateway_spec(alias: str | None) -> dict[str, Any] | None:
    """Resolve a LiteLLM gateway alias to the catalog row that carries its pricing."""

    alias_key = _norm_key(alias)
    if not alias_key:
        return None
    row = gateway_rows_snapshot().get(alias_key)
    if row is None:
        return None
    return {"input_per_1k": row.input_per_1k, "output_per_1k": row.output_per_1k}


def build_trace_cost_summary(
    *,
    provider: str | None,
    model: str | None,
    usage: dict[str, Any] | None,
    provider_cost_usd: float | None,
) -> TraceCostSummary:
    input_tokens, output_tokens, total_tokens = _extract_usage_tokens(usage)

    if provider_cost_usd is not None:
        return TraceCostSummary(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=float(round(provider_cost_usd, 6)),
            cost_source="provider",
            authoritative=True,
            detail="Cost came from provider or gateway response metadata.",
        )

    spec = _find_gateway_spec(model) or _find_model_spec(provider=provider, model=model)
    if spec is None or (input_tokens is None and output_tokens is None):
        return TraceCostSummary(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_source="unavailable",
            authoritative=False,
            detail="Provider did not return request cost and catalog fallback could not resolve pricing.",
        )

    input_rate = _to_float(spec.get("input_per_1k"))
    output_rate = _to_float(spec.get("output_per_1k"))
    if input_rate is None and output_rate is None:
        return TraceCostSummary(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_source="unavailable",
            authoritative=False,
            detail="Catalog pricing is missing for the selected provider/model.",
        )

    estimate = ((float(input_tokens or 0) / 1000.0) * float(input_rate or 0.0)) + (
        (float(output_tokens or 0) / 1000.0) * float(output_rate or 0.0)
    )
    return TraceCostSummary(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=float(round(estimate, 6)),
        cost_source="catalog",
        authoritative=False,
        detail="Cost estimated from token usage and base-tier catalog pricing (provider volume tiers may apply).",
    )
