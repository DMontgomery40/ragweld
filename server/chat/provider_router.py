"""Replacement-only routing to Ragweld's LiteLLM generation gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from server.chat.gateway_runtime import resolve_litellm_api_key, resolve_litellm_base_url
from server.gateway_catalog import gateway_rows_snapshot
from server.model_policy import ensure_model_allowed
from server.models.tribrid_config_model import TriBridConfig

_GATEWAY_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REMOVED_PREFIXES = {"local", "openrouter", "ragweld", "openai", "anthropic", "ollama", "mlx"}


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """The one supported application-to-generation transport."""

    kind: Literal["litellm"]
    provider_name: str
    base_url: str
    model: str
    api_key: str


def _resolve_gateway_alias(raw_override: str, default_alias: str) -> str:
    override = raw_override.strip()
    if override.startswith("litellm:"):
        override = override.split(":", 1)[1].strip()
    elif ":" in override and override.split(":", 1)[0].strip().lower() in _REMOVED_PREFIXES:
        raise RuntimeError("Generation model_override must be a LiteLLM gateway alias")

    alias = override or default_alias.strip()
    try:
        ensure_model_allowed(alias)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    if not _GATEWAY_ALIAS.fullmatch(alias):
        raise RuntimeError("Generation model_override must be a LiteLLM gateway alias")
    return alias


def select_provider_route(*, config: TriBridConfig, model_override: str = "") -> ProviderRoute:
    """Resolve one authenticated LiteLLM route or fail closed.

    Direct provider credentials, local inference inventory, and provider/model
    identifiers are deliberately ignored. Upstream routing belongs to LiteLLM.
    The alias must be a catalog-backed gateway alias (the in-memory snapshot of
    data/models.json, warmed at startup); unknown aliases fail closed.
    """

    gateway = config.chat.litellm
    if not gateway.enabled:
        raise RuntimeError("LiteLLM generation gateway is disabled")

    alias = _resolve_gateway_alias(model_override, gateway.default_model)
    catalog = gateway_rows_snapshot()
    if not catalog:
        raise RuntimeError("Generation catalog is not loaded; gateway aliases cannot be verified")
    if alias not in catalog:
        raise RuntimeError(f"Generation model_override {alias!r} is not a gateway alias in data/models.json")
    return ProviderRoute(
        kind="litellm",
        provider_name="LiteLLM",
        base_url=resolve_litellm_base_url(configured_url=gateway.base_url),
        model=alias,
        api_key=resolve_litellm_api_key(),
    )
