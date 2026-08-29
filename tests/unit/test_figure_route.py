"""The figure vision alias is resolved through the gateway router, or the run is refused."""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

from server.api.index import _resolve_figure_route
from server.models.tribrid_config_model import TriBridConfig


def test_figures_disabled_resolves_no_route() -> None:
    assert _resolve_figure_route(TriBridConfig()) is None


def test_describe_disabled_resolves_no_route() -> None:
    cfg = TriBridConfig(indexing={"figures": {"enabled": True, "describe": False}})
    assert _resolve_figure_route(cfg) is None


def test_unknown_alias_refuses_the_run() -> None:
    """An alias that is not in the catalog must fail before the run takes the fence."""
    cfg = TriBridConfig(indexing={"figures": {"enabled": True, "vision_model": "nope.not-a-model"}})
    with pytest.raises(HTTPException) as excinfo:
        _resolve_figure_route(cfg)
    assert excinfo.value.status_code == 409
    assert "nope.not-a-model" in str(excinfo.value.detail)


def test_disabled_gateway_refuses_a_vision_capable_alias() -> None:
    """A catalog-valid vision alias is still refused when it cannot be routed."""
    cfg = TriBridConfig(
        indexing={"figures": {"enabled": True, "vision_model": "z-ai.glm-5.3-flash"}},
        chat={"litellm": {"enabled": False}},
    )
    with pytest.raises(HTTPException) as excinfo:
        _resolve_figure_route(cfg)
    assert excinfo.value.status_code == 409
    assert "z-ai.glm-5.3-flash" in str(excinfo.value.detail)


@pytest.mark.skipif(
    not os.getenv("RAGWELD_LIVE_GATEWAY"),
    reason="needs the deployment's LITELLM_* environment (RAGWELD_LIVE_GATEWAY=1)",
)
def test_default_vision_alias_resolves_against_the_live_gateway() -> None:
    from server.gateway_catalog import warm_gateway_catalog

    warm_gateway_catalog()
    cfg = TriBridConfig(indexing={"figures": {"enabled": True}})
    gateway = _resolve_figure_route(cfg)
    assert gateway is not None
    assert gateway.model == "z-ai.glm-5.3-flash"
    assert gateway.base_url.startswith("http") and gateway.base_url.endswith("/v1")
    assert gateway.api_key
