"""Native LiteLLM 1.94 reader; no environment discovery or per-call persistence.

Complete means the native measurements cover the explicit HTTP request census.
It never means that calculated costs have been reconciled against an invoice.
"""
from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
)

Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0, strict=True)]
ZERO = Decimal(0)
_PAGE_SIZE = 100
_PAGE_BYTES = 16 * 1024 * 1024


class NativeUsage(BaseModel):
    model_config = ConfigDict(extra="allow")
    prompt_tokens: Count | None = None
    completion_tokens: Count | None = None
    total_tokens: Count | None = None
    cost: Money | None = None
    prompt_tokens_details: dict[str, Count | None] | None = None
    completion_tokens_details: dict[str, Count | None] | None = None


class NativePrices(BaseModel):
    input_cost_per_token: Money | None = None
    output_cost_per_token: Money | None = None


class NativeModelInformation(BaseModel):
    model_map_key: str
    model_map_value: NativePrices | None = None


class NativeCostBreakdown(BaseModel):
    input_cost: Money | None = None
    output_cost: Money | None = None
    total_cost: Money | None = None
    original_cost: Money | None = None
    tool_usage_cost: Money | None = None
    margin_total_amount: Money | None = None
    discount_amount: Money | None = None


class NativeAttribution(BaseModel):
    run_id: str | None = None
    corpus_id: str | None = None
    lane: str | None = None


class NativeMetadata(BaseModel):
    spend_logs_metadata: NativeAttribution | None = None
    litellm_call_id: str | None = None
    attempted_retries: Count | None = None
    max_retries: Count | None = None
    usage_object: NativeUsage | None = None
    cost_breakdown: NativeCostBreakdown | None = None
    model_map_information: NativeModelInformation | None = None


def _json_object(value: object) -> object:
    # Native v2 currently hydrates metadata, while the SQL row can contain JSON
    # text. These are the two observed representations of the same native field.
    return json.loads(value) if isinstance(value, str) else value


class NativeSpendRow(BaseModel):
    request_id: Annotated[str, Field(min_length=1)]
    call_type: str
    session_id: str | None = None
    model: str
    custom_llm_provider: str | None = None
    startTime: AwareDatetime  # noqa: N815 - native LiteLLM wire field
    endTime: AwareDatetime  # noqa: N815 - native LiteLLM wire field
    spend: Money
    status: Literal["success", "failure"] | None = None
    cache_hit: Literal["True", "False", "None"] | bool | None = None
    metadata: Annotated[NativeMetadata | None, BeforeValidator(_json_object)] = None


