"""Authenticated model discovery from the sole LiteLLM generation boundary."""

from __future__ import annotations

from typing import Any

import httpx

from server.chat.gateway_runtime import resolve_litellm_api_key, resolve_litellm_base_url
from server.models.chat_config import LiteLLMConfig


async def discover_litellm_models(cfg: LiteLLMConfig) -> list[dict[str, Any]]:
    """Return deduplicated LiteLLM aliases or fail honestly."""

    if not cfg.enabled:
        raise RuntimeError("LiteLLM generation gateway is disabled")
    base_url = resolve_litellm_base_url(configured_url=cfg.base_url)
    api_key = resolve_litellm_api_key()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            payload: Any = response.json()
    except httpx.HTTPStatusError as error:
        raise RuntimeError(f"LiteLLM model discovery failed (HTTP {error.response.status_code})") from error
    except httpx.RequestError as error:
        raise RuntimeError(
            f"LiteLLM model discovery is unavailable: {type(error).__name__}"
        ) from error

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("LiteLLM model discovery returned an invalid payload")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        model_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(model_id, str) or not model_id.strip() or model_id in seen:
            continue
        seen.add(model_id)
        rows.append(
            {
                "id": model_id,
                "provider": "LiteLLM",
                "provider_type": "litellm",
                "base_url": base_url,
                "source": "litellm",
            }
        )
    return rows
