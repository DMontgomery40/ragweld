"""Replacement-only tests for the LiteLLM generation route."""

from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator

import pytest

from server.chat.provider_router import select_provider_route
from server.models.chat_config import ChatConfig, LiteLLMConfig
from server.models.tribrid_config_model import TriBridConfig


@contextmanager
def _environment(**values: str | None) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _config(*, enabled: bool = True) -> TriBridConfig:
    return TriBridConfig(
        chat=ChatConfig(
            litellm=LiteLLMConfig(
                enabled=enabled,
                base_url="http://configured.invalid:4000/v1/",
                default_model="ragweld-local",
            )
        )
    )


@pytest.mark.parametrize(
    ("override", "expected_model"),
    [
        ("", "ragweld-local"),
        ("another-gateway-alias", "another-gateway-alias"),
        ("litellm:another-gateway-alias", "another-gateway-alias"),
    ],
)
def test_every_valid_alias_resolves_one_litellm_route(override: str, expected_model: str) -> None:
    with _environment(
        LITELLM_API_KEY="test-gateway-key",
        LITELLM_BASE_URL="http://127.0.0.1:54000/v1/",
        OPENAI_API_KEY="must-not-be-read",
        OPENROUTER_API_KEY="must-not-be-read",
    ):
        route = select_provider_route(config=_config(), model_override=override)

    assert route.kind == "litellm"
    assert route.provider_name == "LiteLLM"
    assert route.base_url == "http://127.0.0.1:54000/v1"
    assert route.model == expected_model
    assert route.api_key == "test-gateway-key"


@pytest.mark.parametrize(
    "override",
    [
        "openrouter:openai/gpt-5.4-mini",
        "local:qwen3:8b",
        "ragweld:mlx-community/Qwen3-1.7B-4bit",
        "openai/gpt-5.4-mini",
        "anthropic/claude-sonnet-4",
    ],
)
def test_direct_provider_identifiers_are_rejected(override: str) -> None:
    with _environment(LITELLM_API_KEY="test-gateway-key"):
        with pytest.raises(RuntimeError, match="gateway alias"):
            select_provider_route(config=_config(), model_override=override)


def test_disabled_gateway_fails_closed_without_fallback() -> None:
    with _environment(
        LITELLM_API_KEY="test-gateway-key",
        OPENAI_API_KEY="must-not-be-used",
        OPENROUTER_API_KEY="must-not-be-used",
    ):
        with pytest.raises(RuntimeError, match="disabled"):
            select_provider_route(config=_config(enabled=False))


def test_missing_gateway_key_fails_closed_without_fallback() -> None:
    with _environment(
        LITELLM_API_KEY=None,
        OPENAI_API_KEY="must-not-be-used",
        OPENROUTER_API_KEY="must-not-be-used",
    ):
        with pytest.raises(RuntimeError, match="LITELLM_API_KEY"):
            select_provider_route(config=_config())
