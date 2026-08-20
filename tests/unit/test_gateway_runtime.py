from __future__ import annotations

import pytest

from server.chat.gateway_runtime import resolve_litellm_base_url


def test_environment_url_wins_and_is_normalized() -> None:
    assert resolve_litellm_base_url(
        configured_url="http://configured.invalid:4000/v1",
        environ={"LITELLM_BASE_URL": "http://litellm:4000/v1/"},
    ) == "http://litellm:4000/v1"


def test_configured_url_is_used_for_direct_library_callers() -> None:
    assert resolve_litellm_base_url(
        configured_url="http://127.0.0.1:54000/v1/",
        environ={},
    ) == "http://127.0.0.1:54000/v1"


@pytest.mark.parametrize(
    "url",
    ["", "ftp://gateway.invalid/v1", "http://gateway.invalid", "http://gateway.invalid/v2"],
)
def test_invalid_gateway_urls_fail_closed(url: str) -> None:
    with pytest.raises(RuntimeError, match="LiteLLM base URL"):
        resolve_litellm_base_url(configured_url=url, environ={})
