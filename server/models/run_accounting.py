"""Per-run accounting boundaries; native LiteLLM remains the per-request ledger."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

CostLane = Literal[
    "embedding", "semantic_kg", "figure_description", "schema_proposal",
    "index_embeddings", "retrieval_embeddings", "cache_embeddings",
]
CostState = Literal["pending", "complete", "incomplete"]
NonnegativeMoney = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Counter = Annotated[int, Field(ge=0, strict=True)]


class RunCostIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    corpus_id: str = Field(min_length=1)
    lane: CostLane


class RunRequestCensus(BaseModel):
    """Acknowledged aggregate checkpoint, never an inferred request count."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: RunCostIdentity
    revision: Counter
    started_requests: Counter
    completed_requests: Counter
    failed_requests: Counter
    uncertain_requests: Counter
    inflight: Counter
    active_producers: Counter
    owner_finished: bool
    dispatch_enabled: bool
    state: Literal["open", "closed", "interrupted"]

    @model_validator(mode="after")
    def _consistent(self) -> RunRequestCensus:
        if self.completed_requests + self.inflight != self.started_requests:
            raise ValueError("Completed plus in-flight requests must equal started requests")
        if self.failed_requests + self.uncertain_requests > self.completed_requests:
            raise ValueError("Disjoint failed/uncertain outcomes exceed completed requests")
        if self.state == "closed" and (
            not self.owner_finished or self.active_producers or self.inflight or self.dispatch_enabled
        ):
            raise ValueError("A closed census requires a finished owner and quiescent workers")
        return self


class NativeRunCosts(BaseModel):
    """Derived native measurements; completeness and price evidence are separate."""

    model_config = ConfigDict(extra="forbid")

    state: CostState
    coverage_state: CostState
    pricing_state: Literal["complete", "incomplete"]
    provider_reported_usd: NonnegativeMoney
    gateway_calculated_usd: NonnegativeMoney
    native_logged_usd: NonnegativeMoney | None
    provider_reported_requests: Counter
    gateway_calculated_requests: Counter
    cached_requests: Counter
    unmeasured_requests: Counter
    matched_gateway_requests: Counter
    missing_requests: Counter
    native_rows: Counter
    excluded_rows: Counter
    pages_read: Counter
    reasons: list[str]


class IndexCostEstimateSnapshot(BaseModel):
    """An immutable pre-run quote, distinct from native observed charges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    captured_at: AwareDatetime
    embedding_usd: NonnegativeMoney | None = None
    semantic_kg_usd: NonnegativeMoney | None = None
    figure_description_usd: NonnegativeMoney | None = None
    total_usd: NonnegativeMoney | None = None
    estimated_chunks: Counter | None = None
    estimated_tokens: Counter | None = None
    detail: str


class IndexRunAccounting(BaseModel):
    """Accounting extension of the existing index run summary, with no call rows."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    corpus_id: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    gateway_base_url: str | None = Field(default=None, description="Original gateway management root without credentials; retained for historical reconciliation.")
    models: dict[CostLane, str] = Field(default_factory=dict)
    census: dict[CostLane, RunRequestCensus] = Field(default_factory=dict)
    owner_interrupted: bool = Field(default=False, description="The owner process ended before a durable closed census; also covers runs with no paid lanes.")
    coverage_complete: bool = False
    gateway_attempt_policy_verified: bool = False
    coverage_notes: list[str] = Field(default_factory=list)
    estimate: IndexCostEstimateSnapshot | None = None
    processed_files: Counter = 0
    processed_chunks: Counter = 0
    processed_tokens: Counter = 0
    reconciled_at: AwareDatetime | None = None
    costs: NativeRunCosts | None = None
    reconciliation_error: str | None = None

    @model_validator(mode="after")
    def _identities_match(self) -> IndexRunAccounting:
        if self.gateway_base_url is not None:
            gateway = urlsplit(self.gateway_base_url)
            if (
                gateway.scheme not in {"http", "https"} or not gateway.hostname
                or gateway.username is not None or gateway.password is not None
                or gateway.query or gateway.fragment or gateway.path not in {"", "/"}
            ):
                raise ValueError("Saved gateway must be an absolute management root without credentials/query")
        for lane, checkpoint in self.census.items():
            if (
                checkpoint.identity.session_id != self.session_id
                or checkpoint.identity.corpus_id != self.corpus_id
                or checkpoint.identity.lane != lane
            ):
                raise ValueError("Census identity differs from the owning run/lane")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("Accounting end precedes its start")
        return self
