from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from server.observability.gateway_costs import (
    NativeLedgerReadError,
    NativeSpendReader,
    NativeSpendRow,
    RequestCensus,
    classify_cost,
    native_date_bounds,
    reconcile_costs,
)

EVIDENCE = json.loads((Path(__file__).parents[1] / "fixtures" / "native_spend_rows.json").read_text())
ROWS = [NativeSpendRow.model_validate(row) for row in EVIDENCE["listing"]["data"]]
SESSION = EVIDENCE["session_id"]
CORPUS = "synthetic-ledger"
LANES = frozenset({"index_graph_extraction"})


def census(count: int, **changes: object) -> RequestCensus:
    return replace(RequestCensus("closed", count, count, 0, 0, True, True, True), **changes)


def aggregate(rows: list[NativeSpendRow], request_census: RequestCensus):
    return reconcile_costs(rows, session_id=SESSION, corpus_id=CORPUS, lanes=LANES, census=request_census)


def changed(row: NativeSpendRow, **updates: object) -> NativeSpendRow:
    payload = row.model_dump(mode="json")
    payload.update(updates)
    return NativeSpendRow.model_validate(payload)


MEASURED = [row for row in ROWS if classify_cost(row).kind != "unmeasured"]


@pytest.mark.parametrize(("index", "kind", "amount"), [
    (0, "provider_reported", "0.0123"),
    (1, "provider_reported", "0"),
    (2, "gateway_calculated", "0.00001675"),
    (3, "unmeasured", None),
    (4, "unmeasured", None),
    (5, "gateway_calculated", "0.00001675"),
    (6, "cache", "0"),
])
def test_classifies_observed_native_rows(index: int, kind: str, amount: str | None) -> None:
    result = classify_cost(ROWS[index])
    assert result.kind == kind
    assert result.amount_usd == (Decimal(amount) if amount is not None else None)


def test_complete_call_census_does_not_make_unknown_prices_complete() -> None:
    result = aggregate(ROWS, census(len(EVIDENCE["cases"]), failed_requests=1))
    assert result.coverage_state == "complete"
    assert result.pricing_state == result.state == "incomplete"
    assert result.provider_reported_usd == Decimal("0.0123")
    assert result.gateway_calculated_usd == Decimal("0.0000335")
    assert result.cached_requests == 1
    assert result.unmeasured_requests == 2 and result.missing_requests == 0
    assert "unpriced_usage" in result.reasons


def test_explicit_closed_census_and_all_classified_rows_are_complete() -> None:
    result = aggregate(MEASURED, census(5))
    assert result.state == result.coverage_state == result.pricing_state == "complete"
    assert result.matched_gateway_requests == 5


@pytest.mark.parametrize(("changes", "expected_state", "reason"), [
    ({"state": "open"}, "pending", "request_work_not_closed"),
    ({"workers_quiescent": False}, "pending", "request_work_not_closed"),
    ({"completed_requests": 4}, "pending", "request_work_not_closed"),
    ({"state": "interrupted"}, "incomplete", "interrupted_census"),
    ({"coverage_complete": False}, "incomplete", "incomplete_request_census"),
    ({"uncertain_requests": 1}, "incomplete", "uncertain_request_outcomes"),
    ({"gateway_attempt_policy_verified": False}, "incomplete", "unverified_gateway_attempt_policy"),
])
def test_census_states_fail_closed(changes: dict, expected_state: str, reason: str) -> None:
    result = aggregate(MEASURED, census(5, **changes))
    assert result.state == expected_state
    assert reason in result.reasons


def test_missing_native_rows_remain_incomplete_after_closed_census_and_can_heal() -> None:
    missing = aggregate(MEASURED[:-1], census(5))
    assert missing.state == missing.coverage_state == "incomplete"
    assert missing.missing_requests == 1
    assert aggregate(MEASURED, census(5)).state == "complete"


def test_empty_native_rows_require_explicit_complete_zero_request_census() -> None:
    assert aggregate([], census(0)).state == "complete"
    assert aggregate([], census(0, state="open")).state == "pending"
    assert aggregate([], census(0, coverage_complete=False)).state == "incomplete"
    assert aggregate([], census(1)).missing_requests == 1


