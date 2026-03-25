"""Tests for chat provider routing."""

from __future__ import annotations

import os

from server.chat.provider_router import select_provider_route
from server.models.chat_config import (
    ChatConfig,
    LiteLLMConfig,
    LocalModelConfig,
    LocalProviderEntry,
    OpenRouterConfig,
)
from server.models.tribrid_config_model import TriBridConfig


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


def _set_litellm_api_key(value: str | None) -> str | None:
    old = os.environ.get("LITELLM_API_KEY")
    if value is None:
        os.environ.pop("LITELLM_API_KEY", None)
    else:
        os.environ["LITELLM_API_KEY"] = value
    return old


def _restore_litellm_api_key(old: str | None) -> None:
    if old is None:
        os.environ.pop("LITELLM_API_KEY", None)
    else:
        os.environ["LITELLM_API_KEY"] = old


def test_select_provider_route_prefers_openrouter_when_enabled_and_key_present() -> None:
    old = _set_openrouter_api_key("test-openrouter-key")
    try:
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default"))

        route = select_provider_route(config=TriBridConfig(chat=cfg), model_override="override-model")

        assert route.kind == "openrouter"
        assert route.provider_name == "OpenRouter"
        assert route.base_url == cfg.openrouter.base_url
        assert route.model == "override-model"
        assert route.api_key == "test-openrouter-key"
    finally:
        _restore_openrouter_api_key(old)


def test_select_provider_route_falls_back_to_local_when_openrouter_key_missing() -> None:
    old = _set_openrouter_api_key(None)
    old_openai = _set_openai_api_key(None)
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

        route = select_provider_route(config=TriBridConfig(chat=cfg))

        assert route.kind == "local"
        assert route.provider_name == "A"  # tie-break by name
        assert route.base_url == "http://a.local"
        assert route.model == "local-default"
        assert route.api_key is None
    finally:
        _restore_openai_api_key(old_openai)
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

        route = select_provider_route(config=TriBridConfig(chat=cfg), model_override="openai/gpt-4o-mini")

        assert route.kind == "cloud_direct"
        assert route.provider_name == "OpenAI"
        assert route.base_url.startswith("https://api.openai.com")
        assert route.model == "gpt-4o-mini"
        assert route.api_key == "test-openai-key"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_does_not_hijack_openai_prefix_with_openrouter_when_openai_ready() -> None:
    """Regression test: OpenRouter being enabled must not hijack OpenAI models by default."""
    old_openrouter = _set_openrouter_api_key("test-openrouter-key")
    old_openai = _set_openai_api_key("test-openai-key")
    try:
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default"))
        route = select_provider_route(config=TriBridConfig(chat=cfg), model_override="openai/gpt-4o-mini")
        assert route.kind == "cloud_direct"
        assert route.provider_name == "OpenAI"
        assert route.model == "gpt-4o-mini"
        assert route.api_key == "test-openai-key"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_routes_unqualified_gpt_models_cloud_direct_when_openai_ready() -> None:
    old_openrouter = _set_openrouter_api_key("test-openrouter-key")
    old_openai = _set_openai_api_key("test-openai-key")
    try:
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default"))
        route = select_provider_route(config=TriBridConfig(chat=cfg), model_override="gpt-5.1")
        assert route.kind == "cloud_direct"
        assert route.provider_name == "OpenAI"
        assert route.model == "gpt-5.1"
        assert route.api_key == "test-openai-key"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_honors_openai_backend_with_saved_default_generation_values() -> None:
    old_openrouter = _set_openrouter_api_key("test-openrouter-key")
    old_openai = _set_openai_api_key("test-openai-key")
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default"))
        )
        # Simulate persisted config round-trip (full payload written/read).
        cfg = TriBridConfig.model_validate(cfg.model_dump(mode="serialization", by_alias=True))
        route = select_provider_route(config=cfg)
        assert route.kind == "cloud_direct"
        assert route.provider_name == "OpenAI"
        assert route.model == "gpt-4o-mini"
        assert route.api_key == "test-openai-key"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_uses_openrouter_for_default_openai_backend_without_openai_key() -> None:
    old_openrouter = _set_openrouter_api_key("test-openrouter-key")
    old_openai = _set_openai_api_key(None)
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default")),
        )
        route = select_provider_route(config=cfg)
        assert route.kind == "openrouter"
        assert route.provider_name == "OpenRouter"
        assert route.model == "openai/gpt-4o-mini"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_explicit_litellm_prefix_routes_gateway() -> None:
    old_openai = _set_openai_api_key(None)
    old_openrouter = _set_openrouter_api_key(None)
    old_litellm = _set_litellm_api_key("test-litellm-key")
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(
                litellm=LiteLLMConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:4000/v1",
                    default_model="openai/gpt-4o-mini",
                ),
                openrouter=OpenRouterConfig(enabled=False),
            ),
        )
        route = select_provider_route(config=cfg, model_override="litellm:openai/gpt-4o-mini")
        assert route.kind == "litellm"
        assert route.provider_name == "LiteLLM"
        assert route.base_url == "http://127.0.0.1:4000/v1"
        assert route.model == "openai/gpt-4o-mini"
        assert route.api_key == "test-litellm-key"
    finally:
        _restore_litellm_api_key(old_litellm)
        _restore_openrouter_api_key(old_openrouter)
        _restore_openai_api_key(old_openai)


