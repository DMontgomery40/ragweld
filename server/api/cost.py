from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter

from server.models.cost import CostEstimate, CostEstimateRequest, CostRecord, CostSummary

router = APIRouter(tags=["cost"])

MODELS_PATH = Path(__file__).parent.parent.parent / "data" / "models.json"


def _norm_key(s: str | None) -> str:
    return str(s or "").strip().lower()


@lru_cache(maxsize=1)
def _load_models_catalog() -> dict[str, Any]:
    try:
        raw: Any = json.loads(MODELS_PATH.read_text())
    except Exception:
        return {"models": []}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"models": raw}
    return {"models": []}


def _catalog_models(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    models = catalog.get("models")
    if isinstance(models, list):
        return [m for m in models if isinstance(m, dict)]
    return []


def _find_model_spec(
    models: list[dict[str, Any]], *, provider: str | None, model: str | None
) -> dict[str, Any] | None:
    """Best-effort model lookup (mirrors legacy JS fallback behavior)."""
    prov = _norm_key(provider)
    mdl = _norm_key(model)

    if prov and mdl:
        for m in models:
            if _norm_key(m.get("provider")) == prov and _norm_key(m.get("model")) == mdl:
                return m

    if mdl:
        for m in models:
            if _norm_key(m.get("model")) == mdl:
                return m

    if prov:
        for m in models:
            if _norm_key(m.get("provider")) == prov:
                return m

    return None


def _to_float(x: Any) -> float | None:
    try:
        v = float(x)
    except Exception:
        return None
    if v != v:  # NaN
        return None
    return v


def _estimate_cost(req: CostEstimateRequest) -> CostEstimate:
    catalog = _load_models_catalog()
    models = _catalog_models(catalog)

    errors: list[str] = []

    # ------------------------------------------------------------------
    # Generation (chat/completions) — per request
    # ------------------------------------------------------------------
    gen_cost = 0.0
    gen_detail: dict[str, Any] = {
        "provider": req.gen_provider,
        "model": req.gen_model,
        "tokens_in": int(req.tokens_in),
        "tokens_out": int(req.tokens_out),
    }
    if req.gen_provider and req.gen_model and (req.tokens_in or req.tokens_out):
        spec = _find_model_spec(models, provider=req.gen_provider, model=req.gen_model)
        if not spec:
            errors.append(f"Unknown GEN model: {req.gen_provider}/{req.gen_model}")
        else:
            in_rate = _to_float(spec.get("input_per_1k"))
            out_rate = _to_float(spec.get("output_per_1k"))
            gen_detail["unit"] = spec.get("unit")
            gen_detail["input_per_1k"] = in_rate
            gen_detail["output_per_1k"] = out_rate
            if in_rate is None and out_rate is None and (req.tokens_in or req.tokens_out):
                errors.append(f"Missing GEN pricing: {req.gen_provider}/{req.gen_model}")
            else:
                in_rate = float(in_rate or 0.0)
                out_rate = float(out_rate or 0.0)
                gen_cost = (float(req.tokens_in) / 1000.0) * in_rate + (float(req.tokens_out) / 1000.0) * out_rate
    gen_detail["cost_usd"] = float(round(gen_cost, 6))

    # ------------------------------------------------------------------
    # Embeddings — per request
    #   NOTE: embeds is a count; we assume 1000 tokens per embed (matches UI store).
    # ------------------------------------------------------------------
    embed_cost = 0.0
    assumed_embed_tokens = 1000
    embed_tokens = int(req.embeds) * assumed_embed_tokens
    embed_detail: dict[str, Any] = {
        "provider": req.embed_provider,
        "model": req.embed_model,
        "embeds": int(req.embeds),
        "assumed_tokens_per_embed": assumed_embed_tokens,
        "embed_tokens": embed_tokens,
    }
    if req.embeds and embed_tokens > 0:
        if not (req.embed_provider and req.embed_model):
            errors.append("Embeddings requested but embed_provider/embed_model missing")
        else:
            spec = _find_model_spec(models, provider=req.embed_provider, model=req.embed_model)
            if not spec:
                errors.append(f"Unknown EMB model: {req.embed_provider}/{req.embed_model}")
            else:
                rate = _to_float(spec.get("embed_per_1k"))
                embed_detail["unit"] = spec.get("unit")
                embed_detail["embed_per_1k"] = rate
                if rate is None and embed_tokens > 0:
                    errors.append(f"Missing EMB pricing: {req.embed_provider}/{req.embed_model}")
                else:
                    rate = float(rate or 0.0)
                    embed_cost = (float(embed_tokens) / 1000.0) * rate
    embed_detail["cost_usd"] = float(round(embed_cost, 6))

    # ------------------------------------------------------------------
    # Reranking — per request
    #   NOTE: if priced per 1k tokens, assume 500 tokens per rerank call.
    # ------------------------------------------------------------------
    rerank_cost = 0.0
    assumed_rerank_tokens = 500
    rerank_tokens = int(req.reranks) * assumed_rerank_tokens
    rerank_detail: dict[str, Any] = {
        "provider": req.rerank_provider,
        "model": req.rerank_model,
        "reranks": int(req.reranks),
        "assumed_tokens_per_rerank": assumed_rerank_tokens,
        "rerank_tokens": rerank_tokens,
    }
    if req.reranks and int(req.reranks) > 0:
        if not (req.rerank_provider and req.rerank_model):
            errors.append("Reranks requested but rerank_provider/rerank_model missing")
        else:
            spec = _find_model_spec(models, provider=req.rerank_provider, model=req.rerank_model)
            if not spec:
                errors.append(f"Unknown RERANK model: {req.rerank_provider}/{req.rerank_model}")
            else:
                per_request = _to_float(spec.get("per_request"))
                per_1k = _to_float(spec.get("rerank_per_1k"))
                rerank_detail["unit"] = spec.get("unit")
                rerank_detail["per_request"] = per_request
                rerank_detail["rerank_per_1k"] = per_1k
                if per_request is not None:
                    rerank_cost = float(req.reranks) * float(per_request)
                elif per_1k is not None:
                    rerank_cost = (float(rerank_tokens) / 1000.0) * float(per_1k)
                else:
                    errors.append(f"Missing RERANK pricing: {req.rerank_provider}/{req.rerank_model}")
    rerank_detail["cost_usd"] = float(round(rerank_cost, 6))

    per_request_usd = float(round(gen_cost + embed_cost + rerank_cost, 6))

    # ------------------------------------------------------------------
    # Optional electricity — daily (not per request)
    # ------------------------------------------------------------------
    electricity_daily = 0.0
    electricity_detail: dict[str, Any] = {
        "kwh_rate": req.kwh_rate,
        "watts": req.watts,
        "hours_per_day": req.hours_per_day,
    }

    any_power = req.kwh_rate is not None or req.watts is not None or req.hours_per_day is not None
    if any_power:
        if req.kwh_rate is None or req.watts is None or req.hours_per_day is None:
            errors.append("Electricity estimate requires kwh_rate, watts, and hours_per_day")
        else:
            electricity_daily = (float(req.watts) / 1000.0) * float(req.hours_per_day) * float(req.kwh_rate)

    electricity_detail["daily_usd"] = float(round(electricity_daily, 6))

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------
    rpd = int(req.requests_per_day)
    daily = float(round(per_request_usd * float(rpd) + electricity_daily, 6))
    monthly = float(round(daily * 30.0, 6))

    breakdown: dict[str, Any] = {
        "generation": gen_detail,
        "embedding": embed_detail,
        "rerank": rerank_detail,
        "electricity": electricity_detail,
    }

    currency = str(catalog.get("currency") or "USD")
    last_updated = catalog.get("last_updated")

    return CostEstimate(
        currency=currency,
        models_last_updated=str(last_updated) if last_updated else None,
        per_request_usd=per_request_usd,
        daily=daily,
        monthly=monthly,
        breakdown=breakdown,
        errors=errors,
    )


@router.post("/cost/estimate", response_model=CostEstimate)
async def estimate_cost(req: CostEstimateRequest) -> CostEstimate:
    return _estimate_cost(req)


@router.post("/cost/estimate_pipeline", response_model=CostEstimate)
async def estimate_cost_pipeline(req: CostEstimateRequest) -> CostEstimate:
    # Legacy UI tries this endpoint first.
    return _estimate_cost(req)


@router.get("/cost/history", response_model=list[CostRecord])
async def get_cost_history(period: str = "week") -> list[CostRecord]:
    # Not persisted yet; keep endpoint stable for UI.
    _ = period
    return []


@router.get("/cost/summary", response_model=CostSummary)
async def get_cost_summary(period: Literal["day", "week", "month"] = "month") -> CostSummary:
    # Not persisted yet; keep endpoint stable for UI.
    return CostSummary(period=period, total_cost=0.0, by_operation={}, by_repo={})