def test_exact_attribution_excludes_neighbor_session_corpus_and_lane() -> None:
    row = ROWS[0]
    foreign = [changed(row, session_id=SESSION + "-neighbor", request_id="neighbor")]
    for key, value in (("corpus_id", "other-corpus"), ("lane", "other-lane")):
        metadata = row.metadata.model_dump(mode="json")
        metadata["spend_logs_metadata"][key] = value
        foreign.append(changed(row, request_id=key, metadata=metadata))
    result = aggregate([row, *foreign], census(1))
    assert result.state == "complete" and result.excluded_rows == 3
    assert result.native_rows == result.matched_gateway_requests == 1


def test_missing_attribution_cannot_make_zero_request_census_look_complete() -> None:
    result = aggregate([changed(ROWS[0], metadata=None)], census(0))
    assert result.state == "incomplete"
    assert "missing_native_attribution" in result.reasons


def test_native_request_id_deduplicates_overlap_without_double_counting() -> None:
    result = aggregate([*MEASURED, MEASURED[0], MEASURED[-1]], census(5))
    assert result.state == "complete"
    assert result.provider_reported_usd == Decimal("0.0123")
    assert result.matched_gateway_requests == 5


def test_conflicting_duplicate_request_id_has_no_authoritative_amount() -> None:
    result = aggregate([ROWS[0], changed(ROWS[0], spend="0.02")], census(1))
    assert result.state == "incomplete"
    assert result.native_logged_usd is None
    assert result.provider_reported_usd == 0
    assert "conflicting_native_request_id" in result.reasons


@pytest.mark.parametrize("index", [0, 2, 6])
@pytest.mark.parametrize("copies", [2, 3])
@pytest.mark.parametrize("reverse", [False, True])
def test_distinct_row_ids_cannot_hide_duplicate_native_call_id(index: int, copies: int, reverse: bool) -> None:
    rows = [changed(ROWS[index], request_id=f"duplicate-{number}") for number in range(copies)]
    result = aggregate(list(reversed(rows)) if reverse else rows, census(1))
    assert result.state == "incomplete"
    assert result.matched_gateway_requests == 1
    assert result.native_logged_usd is None
    assert result.provider_reported_usd == result.gateway_calculated_usd == 0
    assert result.unmeasured_requests == copies
    assert "duplicate_native_call_id" in result.reasons


@pytest.mark.parametrize(("field", "value"), [
    ("attempted_retries", 1), ("max_retries", 2),
    ("attempted_retries", None), ("max_retries", None),
])
def test_native_attempt_multiplicity_requires_explicit_supported_evidence(field: str, value: int | None) -> None:
    metadata = ROWS[0].metadata.model_dump(mode="json")
    metadata[field] = value
    result = aggregate([changed(ROWS[0], metadata=metadata)], census(1))
    assert result.state == "incomplete"
    assert result.unmeasured_requests == 1
    assert "unsupported_native_attempt_multiplicity" in result.reasons


def test_cached_provider_cost_must_not_be_counted_again() -> None:
    row = NativeSpendRow.model_validate(EVIDENCE["cross_session_cache"])
    assert row.metadata.usage_object.cost == Decimal("0.0123")
    assert classify_cost(row).kind == "cache"
    assert classify_cost(row).amount_usd == 0


def test_arbitrary_provider_or_caller_metadata_cannot_claim_provider_reported_cost() -> None:
    original = ROWS[0]
    metadata = original.metadata.model_dump(mode="json")
    metadata["spend_logs_metadata"]["cost_source"] = "provider_reported"
    row = changed(original, custom_llm_provider="unverified-provider", metadata=metadata)
    assert classify_cost(row).kind == "unmeasured"


@pytest.mark.parametrize(("path", "value", "reason"), [
    (("usage_object",), None, "missing_native_usage"),
    (("usage_object", "total_tokens"), 19, "incomplete_native_usage"),
    (("usage_object", "prompt_tokens"), None, "incomplete_native_usage"),
    (("usage_object", "prompt_tokens_details"), {"cached_tokens": 3}, "unsupported_usage_details"),
    (("usage_object", "other_billable_units"), 1, "unsupported_usage_details"),
    (("model_map_information",), None, "missing_native_pricing"),
    (("model_map_information", "model_map_value", "input_cost_per_token"), 0, "unpriced_usage"),
    (("model_map_information", "model_map_value", "output_cost_per_token"), None, "unpriced_usage"),
    (("cost_breakdown", "input_cost"), None, "incomplete_native_breakdown"),
    (("cost_breakdown", "input_cost"), "0.000001", "native_pricing_mismatch"),
    (("cost_breakdown", "output_cost"), "0.000001", "native_pricing_mismatch"),
    (("cost_breakdown", "original_cost"), "0.000001", "native_pricing_mismatch"),
    (("cost_breakdown", "total_cost"), "0.000001", "native_pricing_mismatch"),
    (("cost_breakdown", "tool_usage_cost"), "0.000001", "native_pricing_mismatch"),
])
def test_calculated_cost_requires_complete_consistent_supported_native_evidence(
    path: tuple[str, ...], value: object, reason: str,
) -> None:
    metadata = ROWS[2].metadata.model_dump(mode="json")
    target = metadata
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    classification = classify_cost(changed(ROWS[2], metadata=metadata))
    assert classification.kind == "unmeasured" and classification.amount_usd is None
    assert classification.reason == reason


