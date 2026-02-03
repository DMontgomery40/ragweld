"""Tests for chat provider routing."""

from __future__ import annotations

import os

from server.chat.provider_router import select_provider_route
from server.models.chat_config import ChatConfig, LocalModelConfig, LocalProviderEntry, OpenRouterConfig


def _set_openrouter_api_key(value: str | None) -> str | None:
    """Set/clear OPENROUTER_API_KEY and return previous value."""

    old = os.environ.get("OPENROUTER_API_KEY")
    if value is None:
        os.environ.pop("OPENROUTER_API_KEY", None)
    else:
        os.environ["OPENROUTER_API_KEY"] = value
    return old


def _restore_openrouter_api_key(old: str | None) -> None:
    if old is None:
        os.environ.pop("OPENROUTER_API_KEY", None)
    else:
        os.environ["OPENROUTER_API_KEY"] = old


def _set_openai_api_key(value: str | None) -> str | None:
    old = os.environ.get("OPENAI_API_KEY")
    if value is None:
        os.environ.pop("OPENAI_API_KEY", None)
    else:
        os.environ["OPENAI_API_KEY"] = value
    return old


def _restore_openai_api_key(old: str | None) -> None:
    if old is None:
        os.environ.pop("OPENAI_API_KEY", None)
    else:
        os.environ["OPENAI_API_KEY"] = old


def test_select_provider_route_prefers_openrouter_when_enabled_and_key_present() -> None:
    old = _set_openrouter_api_key("test-openrouter-key")
    try:
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default"))

        route = select_provider_route(chat_config=cfg, model_override="override-model")

        assert route.kind == "openrouter"
        assert route.provider_name == "OpenRouter"
        assert route.base_url == cfg.openrouter.base_url
        assert route.model == "override-model"
        assert route.api_key == "test-openrouter-key"
    finally:
        _restore_openrouter_api_key(old)


def test_select_provider_route_falls_back_to_local_when_openrouter_key_missing() -> None:
    old = _set_openrouter_api_key(None)
    try:
        local = LocalModelConfig(
            providers=[
                LocalProviderEntry(
                    name="B",
                    provider_type="custom",
                    base_url="http://b.local",
                    enabled=True,
                    priority=0,
                ),
                LocalProviderEntry(
                    name="A",
                    provider_type="custom",
                    base_url="http://a.local",
                    enabled=True,
                    priority=0,
                ),
            ],
            default_chat_model="local-default",
        )
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=True), local_models=local)

        route = select_provider_route(chat_config=cfg)

        assert route.kind == "local"
        assert route.provider_name == "A"  # tie-break by name
        assert route.base_url == "http://a.local"
        assert route.model == "local-default"
        assert route.api_key is None
    finally:
        _restore_openrouter_api_key(old)


def test_select_provider_route_uses_cloud_direct_openai_for_openai_prefix_when_key_present() -> None:
    old_openrouter = _set_openrouter_api_key(None)
    old_openai = _set_openai_api_key("test-openai-key")
    try:
        local = LocalModelConfig(
            providers=[
                LocalProviderEntry(
                    name="DisabledA",
                    provider_type="custom",
                    base_url="http://a.local",
                    enabled=False,
                    priority=0,
                ),
                LocalProviderEntry(
                    name="DisabledB",
                    provider_type="custom",
                    base_url="http://b.local",
                    enabled=False,
                    priority=0,
                ),
            ],
            default_chat_model="local-default",
        )
        cfg = ChatConfig(
            openrouter=OpenRouterConfig(enabled=False, default_model="openrouter-default"),
            local_models=local,
        )

        route = select_provider_route(chat_config=cfg, model_override="openai/gpt-4o-mini")

        assert route.kind == "cloud_direct"
        assert route.provider_name == "OpenAI"
        assert route.base_url.startswith("https://api.openai.com")
        assert route.model == "gpt-4o-mini"
        assert route.api_key == "test-openai-key"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_local_prefix_forces_local_even_when_openrouter_ready() -> None:
    old = _set_openrouter_api_key("test-openrouter-key")
    try:
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default"))
        route = select_provider_route(chat_config=cfg, model_override="local:qwen3:8b")
        assert route.kind == "local"
        assert route.model == "qwen3:8b"
        assert route.api_key is None
    finally:
        _restore_openrouter_api_key(old)


def test_select_provider_route_raises_when_no_provider_configured() -> None:
    old_openrouter = _set_openrouter_api_key(None)
    old_openai = _set_openai_api_key(None)
    try:
        local = LocalModelConfig(
            providers=[
                LocalProviderEntry(
                    name="DisabledA",
                    provider_type="custom",
                    base_url="http://a.local",
                    enabled=False,
                    priority=0,
                ),
            ],
            default_chat_model="local-default",
        )
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=False), local_models=local)
        try:
            select_provider_route(chat_config=cfg)
            assert False, "Expected select_provider_route to raise"
        except RuntimeError as e:
            assert "No chat provider configured" in str(e)
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)