class NativeSpendPage(BaseModel):
    data: list[NativeSpendRow]
    total: Count
    page: Annotated[int, Field(ge=1, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]
    total_pages: Count
    total_is_capped: bool


@dataclass(frozen=True)
class RequestCensus:
    """An explicit checkpoint from the existing run record, never inferred.

    completed_requests includes HTTP failures and uncertain client outcomes.
    The policy flag requires verified gateway retry=0 and no fallback routes.
    A restart with an open checkpoint must be supplied as interrupted/unknown.
    """

    state: Literal["open", "closed", "interrupted"]
    started_requests: int
    completed_requests: int
    failed_requests: int
    uncertain_requests: int
    workers_quiescent: bool
    coverage_complete: bool
    gateway_attempt_policy_verified: bool

    def __post_init__(self) -> None:
        counts = (self.started_requests, self.completed_requests, self.failed_requests, self.uncertain_requests)
        if self.state not in {"open", "closed", "interrupted"}:
            raise ValueError("Unsupported census state")
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("Request census counters must be nonnegative integers")
        if any(type(value) is not bool for value in (self.workers_quiescent, self.coverage_complete, self.gateway_attempt_policy_verified)):
            raise ValueError("Request census proof flags must be booleans")
        if self.completed_requests > self.started_requests:
            raise ValueError("Finished requests exceed started requests")
        if self.failed_requests + self.uncertain_requests > self.completed_requests:
            raise ValueError("Outcome counters exceed finished requests")


@dataclass(frozen=True)
class CostClassification:
    kind: Literal["provider_reported", "gateway_calculated", "cache", "unmeasured"]
    amount_usd: Decimal | None
    reason: str | None = None


@dataclass(frozen=True)
class RunCostAggregate:
    state: Literal["pending", "complete", "incomplete"]
    coverage_state: Literal["pending", "complete", "incomplete"]
    pricing_state: Literal["complete", "incomplete"]
    provider_reported_usd: Decimal
    gateway_calculated_usd: Decimal
    native_logged_usd: Decimal | None
    provider_reported_requests: int
    gateway_calculated_requests: int
    cached_requests: int
    unmeasured_requests: int
    matched_gateway_requests: int
    missing_requests: int
    native_rows: int
    excluded_rows: int
    pages_read: int
    reasons: tuple[str, ...]


class NativeLedgerReadError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _close_money(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= max(Decimal("1e-12"), abs(right) * Decimal("1e-9"))


def classify_cost(row: NativeSpendRow) -> CostClassification:
    metadata = row.metadata
    if row.status != "success":
        return CostClassification("unmeasured", None, "unsuccessful_or_unknown_status")
    # A cache hit can retain positive provider usage.cost and cost_breakdown.
    if row.cache_hit is True or row.cache_hit == "True":
        if row.spend == 0:
            return CostClassification("cache", ZERO)
        return CostClassification("unmeasured", None, "cache_spend_conflict")
    usage = metadata.usage_object if metadata else None
    if usage is None:
        return CostClassification("unmeasured", None, "missing_native_usage")
    assert metadata is not None
    # This is the provider and explicit native usage field verified in 1.94.
    # A generic caller tag or arbitrary provider 'cost' key is not equivalent.
    if row.custom_llm_provider == "openrouter" and usage.cost is not None:
        return CostClassification("provider_reported", usage.cost)
    if row.call_type not in {"completion", "acompletion", "embedding", "aembedding"}:
        return CostClassification("unmeasured", None, "unsupported_calculation_call_type")
    if usage.model_extra or any(
        value not in (None, 0)
        for details in (usage.prompt_tokens_details, usage.completion_tokens_details)
        for value in (details or {}).values()
    ):
        return CostClassification("unmeasured", None, "unsupported_usage_details")
    prompt = usage.prompt_tokens
    completion = usage.completion_tokens
    if completion is None and row.call_type in {"embedding", "aembedding"}:
        completion = 0
    if prompt is None or completion is None or usage.total_tokens != prompt + completion:
        return CostClassification("unmeasured", None, "incomplete_native_usage")
    info = metadata.model_map_information
    prices = info.model_map_value if info else None
    breakdown = metadata.cost_breakdown
    if prices is None or breakdown is None:
        return CostClassification("unmeasured", None, "missing_native_pricing")
    input_rate = prices.input_cost_per_token
    output_rate = prices.output_cost_per_token
    # Unknown models receive zero-valued native map entries and breakdowns.
    # Zero prices with consumed units cannot prove known-free usage.
    if (prompt and (input_rate is None or input_rate <= 0)) or (completion and (output_rate is None or output_rate <= 0)):
        return CostClassification("unmeasured", None, "unpriced_usage")
    expected_input = Decimal(prompt) * (input_rate or ZERO)
    expected_output = Decimal(completion) * (output_rate or ZERO)
    if expected_input + expected_output == 0:
        return CostClassification("unmeasured", None, "unproven_zero_calculation")
    if any(value is None for value in (breakdown.input_cost, breakdown.output_cost, breakdown.total_cost, breakdown.original_cost)):
        return CostClassification("unmeasured", None, "incomplete_native_breakdown")
    assert breakdown.input_cost is not None and breakdown.output_cost is not None
    assert breakdown.total_cost is not None and breakdown.original_cost is not None
    if not (
        _close_money(breakdown.input_cost, expected_input)
        and _close_money(breakdown.output_cost, expected_output)
        and _close_money(breakdown.original_cost, expected_input + expected_output)
        and _close_money(breakdown.total_cost, row.spend)
        and _close_money(
            breakdown.original_cost + (breakdown.margin_total_amount or ZERO) - (breakdown.discount_amount or ZERO),
            breakdown.total_cost,
        )
        and (breakdown.tool_usage_cost or ZERO) == 0
    ):
        return CostClassification("unmeasured", None, "native_pricing_mismatch")
    return CostClassification("gateway_calculated", row.spend)


def reconcile_costs(
    rows: list[NativeSpendRow], *, session_id: str, corpus_id: str,
    lanes: frozenset[str], census: RequestCensus, pages_read: int = 0,
) -> RunCostAggregate:
    """Pure reconciliation. Missing closed-run rows are incomplete and may heal.

    Open work is pending. No elapsed-time heuristic promotes an incomplete run.
    The caller can poll again when native queued writes are expected to arrive.
    """
    if not session_id or not corpus_id or not lanes or not all(lanes):
        raise ValueError("Run, corpus and lane selection must be explicit")
    reasons: set[str] = set()
    selected: dict[str, NativeSpendRow] = {}
    conflicted: set[str] = set()
    excluded = 0
    for row in rows:
        attribution = row.metadata.spend_logs_metadata if row.metadata else None
        if row.session_id == session_id and (
            attribution is None or not attribution.run_id or not attribution.corpus_id or not attribution.lane
        ):
            reasons.add("missing_native_attribution")
        if not (
            row.session_id == session_id and attribution is not None
            and attribution.run_id == session_id and attribution.corpus_id == corpus_id
            and attribution.lane in lanes
        ):
            excluded += 1
            continue
        previous = selected.get(row.request_id)
        if previous is not None and previous != row:
            conflicted.add(row.request_id)
            reasons.add("conflicting_native_request_id")
        selected.setdefault(row.request_id, row)
    call_groups: dict[str, list[str]] = defaultdict(list)
    for request_id, row in selected.items():
        call_id = row.metadata.litellm_call_id if row.metadata else None
        # Namespaced fallback avoids colliding a response ID with a call ID.
        identity = f"call:{call_id}" if call_id else f"request:{request_id}"
        call_groups[identity].append(request_id)
    for group in call_groups.values():
        if len(group) > 1:
            conflicted.update(group)
            reasons.add("duplicate_native_call_id")
    provider_total = calculated_total = logged_total = ZERO
    provider_count = calculated_count = cached_count = unknown_count = 0
    for request_id, row in selected.items():
        logged_total += row.spend
        metadata = row.metadata
        if metadata is None or metadata.attempted_retries != 0 or metadata.max_retries != 0:
            reasons.add("unsupported_native_attempt_multiplicity")
            conflicted.add(request_id)
        classification = (
            CostClassification("unmeasured", None, "ambiguous_native_identity_or_attempts")
            if request_id in conflicted else classify_cost(row)
        )
        if classification.kind == "provider_reported":
            provider_total += classification.amount_usd or ZERO
            provider_count += 1
        elif classification.kind == "gateway_calculated":
            calculated_total += classification.amount_usd or ZERO
            calculated_count += 1
        elif classification.kind == "cache":
            cached_count += 1
        else:
            unknown_count += 1
            reasons.add(classification.reason or "unmeasured_cost")
    matched = len(call_groups)
    missing = max(0, census.started_requests - matched)
    if matched > census.started_requests:
        reasons.add("native_requests_exceed_census")
    if missing:
        reasons.add("missing_native_requests")
    if census.state == "interrupted":
        reasons.add("interrupted_census")
    if not census.coverage_complete:
        reasons.add("incomplete_request_census")
    if not census.gateway_attempt_policy_verified:
        reasons.add("unverified_gateway_attempt_policy")
    if census.uncertain_requests:
        reasons.add("uncertain_request_outcomes")
    open_work = census.state == "open" or not census.workers_quiescent or census.completed_requests != census.started_requests
    if open_work:
        reasons.add("request_work_not_closed")
    coverage_failures = {
        "conflicting_native_request_id", "duplicate_native_call_id", "missing_native_attribution",
        "unsupported_native_attempt_multiplicity", "native_requests_exceed_census", "interrupted_census",
        "incomplete_request_census", "unverified_gateway_attempt_policy", "uncertain_request_outcomes",
    }
    coverage_state: Literal["pending", "complete", "incomplete"] = (
        "incomplete" if reasons & coverage_failures else "pending" if open_work else "incomplete" if missing else "complete"
    )
    pricing_state: Literal["complete", "incomplete"] = "incomplete" if unknown_count or missing else "complete"
    state: Literal["pending", "complete", "incomplete"] = (
        "pending" if coverage_state == "pending" else "incomplete"
        if coverage_state == "incomplete" or pricing_state == "incomplete" else "complete"
    )
    return RunCostAggregate(
        state, coverage_state, pricing_state, provider_total, calculated_total,
        None if reasons & {"conflicting_native_request_id", "duplicate_native_call_id"} else logged_total, provider_count,
        calculated_count, cached_count, unknown_count, matched, missing,
        len(selected), excluded, pages_read, tuple(sorted(reasons)),
    )


def native_date_bounds(started_at: datetime, ended_at: datetime) -> tuple[str, str]:
    if started_at.tzinfo is None or ended_at.tzinfo is None or started_at > ended_at:
        raise ValueError("A valid timezone-aware run interval is required")
    start = started_at.astimezone(UTC).replace(microsecond=0)
    end = ended_at.astimezone(UTC)
    if end.microsecond:
        end = end.replace(microsecond=0) + timedelta(seconds=1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


class NativeSpendReader:
    def __init__(self, *, base_url: str, api_key: SecretStr, request_timeout_s: float, total_timeout_s: float):
        url = httpx.URL(base_url)
        if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError("An explicit trusted gateway URL without credentials/query is required")
        if url.path not in {"", "/"}:
            raise ValueError("Provide the gateway management root, without /v1")
        if not api_key.get_secret_value() or any(not math.isfinite(value) or value <= 0 for value in (request_timeout_s, total_timeout_s)):
            raise ValueError("An explicit key and positive timeouts are required")
        self._base_url = str(url).rstrip("/")
        self._api_key = api_key
        self._request_timeout_s = request_timeout_s
        self._total_timeout_s = total_timeout_s

    async def read_run(
        self, *, session_id: str, corpus_id: str, lanes: frozenset[str],
        started_at: datetime, ended_at: datetime, census: RequestCensus,
    ) -> RunCostAggregate:
        if not session_id or not corpus_id or not lanes or not all(lanes):
            raise ValueError("Run, corpus and lane selection must be explicit")
        start_date, end_date = native_date_bounds(started_at, ended_at)
        rows: list[NativeSpendRow] = []
        page_number = 1
        try:
            async with asyncio.timeout(self._total_timeout_s):
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    timeout=self._request_timeout_s, follow_redirects=False, trust_env=False,
                ) as client:
                    while True:
                        parameters: dict[str, str | int] = {
                            "start_date": start_date, "end_date": end_date, "session_id": session_id,
                            "page": page_number, "page_size": _PAGE_SIZE, "sort_by": "startTime", "sort_order": "asc",
                        }
                        async with client.stream("GET", "/spend/logs/v2", params=parameters) as response:
                            if response.status_code != 200:
                                raise NativeLedgerReadError("native_http_error", status_code=response.status_code)
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(body) + len(chunk) > _PAGE_BYTES:
                                    raise NativeLedgerReadError("native_page_too_large")
                                body.extend(chunk)
                        page = NativeSpendPage.model_validate_json(body)
                        if page.page != page_number or page.page_size != _PAGE_SIZE or len(page.data) > _PAGE_SIZE:
                            raise NativeLedgerReadError("invalid_native_pagination")
                        rows.extend(page.data)
                        # total_pages may be based on the native capped10k count.
                        # Page data exhaustion is the only native continuation rule.
                        if len(page.data) < _PAGE_SIZE:
                            break
                        page_number += 1
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise NativeLedgerReadError("native_read_timeout") from exc
        except httpx.HTTPError as exc:
            raise NativeLedgerReadError("native_connection_error") from exc
        except ValidationError:
            raise NativeLedgerReadError("invalid_native_payload") from None
        return reconcile_costs(rows, session_id=session_id, corpus_id=corpus_id, lanes=lanes, census=census, pages_read=page_number)