@pytest.mark.parametrize(("margin", "discount", "spend"), [
    ("0.000002", "0", "0.00001875"),
    ("0", "0.000002", "0.00001475"),
    ("0.000003", "0.000001", "0.00001875"),
])
def test_native_margin_and_discount_are_calculated_only_when_arithmetic_agrees(
    margin: str, discount: str, spend: str,
) -> None:
    metadata = ROWS[2].metadata.model_dump(mode="json")
    metadata["cost_breakdown"].update(
        margin_total_amount=margin, discount_amount=discount, total_cost=spend,
    )
    result = classify_cost(changed(ROWS[2], metadata=metadata, spend=spend))
    assert result.kind == "gateway_calculated" and result.amount_usd == Decimal(spend)
    metadata["cost_breakdown"]["discount_amount"] = "0.00001"
    assert classify_cost(changed(ROWS[2], metadata=metadata, spend=spend)).kind == "unmeasured"


def test_unknown_cache_spend_and_unsupported_call_type_cannot_claim_measured_cost() -> None:
    assert classify_cost(changed(ROWS[6], spend="0.001")).reason == "cache_spend_conflict"
    assert classify_cost(changed(ROWS[2], call_type="image_generation")).reason == "unsupported_calculation_call_type"


def test_native_metadata_serialization_preserves_the_same_validated_contract() -> None:
    row = ROWS[0]
    encoded = changed(row, metadata=json.dumps(row.metadata.model_dump(mode="json")))
    assert encoded == row
    assert NativeSpendRow.model_validate_json(row.model_dump_json()) == row


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", True])
def test_native_money_boundary_rejects_nonmonetary_values(value: object) -> None:
    with pytest.raises(ValidationError):
        changed(ROWS[0], spend=value)


def test_dates_round_outward_using_native_utc_format() -> None:
    start = datetime(2026, 9, 5, 2, 3, 4, 123, tzinfo=timezone(timedelta(hours=-6)))
    end = start + timedelta(seconds=10)
    assert native_date_bounds(start, end) == ("2026-09-05 08:03:04", "2026-09-05 08:03:15")
    with pytest.raises(ValueError):
        native_date_bounds(start.replace(tzinfo=None), end)
    with pytest.raises(ValueError):
        native_date_bounds(end, start)


@pytest.mark.parametrize("url", ["", "file:///tmp/gateway", "http://key@localhost", "http://localhost/v1", "http://localhost?key=x"])
def test_reader_requires_explicit_management_root(url: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        NativeSpendReader(base_url=url, api_key=SecretStr("fixture"), request_timeout_s=1, total_timeout_s=2)


@pytest.mark.parametrize("changes", [
    {"started_requests": -1}, {"completed_requests": 6}, {"failed_requests": 6},
    {"uncertain_requests": 6}, {"failed_requests": 3, "uncertain_requests": 3},
    {"started_requests": True}, {"workers_quiescent": 1},
])
def test_request_census_rejects_impossible_counts(changes: dict) -> None:
    with pytest.raises(ValueError):
        census(5, **changes)


@pytest.mark.asyncio
async def test_real_unbound_connection_returns_typed_error_without_credentials() -> None:
    # Own an unlistened port so another service cannot change this failure.
    # The separate paused-gateway test exercises the subsecond deadline.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        reader = NativeSpendReader(base_url=f"http://127.0.0.1:{reservation.getsockname()[1]}", api_key=SecretStr("never-print-fixture-key"), request_timeout_s=2, total_timeout_s=3)
        now = datetime.now(UTC)
        with pytest.raises(NativeLedgerReadError) as error:
            await reader.read_run(session_id=SESSION, corpus_id=CORPUS, lanes=LANES, started_at=now, ended_at=now, census=census(0))
    assert error.value.code == "native_connection_error"
    assert "never-print-fixture-key" not in str(error.value)
