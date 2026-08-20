"""Provider routing for Chat 2.0.

This module is intentionally small and unit-testable: it performs deterministic
selection of the chat provider route based on config + environment, with no
network calls or side effects.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from server.models.tribrid_config_model import GenerationConfig, TriBridConfig
from server.retrieval.mlx_qwen3 import mlx_is_available

_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"

_LOG = logging.getLogger(__name__)


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


def _requires_openai_responses(model: str) -> bool:
    """Return True when a model must use Responses API for cloud-direct OpenAI."""
    m = (model or "").strip().lower()
    if not m:
        return False
    return "codex" in m or m.startswith("gpt-5.2-pro")


def _resolve_openai_protocol(policy: str, model: str) -> Literal["responses", "chat_completions"]:
    p = (policy or "auto").strip().lower()
    if p == "responses":
        return "responses"
    if p == "chat_completions":
        return "chat_completions"
    return "responses" if _requires_openai_responses(model) else "chat_completions"


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """Selected chat provider route.

    Fields are intentionally simple so callers can use them to construct an
    OpenAI-compatible client.
    """

    kind: str  # one of: 'openrouter' | 'local' | 'cloud_direct' | 'ragweld' | 'litellm'
    provider_name: str
    base_url: str
    model: str
    api_key: str | None
    ragweld_backend: str | None = None
    ragweld_base_model: str | None = None
    ragweld_adapter_dir: str | None = None
    ragweld_reload_period_sec: int | None = None
    ragweld_unload_after_sec: int | None = None
    openai_protocol: Literal["responses", "chat_completions"] | None = None


def select_provider_route(
    *,
    config: TriBridConfig,
    model_override: str = "",
) -> ProviderRoute:
    """Select the provider route for a chat request.

    Selection order (high-level):
    1) Explicit prefixes: `local:<id>` or `openrouter:<id>` or `ragweld:<id>` or `litellm:<id>`
    2) Provider/model ids (`openai/<model>`, `anthropic/<model>`, ...):
       - Prefer cloud-direct OpenAI when OPENAI_API_KEY is set
       - Otherwise, require OpenRouter for non-OpenAI providers (and for OpenAI if no OpenAI key)
    3) Unqualified ids (e.g. `gpt-5.1`): best-effort route cloud-direct OpenAI when configured,
       otherwise fall back to OpenRouter, then local.

    Args:
        config: Validated full runtime configuration. Used for chat + training-backed providers.
        model_override: Optional override model string. If non-empty (after
            stripping whitespace), it is used as the selected model.
    """

    chat_config = config.chat
    override = model_override.strip()
    openai_api_key_hint = os.getenv("OPENAI_API_KEY", "").strip()
    openrouter_api_key_hint = os.getenv("OPENROUTER_API_KEY", "").strip()
    has_enabled_local = any(provider.enabled for provider in chat_config.local_models.providers)
    if not override:
        gen_backend = str(getattr(config.generation, "gen_backend", "") or "").strip().lower()
        gen_model = str(getattr(config.generation, "gen_model", "") or "").strip()
        if gen_model and gen_backend:
            if gen_backend == "openai":
                normalized_openai_model = gen_model if ("/" in gen_model or ":" in gen_model) else f"openai/{gen_model}"
                default_gen_model = str(GenerationConfig.model_fields["gen_model"].default or "gpt-4o-mini").strip()
                cloud_capable = bool(openai_api_key_hint or (chat_config.openrouter.enabled and openrouter_api_key_hint))
                # OpenAI-backed generation defaults should still honor the
                # saved OpenAI/OpenRouter cloud route. LiteLLM is an explicit
                # gateway override for generation; the built-in local provider
                # inventory is a serving surface and should not silently
                # hijack the saved OpenAI backend.
                explicit_runtime_route = bool(getattr(chat_config.litellm, "enabled", False))
                if gen_model != default_gen_model or (cloud_capable and not explicit_runtime_route):
                    override = normalized_openai_model
            elif gen_backend in {"ollama", "mlx"}:
                override = f"local:{gen_model}"
            elif gen_backend == "openrouter":
                route_model = gen_model
                if "/" not in route_model and ":" not in route_model:
                    route_model = f"openai/{route_model}"
                override = f"openrouter:{route_model}"
            elif gen_backend == "litellm":
                override = f"litellm:{gen_model}"
            elif gen_backend == "anthropic":
                if "/" in gen_model or ":" in gen_model:
                    override = gen_model
                else:
                    override = f"anthropic/{gen_model}"
            else:
                override = gen_model
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    litellm_api_key = os.getenv("LITELLM_API_KEY", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_base_url = (str(getattr(config.generation, "openai_base_url", "") or "").strip() or _OPENAI_DEFAULT_BASE_URL)
    openai_protocol_policy = str(getattr(config.chat, "openai_protocol", "auto") or "auto").strip().lower()

    # Explicit provider prefixes (to disambiguate local vs cloud ids like "gpt-4o-mini").
    override_kind = ""
    override_model = override
    if ":" in override:
        prefix, rest = override.split(":", 1)
        p = prefix.strip().lower()
        if p in {"local", "openrouter", "ragweld", "litellm"}:
            override_kind = p
            override_model = rest.strip()

    enabled_local = [p for p in chat_config.local_models.providers if p.enabled]
    openrouter_ready = bool(chat_config.openrouter.enabled and openrouter_api_key)
    litellm_ready = bool(getattr(chat_config.litellm, "enabled", False) and str(getattr(chat_config.litellm, "base_url", "") or "").strip())
    openai_ready = bool(openai_api_key)

    # Force ragweld when requested (in-process MLX model).
    if override_kind == "ragweld":
        if not mlx_is_available():
            # Fall back to the normal provider selection order if possible.
            if litellm_ready or openrouter_ready or enabled_local or openai_ready:
                _LOG.warning("ragweld requested but MLX is unavailable; falling back to configured chat providers")
                override_kind = ""
                override_model = ""
            else:
                raise RuntimeError(
                    "ragweld requested but MLX is not available and no fallback provider is configured"
                )
        else:
            model_id = override_model or str(getattr(config.training, "ragweld_agent_base_model", "") or "").strip()
            if not model_id:
                raise RuntimeError("ragweld requested but training.ragweld_agent_base_model is empty")
            return ProviderRoute(
                kind="ragweld",
                provider_name="Ragweld",
                base_url="",
                model=model_id,
                api_key=None,
                ragweld_backend=str(getattr(config.training, "ragweld_agent_backend", "") or "").strip() or "mlx_qwen3",
                ragweld_base_model=str(getattr(config.training, "ragweld_agent_base_model", "") or "").strip() or model_id,
                ragweld_adapter_dir=str(getattr(config.training, "ragweld_agent_model_path", "") or "").strip(),
                ragweld_reload_period_sec=int(getattr(config.training, "ragweld_agent_reload_period_sec", 60) or 60),
                ragweld_unload_after_sec=int(getattr(config.training, "ragweld_agent_unload_after_sec", 0) or 0),
            )

    # Force LiteLLM when requested.
    if override_kind == "litellm":
        if not litellm_ready:
            raise RuntimeError("LiteLLM not ready (enable config.chat.litellm.enabled and set chat.litellm.base_url)")
        model = override_model or str(getattr(chat_config.litellm, "default_model", "") or "").strip()
        if not model:
            raise RuntimeError("LiteLLM enabled but chat.litellm.default_model is empty")
        return ProviderRoute(
            kind="litellm",
            provider_name="LiteLLM",
            base_url=str(chat_config.litellm.base_url).rstrip("/"),
            model=model,
            api_key=litellm_api_key or None,
        )

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
                    openai_protocol=_resolve_openai_protocol(openai_protocol_policy, model_name),
                )
            if litellm_ready:
                return ProviderRoute(
                    kind="litellm",
                    provider_name="LiteLLM",
                    base_url=str(chat_config.litellm.base_url).rstrip("/"),
                    model=override_model,
                    api_key=litellm_api_key or None,
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

        if litellm_ready:
            return ProviderRoute(
                kind="litellm",
                provider_name="LiteLLM",
                base_url=str(chat_config.litellm.base_url).rstrip("/"),
                model=override_model,
                api_key=litellm_api_key or None,
            )

        if openrouter_ready:
            return ProviderRoute(
                kind="openrouter",
                provider_name="OpenRouter",
                base_url=chat_config.openrouter.base_url,
                model=override_model,
                api_key=openrouter_api_key,
            )

        raise RuntimeError(
            f"Cloud model '{override_model}' requires a configured gateway route. "
            "Enable LiteLLM (config.chat.litellm.enabled + chat.litellm.base_url), "
            "or enable OpenRouter (config.chat.openrouter.enabled + OPENROUTER_API_KEY)."
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
            openai_protocol=_resolve_openai_protocol(openai_protocol_policy, override_model),
        )
    if override_model and _looks_like_openai_model_name(override_model) and (not openai_ready) and (not openrouter_ready) and (not litellm_ready):
        raise RuntimeError(
            f"Selected model '{override_model}' looks like an OpenAI cloud model, but neither OpenAI nor a gateway route is configured. "
            "Set OPENAI_API_KEY, or enable LiteLLM (config.chat.litellm.enabled + chat.litellm.base_url), "
            "or enable OpenRouter (config.chat.openrouter.enabled + OPENROUTER_API_KEY)."
        )

    # Default selection order.
    if litellm_ready:
        model = override_model or str(getattr(chat_config.litellm, "default_model", "") or "").strip()
        return ProviderRoute(
            kind="litellm",
            provider_name="LiteLLM",
            base_url=str(chat_config.litellm.base_url).rstrip("/"),
            model=model,
            api_key=litellm_api_key or None,
        )

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
            openai_protocol=_resolve_openai_protocol(openai_protocol_policy, model),
        )

    raise RuntimeError(
        "No chat provider configured. Enable LiteLLM (config.chat.litellm.enabled + chat.litellm.base_url), "
        "or start a local provider (Ollama/llama.cpp/vLLM), "
        "or enable OpenRouter (config.chat.openrouter.enabled + OPENROUTER_API_KEY), "
        "or set OPENAI_API_KEY."
    )
