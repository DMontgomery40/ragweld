from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CostEstimateRequest(BaseModel):
    """Request payload for /api/cost/estimate (UI cost projection)."""

    # Generation (chat/completions)
    gen_provider: str = Field(default="", description="Generation provider (e.g., openai, anthropic, local)")
    gen_model: str = Field(default="", description="Generation model name (e.g., gpt-4o-mini)")
    tokens_in: int = Field(default=0, ge=0, description="Input tokens per request")
    tokens_out: int = Field(default=0, ge=0, description="Output tokens per request")

    # Embeddings
    embed_provider: str | None = Field(default=None, description="Embedding provider")
    embed_model: str | None = Field(default=None, description="Embedding model")
    embeds: int = Field(default=0, ge=0, description="Embeddings per request (count of chunks)")

    # Reranking
    rerank_provider: str | None = Field(default=None, description="Reranker provider")
    rerank_model: str | None = Field(default=None, description="Reranker model")
    reranks: int = Field(default=0, ge=0, description="Rerank calls per request")

    # Projection
    requests_per_day: int = Field(default=0, ge=0, description="Requests per day for daily/monthly projection")

    # Optional: local electricity estimate (USD)
    kwh_rate: float | None = Field(default=None, ge=0, description="Electricity cost per kWh (USD)")
    watts: int | None = Field(default=None, ge=0, description="Average power draw (W)")
    hours_per_day: float | None = Field(default=None, ge=0, le=24, description="Hours per day at that draw")


class CostEstimate(BaseModel):
    """Response model for /api/cost/estimate (UI cost projection)."""

    currency: str = Field(default="USD", description="Currency for all cost values")
    models_last_updated: str | None = Field(default=None, description="models.json last_updated (if available)")

    # Costs (USD)
    per_request_usd: float = Field(default=0.0, ge=0, description="Estimated model cost per request (USD)")
    daily: float = Field(default=0.0, ge=0, description="Estimated daily cost (USD)")
    monthly: float = Field(default=0.0, ge=0, description="Estimated monthly cost (USD)")

    # Flexible breakdown for UI/debugging
    breakdown: dict[str, Any] = Field(default_factory=dict, description="Per-component cost details")
    errors: list[str] = Field(default_factory=list, description="Best-effort errors (unknown model/pricing)")


class CostRecord(BaseModel):
    record_id: str
    operation: str
    repo_id: str
    tokens: int
    cost: float
    timestamp: datetime


class CostSummary(BaseModel):
    period: Literal["day", "week", "month"]
    total_cost: float
    by_operation: dict[str, float]
    by_repo: dict[str, float]
