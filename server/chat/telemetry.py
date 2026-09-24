"""Per-request chat telemetry: the one place the chat metric contract is emitted.

The API layer opens a `ChatRunTelemetry` when a chat request arrives, marks the first SSE
event and the first answer text as they go out, and finishes it once with the request's
outcome. The handler, which is the only code that knows the route, the generation phase and
the gateway's usage and cost, reports those onto the same object. `finish()` is idempotent,
so whichever path ends the request (terminal event, typed error, client disconnect) counts
it exactly once.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

import httpx

from server.chat.prompt_budget import PromptBudgetError
from server.chat.provider_router import catalog_alias_or_none, effective_model_override
from server.models.tribrid_config_model import (
    ChatRequest,
    RunOutcome,
    TraceCostSummary,
    TriBridConfig,
)
from server.observability.metrics import (
    CHAT_COST_USD_TOTAL,
    CHAT_DURATION_SECONDS,
    CHAT_REQUESTS_TOTAL,
    CHAT_TIME_TO_FIRST_EVENT_SECONDS,
    CHAT_TIME_TO_FIRST_TEXT_SECONDS,
    CHAT_TOKEN_KINDS,
    CHAT_TOKENS_TOTAL,
)
from server.retrieval.gateway_reranker import reasoning_tokens_spent

# The `model` label of a request whose alias is not in the catalog (an invalid override, or
# a disabled gateway): one bounded value instead of the client's text.
UNRESOLVED_MODEL_LABEL = "unresolved"

ChatPhase = Literal["retrieval", "generation"]

_OUTCOMES: tuple[RunOutcome, ...] = get_args(RunOutcome)
_COST_SOURCES: tuple[str, ...] = get_args(TraceCostSummary.model_fields["cost_source"].annotation)


def prime_chat_series(model: str) -> None:
    """Create the chat series of `model` at 0 (idempotent).

    A labelled series appears in `/metrics` when its child is created. Created and
    incremented between two scrapes, its first sample is already 1, and `rate()` /
    `increase()` never count that request: the first chat, or the first error, of an alias
    after a restart would be invisible on every dashboard and alert. Creating the children
    as soon as the request's alias is known, well before a chat finishes, gives Prometheus
    a 0 sample to count from. The request counter is primed for every outcome (the error
    ratio and its alert read it); the duration histogram, ~18 series per outcome, only for
    `ok`, so an alias costs dozens of series rather than a hundred and more.
    """
    for outcome in _OUTCOMES:
        CHAT_REQUESTS_TOTAL.labels(model=model, outcome=outcome)
    CHAT_DURATION_SECONDS.labels(model=model, outcome="ok")
    CHAT_TIME_TO_FIRST_EVENT_SECONDS.labels(model=model)
    CHAT_TIME_TO_FIRST_TEXT_SECONDS.labels(model=model)
    for cost_source in _COST_SOURCES:
        CHAT_COST_USD_TOTAL.labels(model=model, cost_source=cost_source)
    for kind in CHAT_TOKEN_KINDS:
        CHAT_TOKENS_TOTAL.labels(model=model, kind=kind)


def chat_model_label(*, request: ChatRequest, config: TriBridConfig) -> str:
    """The catalog alias this request routes to, or `unresolved`."""
    alias = catalog_alias_or_none(
        config=config, model_override=effective_model_override(request=request, config=config)
    )
    return alias or UNRESOLVED_MODEL_LABEL


def _is_timeout(exc: BaseException) -> bool:
    """The gateway transport's timeout (`ui.chat_stream_timeout` is its httpx timeout),
    wherever it sits in the chain the transport re-raised it through."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass(slots=True)
class ChatRunTelemetry:
    model: str
    started_at: float = field(default_factory=time.perf_counter)
    phase: ChatPhase = "retrieval"
    first_event_at: float | None = None
    first_text_at: float | None = None
    usage: dict[str, Any] | None = None
    cost: TraceCostSummary | None = None
    generation_error: BaseException | None = None
    outcome: RunOutcome | None = None

    def __post_init__(self) -> None:
        # A request fails as `unresolved` before its alias is known (config load) or when
        # the alias is not in the catalog, so its request counter is primed from the start.
        # Only that counter: `unresolved` requests never reach the gateway, and zero cost,
        # token or latency series for it would put an empty row on every per-model panel.
        for outcome in _OUTCOMES:
            CHAT_REQUESTS_TOTAL.labels(model=UNRESOLVED_MODEL_LABEL, outcome=outcome)

    def bind_model(self, model: str) -> None:
        """Label the request with its alias once the config resolves it, priming its series."""
        self.model = model
        if model != UNRESOLVED_MODEL_LABEL:
            prime_chat_series(model)

    def begin_generation(self) -> None:
        """Retrieval and prompt assembly are done; from here a failure is the generation lane's
        (route resolution included: a disabled gateway or unknown alias is a gateway error)."""
        self.phase = "generation"

    def mark_event(self) -> None:
        if self.first_event_at is None:
            self.first_event_at = time.perf_counter()

    def mark_text(self) -> None:
        if self.first_text_at is None:
            self.first_text_at = time.perf_counter()

    def record_usage(self, usage: dict[str, Any] | None) -> None:
        if usage:
            self.usage = dict(usage)

    def record_cost(self, cost: TraceCostSummary | None) -> None:
        if cost is not None:
            self.cost = cost

    def classify(self, exc: BaseException | None) -> RunOutcome:
        """The outcome of a request that ended with `exc` (None: generation produced nothing)."""
        if isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
            # Chat has no server-side stop, so every early end is the client going away.
            return "client_disconnect"
        if isinstance(exc, PromptBudgetError):
            # The prompt does not fit the alias's window: a generation-lane refusal.
            return "gateway_error"
        if self.phase == "retrieval":
            return "retrieval_error"
        if exc is not None and _is_timeout(exc):
            return "timeout"
        return "gateway_error"

    def finish(self, outcome: RunOutcome) -> None:
        """Emit the request's metrics once; later calls are no-ops."""
        if self.outcome is not None:
            return
        self.outcome = outcome
        now = time.perf_counter()
        model = self.model
        CHAT_REQUESTS_TOTAL.labels(model=model, outcome=outcome).inc()
        CHAT_DURATION_SECONDS.labels(model=model, outcome=outcome).observe(now - self.started_at)
        if self.first_event_at is not None:
            CHAT_TIME_TO_FIRST_EVENT_SECONDS.labels(model=model).observe(self.first_event_at - self.started_at)
        if self.first_text_at is not None:
            CHAT_TIME_TO_FIRST_TEXT_SECONDS.labels(model=model).observe(self.first_text_at - self.started_at)
        cost = self.cost
        if cost is None:
            # No gateway answer (retrieval failure, cache hit, refused prompt): nothing billed.
            return
        CHAT_COST_USD_TOTAL.labels(model=model, cost_source=cost.cost_source).inc(
            float(cost.estimated_cost_usd or 0.0) if cost.cost_source != "unavailable" else 0.0
        )
        for kind, count in (
            ("input", cost.input_tokens),
            ("output", cost.output_tokens),
            ("reasoning", reasoning_tokens_spent(self.usage) if self.usage else None),
        ):
            if count:
                CHAT_TOKENS_TOTAL.labels(model=model, kind=kind).inc(int(count))
