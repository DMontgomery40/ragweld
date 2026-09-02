"""Reasoning controls in the protocol of a gateway alias's upstream.

Every lane that sends a reasoning-capable alias a reasoning effort shapes the request
here: GraphRAG semantic extraction carries the operator's effort, and the gateway
reranker asks for the lowest effort the upstream honours. Which parameter carries the
effort depends on the LiteLLM upstream behind the alias, never on the alias name.
"""

from __future__ import annotations

from typing import Any

from server.gateway_catalog import OPENROUTER_UPSTREAM_PREFIX

# The cheapest reasoning effort an OpenRouter provider answers with, measured on 2026-09-02
# through the live LiteLLM gateway with 50 real reranking candidates per call (defect D26):
#
#   effort "none"     -> 0 reasoning tokens on openai (gpt-5.6-luna, gpt-4.1-nano), deepseek
#                        (v4-flash), anthropic (claude-haiku-4.5), qwen (qwen3.7-flash),
#                        moonshotai (kimi-k2.5), mistralai, meta-llama; google (gemini-3.7-flash,
#                        gemini-3.5-flash-lite) and z-ai (glm-5.3-flash) reject it with HTTP 400
#                        "Reasoning is mandatory for this endpoint and cannot be disabled".
#   effort "minimal"  -> 0 reasoning tokens on google, ~50-70 on z-ai and openai, but deepseek,
#                        anthropic and qwen treat any effort but "none" as "think" and spent the
#                        whole output budget reasoning; kimi-k2.5 spent 5693 tokens on it.
#
# So "none" is the floor everywhere except the providers whose endpoint declares reasoning
# mandatory, which get the lowest effort they accept. An unmeasured provider that also
# rejects "none" fails closed with that same typed HTTP 400 from the gateway.
LOWEST_REASONING_EFFORT = "none"
MANDATORY_REASONING_LOWEST_EFFORT: dict[str, str] = {"google": "minimal", "z-ai": "minimal"}


def openrouter_provider(route_upstream: str) -> str | None:
    """The provider of a whole ``openrouter/<provider>/<model>`` upstream, else ``None``.

    Both segments must be there: a truncated upstream names no provider, and answering
    for it would send a provider's measured floor to a model that is not that provider's.
    The provider is compared in lower case because it is an identifier, not display text.
    """
    upstream = str(route_upstream or "").strip()
    if not upstream.startswith(OPENROUTER_UPSTREAM_PREFIX):
        return None
    provider, _, model = upstream[len(OPENROUTER_UPSTREAM_PREFIX) :].partition("/")
    if not provider.strip() or not model.strip():
        return None
    return provider.strip().lower()


def lowest_reasoning_effort(route_upstream: str) -> str:
    """The lowest reasoning effort the upstream's provider honours (see the measured table)."""
    provider = openrouter_provider(route_upstream)
    if provider is None:
        raise RuntimeError(
            "lowest reasoning effort is an OpenRouter protocol decision; "
            f"{route_upstream!r} is not an openrouter/<provider>/<model> upstream"
        )
    return MANDATORY_REASONING_LOWEST_EFFORT.get(provider, LOWEST_REASONING_EFFORT)


def reasoning_body_fields(*, reasoning_effort: str, route_upstream: str) -> dict[str, Any]:
    """Top-level chat-completions body fields that carry ``reasoning_effort`` to ``route_upstream``.

    LiteLLM maps the OpenAI ``reasoning_effort`` parameter onto OpenRouter only for models
    its own capability map knows; every newer alias it does not know (the 2026 Gemini Flash
    family among them) answers a request carrying it with a 400 ``UnsupportedParamsError``,
    so a semantic run extracted nothing (follow-up finding D25). OpenRouter's native
    ``reasoning`` object passes LiteLLM untouched and is honoured by every reasoning-capable
    model there and ignored by the rest, so an OpenRouter upstream gets that form. An
    OpenAI-compatible upstream (the local vLLM lane) keeps the OpenAI parameter, which is
    the protocol that server speaks.
    """
    effort = str(reasoning_effort or "").strip()
    if not effort:
        raise RuntimeError("shaping a reasoning-capable request requires a reasoning effort")
    upstream = str(route_upstream or "").strip()
    if not upstream:
        raise RuntimeError("choosing the reasoning protocol requires the alias's gateway upstream")
    if upstream.startswith(OPENROUTER_UPSTREAM_PREFIX):
        return {"reasoning": {"effort": effort}}
    return {"reasoning_effort": effort}


def reasoning_model_params(*, reasoning_effort: str, route_upstream: str) -> dict[str, Any]:
    """The same controls as OpenAI-SDK keyword arguments (``OpenAILLM(model_params=...)``).

    The SDK sends unknown keyword arguments nowhere, so OpenRouter's native ``reasoning``
    object rides in ``extra_body``, which the SDK merges into the request body top level.
    """
    fields = reasoning_body_fields(reasoning_effort=reasoning_effort, route_upstream=route_upstream)
    if "reasoning" in fields:
        return {"temperature": 0, "extra_body": fields}
    return {"temperature": 0, **fields}
