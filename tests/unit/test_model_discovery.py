import os

import pytest

from server.chat.model_discovery import discover_local_models, discover_models, discover_openrouter_models
from server.models.chat_config import LocalModelConfig, LocalProviderEntry, OpenRouterConfig


@pytest.mark.asyncio
async def test_discover_local_models_offline_provider_does_not_raise() -> None:
    provider = LocalProviderEntry(
        name="Offline",
        provider_type="custom",
        base_url="http://127.0.0.1:1",  # connection refused (fast)
        enabled=True,
    )
    models = await discover_local_models([provider])
    assert models == []


@pytest.mark.asyncio
async def test_discover_openrouter_models_disabled_or_missing_env_returns_empty() -> None:
    # Disabled => always empty, no env required.
    disabled = OpenRouterConfig(enabled=False)
    assert await discover_openrouter_models(disabled) == []

    # Enabled but no OPENROUTER_API_KEY => empty.
    enabled = OpenRouterConfig(enabled=True)
    old = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        assert await discover_openrouter_models(enabled) == []
    finally:
        if old is not None:
            os.environ["OPENROUTER_API_KEY"] = old


@pytest.mark.asyncio
async def test_discover_models_combines_lists_without_raising() -> None:
    local_cfg = LocalModelConfig(
        providers=[
            LocalProviderEntry(
                name="Offline",
                provider_type="custom",
                base_url="http://127.0.0.1:1",
                enabled=True,
            )
        ]
    )
    openrouter_cfg = OpenRouterConfig(enabled=False)
    models = await discover_models(local_cfg, openrouter_cfg)
    assert models == []