def test_select_provider_route_prefers_litellm_for_cloud_models_when_openai_missing() -> None:
    old_openai = _set_openai_api_key(None)
    old_openrouter = _set_openrouter_api_key(None)
    old_litellm = _set_litellm_api_key(None)
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(
                litellm=LiteLLMConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:4000/v1",
                    default_model="openai/gpt-4o-mini",
                ),
                openrouter=OpenRouterConfig(enabled=False),
            ),
        )
        route = select_provider_route(config=cfg, model_override="openai/gpt-4o-mini")
        assert route.kind == "litellm"
        assert route.provider_name == "LiteLLM"
        assert route.model == "openai/gpt-4o-mini"
    finally:
        _restore_litellm_api_key(old_litellm)
        _restore_openrouter_api_key(old_openrouter)
        _restore_openai_api_key(old_openai)


def test_select_provider_route_honors_litellm_generation_backend() -> None:
    old_openai = _set_openai_api_key(None)
    old_openrouter = _set_openrouter_api_key(None)
    old_litellm = _set_litellm_api_key(None)
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(
                litellm=LiteLLMConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:4000/v1",
                    default_model="anthropic/claude-sonnet-4",
                ),
                openrouter=OpenRouterConfig(enabled=False),
            ),
        )
        cfg.generation.gen_backend = "litellm"
        cfg.generation.gen_model = "anthropic/claude-sonnet-4"
        route = select_provider_route(config=cfg)
        assert route.kind == "litellm"
        assert route.provider_name == "LiteLLM"
        assert route.model == "anthropic/claude-sonnet-4"
    finally:
        _restore_litellm_api_key(old_litellm)
        _restore_openrouter_api_key(old_openrouter)
        _restore_openai_api_key(old_openai)


def test_select_provider_route_honors_non_default_openai_generation_model() -> None:
    old_openrouter = _set_openrouter_api_key("test-openrouter-key")
    old_openai = _set_openai_api_key("test-openai-key")
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default")),
        )
        cfg.generation.gen_backend = "openai"
        cfg.generation.gen_model = "gpt-5.2"
        route = select_provider_route(config=cfg)
        assert route.kind == "cloud_direct"
        assert route.provider_name == "OpenAI"
        assert route.model == "gpt-5.2"
        assert route.api_key == "test-openai-key"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_preserves_non_default_openai_model_without_openai_key() -> None:
    old_openrouter = _set_openrouter_api_key("test-openrouter-key")
    old_openai = _set_openai_api_key(None)
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default")),
        )
        cfg.generation.gen_backend = "openai"
        cfg.generation.gen_model = "gpt-5.2"
        route = select_provider_route(config=cfg)
        assert route.kind == "openrouter"
        assert route.provider_name == "OpenRouter"
        assert route.model == "openai/gpt-5.2"
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)


def test_select_provider_route_local_prefix_forces_local_even_when_openrouter_ready() -> None:
    old = _set_openrouter_api_key("test-openrouter-key")
    try:
        cfg = ChatConfig(openrouter=OpenRouterConfig(enabled=True, default_model="openrouter-default"))
        route = select_provider_route(config=TriBridConfig(chat=cfg), model_override="local:qwen3:8b")
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
            select_provider_route(config=TriBridConfig(chat=cfg))
            raise AssertionError("Expected select_provider_route to raise")
        except RuntimeError as e:
            assert "No chat provider configured" in str(e)
    finally:
        _restore_openai_api_key(old_openai)
        _restore_openrouter_api_key(old_openrouter)
