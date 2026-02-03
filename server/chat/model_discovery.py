from __future__ import annotations

import os
from typing import Any

import httpx

from server.models.chat_config import LocalModelConfig, LocalProviderEntry, OpenRouterConfig


def _norm_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _norm_local_base_url(url: str) -> str:
    """Normalize a local provider base URL to the provider root.

    Many OpenAI-compatible servers are documented with a trailing `/v1`.
    Our config expects the provider root (we append `/v1/...` internally), so
    strip a trailing `/v1` to avoid double-prefix paths like `/v1/v1/models`.
    """
    u = _norm_base_url(url)
    if u.endswith("/v1"):
        u = u[: -len("/v1")]
    return u


async def discover_local_models(providers: list[LocalProviderEntry]) -> list[dict[str, Any]]:
    """Best-effort discovery of models from enabled local providers.

    Strategy:
    - Prefer OpenAI-compatible `/v1/models` when available.
    - Fallback to Ollama-native `/api/tags` when `/v1/models` is unavailable.

    This must never raise due to provider unavailability.
    """

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # (provider_name, model_id)

    async with httpx.AsyncClient(timeout=2.0) as client:
        for provider in providers:
            if not getattr(provider, "enabled", True):
                continue

            base_url = _norm_local_base_url(getattr(provider, "base_url", ""))
            if not base_url:
                continue

            provider_name = getattr(provider, "name", "") or ""
            provider_type = getattr(provider, "provider_type", "") or ""

            # 1) OpenAI-compatible: /v1/models
            openai_shape_ok = False
            try:
                resp = await client.get(f"{base_url}/v1/models")
                resp.raise_for_status()
                payload: Any = resp.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, list):
                    openai_shape_ok = True
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        model_id = item.get("id")
                        if not isinstance(model_id, str) or not model_id.strip():
                            continue
                        key = (provider_name, model_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(
                            {
                                "id": model_id,
                                "provider": provider_name,
                                "provider_type": provider_type,
                                "base_url": base_url,
                                "source": "local",
                            }
                        )
            except Exception:
                # Swallow per-provider exceptions; fallback attempted below.
                pass

            # 2) Ollama-native fallback: /api/tags
            if openai_shape_ok:
                continue

            try:
                resp = await client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                payload = resp.json()
                models = payload.get("models") if isinstance(payload, dict) else None
                if not isinstance(models, list):
                    continue
                for item in models:
                    if not isinstance(item, dict):
                        continue
                    model_id = item.get("name")
                    if not isinstance(model_id, str) or not model_id.strip():
                        continue
                    key = (provider_name, model_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        {
                            "id": model_id,
                            "provider": provider_name,
                            "provider_type": provider_type,
                            "base_url": base_url,
                            "source": "local",
                        }
                    )
            except Exception:
                # Provider offline/unreachable is expected.
                pass

    return out


async def discover_openrouter_models(cfg: OpenRouterConfig) -> list[dict[str, Any]]:
    """Best-effort discovery of OpenRouter models.

    OpenRouter API key must come from env var OPENROUTER_API_KEY.
    This must never raise on network/parse failures.
    """

    if not getattr(cfg, "enabled", False):
        return []

    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        return []

    base_url = _norm_base_url(getattr(cfg, "base_url", ""))
    if not base_url:
        return []

    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Validate the API key first. `/models` is public and can return 200 even
            # with an invalid key, which makes the UI look like OpenRouter is usable
            # when it isn't.
            key_resp = await client.get(f"{base_url}/key", headers=headers)
            if key_resp.status_code != 200:
                return []

            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload: Any = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                return []

            out: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for item in data:
                if not isinstance(item, dict):
                    continue
                model_id = item.get("id")
                if not isinstance(model_id, str) or not model_id.strip():
                    continue
                key = ("OpenRouter", model_id)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "id": model_id,
                        "provider": "OpenRouter",
                        "provider_type": "openrouter",
                        "base_url": base_url,
                        "source": "openrouter",
                    }
                )
            return out
    except Exception:
        return []


async def discover_models(local_cfg: LocalModelConfig, openrouter_cfg: OpenRouterConfig) -> list[dict[str, Any]]:
    """Combine local + OpenRouter model discovery (best-effort)."""

    openrouter_models = await discover_openrouter_models(openrouter_cfg)

    providers = getattr(local_cfg, "providers", []) if local_cfg is not None else []
    local_models = await discover_local_models(list(providers or []))

    return [*openrouter_models, *local_models]
