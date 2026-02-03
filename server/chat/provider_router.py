"""Provider routing for Chat 2.0.

This module is intentionally small and unit-testable: it performs deterministic
selection of the chat provider route based on config + environment, with no
network calls or side effects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from server.models.chat_config import ChatConfig

_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"

def _normalize_local_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    return u[: -len("/v1")] if u.endswith("/v1") else u


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
    3) Fallback to cloud-direct (currently: OpenAI via OPENAI_API_KEY).

    Args:
        chat_config: THE LAW chat configuration (TriBridConfig.chat).
        model_override: Optional override model string. If non-empty (after
            stripping whitespace), it is used as the selected model.
    """

    override = model_override.strip()
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip() or _OPENAI_DEFAULT_BASE_URL

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
    openai_ready = bool(openai_api_key)

    # Force local when requested.
    if override_kind == "local":
        if not enabled_local:
            raise RuntimeError("No local providers enabled (config.chat.local_models.providers)")
        chosen = sorted(enabled_local, key=lambda p: (p.priority, p.name))[0]
        model = override_model or chat_config.local_models.default_chat_model
        return ProviderRoute(
            kind="local",
            provider_name=chosen.name,
            base_url=_normalize_local_base_url(chosen.base_url),
            model=model,
            api_key=None,
        )

    # Force OpenRouter when requested.
    if override_kind == "openrouter":
        if not openrouter_ready:
            raise RuntimeError(
                "OpenRouter not ready (enable config.chat.openrouter.enabled and set OPENROUTER_API_KEY)"
            )
        model = override_model or chat_config.openrouter.default_model
        return ProviderRoute(
            kind="openrouter",
            provider_name="OpenRouter",
            base_url=chat_config.openrouter.base_url,
            model=model,
            api_key=openrouter_api_key,
        )

    # Cloud models use the "provider/model" convention (e.g. openai/gpt-4o-mini).
    # When OpenRouter is enabled, route ALL provider/model IDs through OpenRouter.
    # Otherwise, route through a supported direct provider (currently: OpenAI only).
    if "/" in override_model:
        provider_slug, model_name = override_model.split("/", 1)
        provider_slug = provider_slug.strip().lower()
        model_name = model_name.strip()

        if openrouter_ready:
            return ProviderRoute(
                kind="openrouter",
                provider_name="OpenRouter",
                base_url=chat_config.openrouter.base_url,
                model=override_model,
                api_key=openrouter_api_key,
            )

        if provider_slug == "openai":
            if not openai_ready:
                raise RuntimeError("OpenAI not configured (set OPENAI_API_KEY)")
            if not model_name:
                raise RuntimeError("Invalid OpenAI model id (expected openai/<model>)")
            return ProviderRoute(
                kind="cloud_direct",
                provider_name="OpenAI",
                base_url=openai_base_url,
                model=model_name,
                api_key=openai_api_key,
            )

        raise RuntimeError(
            f"Cloud model '{override_model}' requires OpenRouter. "
            "Enable config.chat.openrouter.enabled and set OPENROUTER_API_KEY."
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
            base_url=_normalize_local_base_url(chosen.base_url),
            model=model,
            api_key=None,
        )

    if openai_ready:
        # Best-effort fallback: treat unqualified overrides as OpenAI model names.
        # This makes the API usable without forcing `openai/<model>` everywhere.
        model = override_model or os.getenv("LLM_MODEL", "").strip() or "gpt-4o-mini"
        return ProviderRoute(
            kind="cloud_direct",
            provider_name="OpenAI",
            base_url=openai_base_url,
            model=model,
            api_key=openai_api_key,
        )

    raise RuntimeError(
        "No chat provider configured. Start a local provider (Ollama/llama.cpp), "
        "or enable OpenRouter (config.chat.openrouter.enabled + OPENROUTER_API_KEY), "
        "or set OPENAI_API_KEY."
    )

