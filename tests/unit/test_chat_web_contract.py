from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.models.tribrid_config_model import ChatRequest, ChatWebConfig, TriBridConfig


def test_web_request_is_opt_in_and_corpus_free() -> None:
    direct = ChatRequest.model_validate({"message": "hello", "sources": {"corpus_ids": []}})
    assert direct.web_enabled is False

    web = ChatRequest.model_validate(
        {"message": "what happened today?", "sources": {"corpus_ids": []}, "web_enabled": True}
    )
    assert web.web_enabled is True
    assert web.sources.corpus_ids == []


@pytest.mark.parametrize("field", ["web_engine", "web_max_results", "web_max_characters"])
def test_client_cannot_override_server_owned_web_limits(field: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"message": "news", "web_enabled": True, field: 999})


def test_unrelated_legacy_extra_fields_remain_tolerated() -> None:
    request = ChatRequest.model_validate({"message": "hello", "legacy_ui_hint": "ignored"})
    assert request.message == "hello"


def test_web_config_defaults_and_bounds() -> None:
    config = TriBridConfig()
    assert config.chat.web == ChatWebConfig(
        enabled=True,
        engine="auto",
        max_results=5,
        max_total_results=5,
        max_characters=12000,
    )
    for field, value in (
        ("max_results", 0),
        ("max_total_results", 0),
        ("max_characters", 999),
    ):
        with pytest.raises(ValidationError):
            ChatWebConfig.model_validate({field: value})
