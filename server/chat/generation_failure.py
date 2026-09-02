"""Operator-facing classification of generation-gateway failures.

One place turns the exception the gateway transport raised into the typed
``GenerationUnavailableDetail`` every generation surface returns (chat stream,
chat, eval): the sanitised provider reason plus an operator hint chosen from that
reason. Before this, every failure carried the same "verify the gateway, client
key and alias" hint, so an exhausted OpenRouter spending limit sent the operator
to check keys and aliases that were fine (2026-09-02 drive, S9).
"""

from __future__ import annotations

import re

from server.models.tribrid_config_model import GenerationFailureKind, GenerationUnavailableDetail

_SK_TOKEN_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{10,})")
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9_.\-]{10,}")
# Provider management links can carry key identifiers in the path (OpenRouter's
# ".../keys/<key hash>"), so no URL survives into an operator-facing payload.
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")

# Checked in this order: the gateway itself not answering (the transport's own
# "failed at <url>" wording, from server/chat/generation.py), then the upstream lane
# being down (its gateway wrapper also says "InternalServerError" and "500"), a
# rejected key next, and a spending or credit limit last (a limit answer is a
# 402/403 that mentions no key problem).
_GATEWAY_UNREACHABLE_RE = re.compile(r"^LiteLLM (?:request|stream) failed at <url>", re.IGNORECASE)
_UPSTREAM_UNREACHABLE_RE = re.compile(
    r"connection (?:error|refused|reset)"
    r"|apiconnectionerror|connecterror|connectionerror"
    r"|name or service not known|no route to host|network is unreachable"
    r"|failed to establish a new connection",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"unauthori[sz]ed|authenticationerror|authentication (?:failed|error)"
    r"|invalid[_ ]api[_ ]key|incorrect api key|api[_ -]?key"
    r"|\b401\b",
    re.IGNORECASE,
)
_SPEND_LIMIT_RE = re.compile(
    r"limit exceeded|insufficient[_ ](?:credits|funds|balance|quota)"
    r"|exceeded your current quota|budget (?:exceeded|has been exhausted)|budgetexceedederror"
    r"|\b402\b|\b403\b",
    re.IGNORECASE,
)

GENERATION_FAILURE_HINTS: dict[GenerationFailureKind, str] = {
    "spend_limit": (
        "The provider key's spending limit is exhausted; raise it or wait for the reset, then retry. "
        "Ragweld did not substitute a direct provider fallback."
    ),
    "auth": (
        "The gateway or provider rejected the API key; check the LiteLLM client key and the provider key "
        "on this alias's route, then retry. Ragweld did not substitute a direct provider fallback."
    ),
    "upstream_unreachable": (
        "The alias's serving lane is not running; start it or pick another alias, then retry. "
        "Ragweld did not substitute a direct provider fallback."
    ),
    "gateway_unreachable": (
        "The LiteLLM gateway did not answer at its configured base URL; start it or fix the URL, then retry. "
        "Ragweld did not substitute a direct provider fallback."
    ),
    "gateway": (
        "Verify the scoped LiteLLM gateway, client key, and selected model alias, then retry. "
        "Ragweld did not substitute a direct provider fallback."
    ),
}

GENERATION_UNAVAILABLE_MESSAGE = "The generation gateway could not complete the chat request."


def safe_error_message(e: BaseException, *, max_len: int = 400) -> str:
    """Best-effort redaction: keep the reason useful without leaking secrets or key-bearing links."""
    msg = str(e) or type(e).__name__
    msg = _SK_TOKEN_RE.sub("sk-REDACTED", msg)
    msg = _BEARER_RE.sub(r"\1REDACTED", msg)
    msg = _URL_RE.sub("<url>", msg)
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    return msg[: int(max_len)]


def classify_generation_failure(reason: str) -> GenerationFailureKind:
    """Classify a sanitised gateway reason into the operator-facing failure kind."""
    text = str(reason or "")
    if _GATEWAY_UNREACHABLE_RE.search(text):
        return "gateway_unreachable"
    if _UPSTREAM_UNREACHABLE_RE.search(text):
        return "upstream_unreachable"
    if _AUTH_RE.search(text):
        return "auth"
    if _SPEND_LIMIT_RE.search(text):
        return "spend_limit"
    return "gateway"


def generation_unavailable_detail(exc: BaseException, *, operation: str) -> GenerationUnavailableDetail:
    """Build the typed detail for a generation failure: sanitised reason, classified kind, matching hint."""
    reason = safe_error_message(exc)
    kind = classify_generation_failure(reason)
    return GenerationUnavailableDetail(
        operation=operation,
        message=GENERATION_UNAVAILABLE_MESSAGE,
        operator_hint=GENERATION_FAILURE_HINTS[kind],
        failure_kind=kind,
        gateway_reason=reason,
    )
