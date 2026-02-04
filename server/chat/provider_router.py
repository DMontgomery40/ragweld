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


def _looks_like_openai_model_name(model: str) -> bool:
    """Best-effort heuristic for OpenAI model names.

    Some parts of this codebase store OpenAI model ids unqualified (e.g.
    `generation.gen_model = "gpt-5.1"`). When OPENAI_API_KEY is configured,
    these should route cloud-direct by default even if OpenRouter is enabled.
    """
    m = (model or "").strip().lower()
    return m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


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


def select_provider_route(
    *,
    chat_config: ChatConfig,
    model_override: str = "",
    openai_base_url_override: str = "",
) -> ProviderRoute:
    """Select the provider route for a chat request.

    Selection order (high-level):
    1) Explicit prefixes: `local:<id>` or `openrouter:<id>`
    2) Provider/model ids (`openai/<model>`, `anthropic/<model>`, ...):
       - Prefer cloud-direct OpenAI when OPENAI_API_KEY is set
       - Otherwise, require OpenRouter for non-OpenAI providers (and for OpenAI if no OpenAI key)
    3) Unqualified ids (e.g. `gpt-5.1`): best-effort route cloud-direct OpenAI when configured,
       otherwise fall back to OpenRouter, then local.

    Args:
        chat_config: THE LAW chat configuration (TriBridConfig.chat).
        model_override: Optional override model string. If non-empty (after
            stripping whitespace), it is used as the selected model.
        openai_base_url_override: Optional OpenAI base URL override (proxy)
            sourced from THE LAW (TriBridConfig.generation.openai_base_url).
    """

    override = model_override.strip()
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_base_url = (openai_base_url_override or "").strip() or _OPENAI_DEFAULT_BASE_URL

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
    # Route OpenAI models cloud-direct when OPENAI_API_KEY is set. Use OpenRouter
    # only when explicitly requested (openrouter:<id>) or when required for
    # non-OpenAI providers.
    if "/" in override_model:
        provider_slug, model_name = override_model.split("/", 1)
        provider_slug = provider_slug.strip().lower()
        model_name = model_name.strip()

        if provider_slug == "openai":
            if openai_ready:
                if not model_name:
                    raise RuntimeError("Invalid OpenAI model id (expected openai/<model>)")
                return ProviderRoute(
                    kind="cloud_direct",
                    provider_name="OpenAI",
                    base_url=openai_base_url,
                    model=model_name,
                    api_key=openai_api_key,
                )
            if openrouter_ready:
                # OpenRouter can proxy OpenAI models using the openai/<model> id.
                return ProviderRoute(
                    kind="openrouter",
                    provider_name="OpenRouter",
                    base_url=chat_config.openrouter.base_url,
                    model=override_model,
                    api_key=openrouter_api_key,
                )
            raise RuntimeError("OpenAI not configured (set OPENAI_API_KEY)")

        if openrouter_ready:
            return ProviderRoute(
                kind="openrouter",
                provider_name="OpenRouter",
                base_url=chat_config.openrouter.base_url,
                model=override_model,
                api_key=openrouter_api_key,
            )

        raise RuntimeError(
            f"Cloud model '{override_model}' requires OpenRouter. "
            "Enable config.chat.openrouter.enabled and set OPENROUTER_API_KEY."
        )

    # Unqualified model ids:
    # - If it looks like an OpenAI model and OPENAI_API_KEY is configured, route cloud-direct.
    # - Otherwise, follow the default selection order.
    if override_model and openai_ready and _looks_like_openai_model_name(override_model):
        return ProviderRoute(
            kind="cloud_direct",
            provider_name="OpenAI",
            base_url=openai_base_url,
            model=override_model,
            api_key=openai_api_key,
        )
    if override_model and _looks_like_openai_model_name(override_model) and (not openai_ready) and (not openrouter_ready):
        raise RuntimeError(
            f"Selected model '{override_model}' looks like an OpenAI cloud model, but neither OpenAI nor OpenRouter is configured. "
            "Set OPENAI_API_KEY, or enable config.chat.openrouter.enabled and set OPENROUTER_API_KEY."
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
        model = override_model or "gpt-4o-mini"
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
