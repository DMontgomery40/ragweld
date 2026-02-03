"""Provider routing for Chat 2.0.

This module is intentionally small and unit-testable: it performs deterministic
selection of the chat provider route based on config + environment, with no
network calls or side effects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from server.models.chat_config import ChatConfig


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """Selected chat provider route.

    Fields are intentionally simple so callers can use them to construct an
    OpenAI-compatible client.
    """

    kind: str  # one of: 'openrouter' | 'local' | 'cloud_direct'
    provider_name: str
    base_url: str
    model: str
    api_key: str | None


def select_provider_route(*, chat_config: ChatConfig, model_override: str = "") -> ProviderRoute:
    """Select the provider route for a chat request.

    Selection order:
    1) OpenRouter when enabled AND `OPENROUTER_API_KEY` is set.
    2) Local provider with lowest priority (tie-break by name) when any enabled.
    3) Fallback to a placeholder cloud-direct route.

    Args:
        chat_config: THE LAW chat configuration (TriBridConfig.chat).
        model_override: Optional override model string. If non-empty (after
            stripping whitespace), it is used as the selected model.
    """

    override = model_override.strip()
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    # Explicit provider prefixes (to disambiguate local vs cloud ids like "gpt-4o-mini").
    override_kind = ""
    override_model = override
    if ":" in override:
        prefix, rest = override.split(":", 1)
        p = prefix.strip().lower()
        if p in {"local", "openrouter"}:
            override_kind = p
            override_model = rest.strip()

    enabled_local = [p for p in chat_config.local_models.providers if p.enabled]
    openrouter_ready = bool(chat_config.openrouter.enabled and openrouter_api_key)

    # Force local when requested.
    if override_kind == "local":
        if enabled_local:
            chosen = sorted(enabled_local, key=lambda p: (p.priority, p.name))[0]
            model = override_model or chat_config.local_models.default_chat_model
            return ProviderRoute(
                kind="local",
                provider_name=chosen.name,
                base_url=chosen.base_url,
                model=model,
                api_key=None,
            )
        # No local providers available; fall through to OpenRouter/cloud.

    # Force OpenRouter when requested OR when model id includes a provider prefix (slash).
    if override_kind == "openrouter" or ("/" in override_model):
        model = override_model or chat_config.openrouter.default_model
        if openrouter_ready:
            return ProviderRoute(
                kind="openrouter",
                provider_name="OpenRouter",
                base_url=chat_config.openrouter.base_url,
                model=model,
                api_key=openrouter_api_key,
            )
        return ProviderRoute(
            kind="cloud_direct",
            provider_name="Cloud",
            base_url="",
            model=model,
            api_key=None,
        )

    # Default selection order.
    if openrouter_ready:
        model = override_model or chat_config.openrouter.default_model
        return ProviderRoute(
            kind="openrouter",
            provider_name="OpenRouter",
            base_url=chat_config.openrouter.base_url,
            model=model,
            api_key=openrouter_api_key,
        )

    if enabled_local:
        chosen = sorted(enabled_local, key=lambda p: (p.priority, p.name))[0]
        model = override_model or chat_config.local_models.default_chat_model
        return ProviderRoute(
            kind="local",
            provider_name=chosen.name,
            base_url=chosen.base_url,
            model=model,
            api_key=None,
        )

    # Placeholder for future direct cloud provider integration.
    model = override_model or chat_config.openrouter.default_model or chat_config.local_models.default_chat_model
    return ProviderRoute(
        kind="cloud_direct",
        provider_name="Cloud",
        base_url="",
        model=model,
        api_key=None,
    )

