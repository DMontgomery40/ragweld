"""The generation-failure classifier: one sanitised reason, one hint chosen from it, on every surface.

The strings below are the gateway's real answers on LXC100 (2026-09-02): an OpenRouter
key over its weekly limit, the local lane with no vLLM behind it, and the two ways a
rejected key reaches the transport. Each must land on a different operator hint; the
old card sent every one of them to "verify the gateway, client key and alias".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from server.api.generation_errors import generation_unavailable_http_exception
from server.chat.generation_failure import (
    GENERATION_FAILURE_HINTS,
    classify_generation_failure,
    generation_unavailable_detail,
    safe_error_message,
)
from server.models.tribrid_config_model import GenerationUnavailableDetail

KEY_HASH = "c25f3bf6ac884107724d484e99f73a83eaca6e8db76b9f3b13525ccd4f3f13f7"
SPEND_LIMIT_REASON = (
    "LiteLLM request failed (HTTP 403): litellm.APIError: APIError: OpenrouterException - "
    '{"error":{"message":"Key limit exceeded (weekly limit). Manage it using '
    f'https://openrouter.ai/workspaces/default/keys/{KEY_HASH}","code":403}}}}'
    "No fallback model group found for original model_group=openai.gpt-5.6-luna. Fallbacks=[]"
)
LANE_DOWN_REASON = (
    "LiteLLM request failed (HTTP 500): litellm.InternalServerError: InternalServerError: "
    "OpenAIException - Connection error.No fallback model group found for original "
    "model_group=ragweld-local. Fallbacks=[]. Received Model Group=ragweld-local\n"
    "Available Model Group Fallbacks=None"
)
GATEWAY_KEY_REJECTED_REASON = "LiteLLM unauthorized (check LITELLM_API_KEY)"
PROVIDER_KEY_REJECTED_REASON = (
    "LiteLLM request failed (HTTP 401): litellm.AuthenticationError: AuthenticationError: "
    'OpenrouterException - {"error":{"message":"No auth credentials found","code":401}}'
)
INSUFFICIENT_CREDITS_REASON = (
    "LiteLLM request failed (HTTP 402): litellm.APIError: APIError: OpenrouterException - "
    '{"error":{"message":"Insufficient credits. Add more using https://openrouter.ai/settings/credits","code":402}}'
)
GATEWAY_DOWN_REASONS = (
    "LiteLLM stream failed at http://127.0.0.1:4000/v1: ConnectError: All connection attempts failed",
    "LiteLLM request failed at http://127.0.0.1:4000/v1: ConnectError: [Errno 111] Connection refused",
)
GENERIC_REASONS = (
    "LiteLLM response parse failed: Expecting value: line 1 column 1 (char 0)",
    "LLM returned an empty response",
    "LiteLLM stream produced no content",
    "Gateway response missing choices[]",
)


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        (SPEND_LIMIT_REASON, "spend_limit"),
        (INSUFFICIENT_CREDITS_REASON, "spend_limit"),
        (LANE_DOWN_REASON, "upstream_unreachable"),
        (GATEWAY_KEY_REJECTED_REASON, "auth"),
        (PROVIDER_KEY_REJECTED_REASON, "auth"),
        *[(reason, "gateway_unreachable") for reason in GATEWAY_DOWN_REASONS],
        *[(reason, "gateway") for reason in GENERIC_REASONS],
    ],
)
def test_real_gateway_reasons_classify_to_distinct_kinds(reason: str, kind: str) -> None:
    # Classification runs on what the card will show: the sanitised text.
    assert classify_generation_failure(safe_error_message(RuntimeError(reason))) == kind


def test_every_kind_has_a_distinct_hint_and_the_generic_one_is_the_old_card_text() -> None:
    hints = list(GENERATION_FAILURE_HINTS.values())
    assert len(set(hints)) == len(hints)
    assert GENERATION_FAILURE_HINTS["gateway"].startswith("Verify the scoped LiteLLM gateway")
    assert "spending limit" in GENERATION_FAILURE_HINTS["spend_limit"]
    assert "serving lane is not running" in GENERATION_FAILURE_HINTS["upstream_unreachable"]
    assert "gateway did not answer" in GENERATION_FAILURE_HINTS["gateway_unreachable"]
    assert "rejected the API key" in GENERATION_FAILURE_HINTS["auth"]


def test_safe_error_message_strips_secrets_and_key_bearing_urls() -> None:
    raw = RuntimeError(
        f"{SPEND_LIMIT_REASON} Authorization: Bearer sk-or-v1-0123456789abcdefghij token=sk-abcdefghijklmnop\nnext line"
    )
    cleaned = safe_error_message(raw)
    assert KEY_HASH not in cleaned
    assert "openrouter.ai" not in cleaned
    assert "<url>" in cleaned
    assert "sk-or-v1-0123456789abcdefghij" not in cleaned
    assert "sk-abcdefghijklmnop" not in cleaned
    assert "Bearer REDACTED" in cleaned
    assert "\n" not in cleaned
    assert "Key limit exceeded (weekly limit)" in cleaned
    assert len(safe_error_message(RuntimeError("x" * 1000))) == 400


def test_detail_carries_the_sanitised_reason_and_the_matching_hint() -> None:
    detail = generation_unavailable_detail(RuntimeError(SPEND_LIMIT_REASON), operation="Chat stream generation")
    assert isinstance(detail, GenerationUnavailableDetail)
    assert detail.code == "generation_unavailable"
    assert detail.operation == "Chat stream generation"
    assert detail.retryable is True
    assert detail.failure_kind == "spend_limit"
    assert detail.operator_hint == GENERATION_FAILURE_HINTS["spend_limit"]
    assert "Key limit exceeded (weekly limit)" in detail.gateway_reason
    assert KEY_HASH not in detail.gateway_reason
    assert "http" not in detail.gateway_reason.lower().replace("http 403", "")


def test_http_exception_path_agrees_with_the_stream_detail() -> None:
    """Non-stream chat and eval raise through generation_errors; same reason, same hint, same kind."""
    exc = RuntimeError(LANE_DOWN_REASON)
    http = generation_unavailable_http_exception(exc, operation="Chat generation")
    assert http.status_code == 503
    wire = http.detail
    assert isinstance(wire, dict)
    expected = generation_unavailable_detail(exc, operation="Chat generation").model_dump(mode="json")
    assert wire == expected
    assert wire["failure_kind"] == "upstream_unreachable"
    assert wire["operator_hint"] == GENERATION_FAILURE_HINTS["upstream_unreachable"]
    assert "Connection error" in wire["gateway_reason"]
    assert "\n" not in wire["gateway_reason"]


def test_answer_route_error_paths_redact_like_the_chat_path() -> None:
    """/api/answer's failure reason comes from the one shared classifier, so it is sanitised
    by the one shared sanitiser.

    answer_service once kept its own sanitiser copy (no URL rule, a Bearer regex that never
    matched) and used it to build "retrieval-only" answers. Both are gone: the answer lane
    raises, and the reason a client sees is the chat lane's ``generation_unavailable_detail``.
    """
    from server.services import answer_service

    assert answer_service.generation_unavailable_detail is generation_unavailable_detail
    assert not hasattr(answer_service, "safe_error_message")
    raw = RuntimeError(
        f"{SPEND_LIMIT_REASON} Authorization: Bearer sk-or-v1-0123456789abcdefghij\nnext line"
    )
    detail = answer_service.generation_unavailable_detail(raw, operation="Answer stream generation")
    cleaned = detail.gateway_reason
    assert cleaned == safe_error_message(raw)
    assert KEY_HASH not in cleaned
    assert "openrouter.ai" not in cleaned
    assert "<url>" in cleaned
    assert "sk-or-v1-0123456789abcdefghij" not in cleaned
    assert "Bearer REDACTED" in cleaned
    assert "\n" not in cleaned
    assert "Key limit exceeded (weekly limit)" in cleaned
    assert detail.failure_kind == "spend_limit"


def test_no_server_module_keeps_a_private_error_sanitiser() -> None:
    """One redaction rule for every operator-facing reason: a private copy drifts silently."""
    server_root = Path(__file__).resolve().parents[2] / "server"
    canonical = server_root / "chat" / "generation_failure.py"
    definition = re.compile(r"^\s*def _?safe_error_message\(", re.MULTILINE)
    offenders = sorted(
        str(path.relative_to(server_root.parent))
        for path in server_root.rglob("*.py")
        if path != canonical and definition.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == [], f"private error sanitisers outside generation_failure.py: {offenders}"
