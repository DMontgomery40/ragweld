"""Tests for the OSS config and secret control plane registry."""

from pathlib import Path

import pytest

from server.config_control_plane import (
    _UNIT_SUFFIXES,
    _label_for_path,
    build_config_field_descriptors,
    _build_runtime_integration_readiness,
    list_integration_contracts,
    list_config_leaf_paths,
    validate_config_field_registry,
    validate_integration_contracts,
    validate_secret_registry,
)
from server.chat.provider_router import select_provider_route
from server.gateway_catalog import LOCAL_GATEWAY_ALIAS
from server.models.tribrid_config_model import TriBridConfig


def test_config_control_plane_registry_covers_all_leaf_paths_once() -> None:
    leaf_paths = list_config_leaf_paths()
    descriptors = build_config_field_descriptors()
    descriptor_paths = [descriptor.path for descriptor in descriptors]

    assert descriptor_paths == sorted(descriptor_paths)
    assert len(descriptor_paths) == len(set(descriptor_paths))
    assert set(descriptor_paths) == set(leaf_paths)


def test_config_control_plane_registry_has_no_validation_errors() -> None:
    assert validate_config_field_registry() == []
    assert validate_secret_registry() == []
    assert validate_integration_contracts() == []


def test_a_trailing_unit_suffix_is_rendered_as_a_unit_not_a_word() -> None:
    """`indexing.figures.timeout_s` used to read "Timeout S" (M-160/A-42)."""
    assert _label_for_path("indexing.figures.timeout_s") == "Timeout (seconds)"
    assert _label_for_path("eval.ragas_judge_timeout_s") == "Ragas Judge Timeout (seconds)"
    assert _label_for_path("observability.latency_ms") == "Latency (milliseconds)"
    assert _label_for_path("indexing.index_max_file_size_mb") == "Index Max File Size (MB)"
    assert _label_for_path("ui.learning_reranker_studio_left_panel_pct") == (
        "Learning Reranker Studio Left Panel (%)"
    )
    assert _label_for_path("cost.estimated_cost_usd") == "Estimated Cost (USD)"


def test_a_unit_word_that_is_not_a_suffix_stays_a_word() -> None:
    """Only the LAST segment is a unit; the acronym table still wins for real acronyms."""
    # A single-segment leaf has no unit to strip.
    assert _label_for_path("retrieval.s") == "S"
    # Mid-name occurrences are names, not units.
    assert _label_for_path("retrieval.ms_between_retries") == "Ms Between Retries"
    assert _label_for_path("tracing.otlp_endpoint") == "OTLP Endpoint"


def test_no_registry_label_ends_in_a_bare_unit_abbreviation() -> None:
    """A tree invariant: one stray unit suffix anywhere in the registry fails this."""
    stray = [
        descriptor.path
        for descriptor in build_config_field_descriptors()
        if descriptor.label.split(" ")[-1].lower() in _UNIT_SUFFIXES
    ]
    assert stray == [], f"labels ending in a bare unit abbreviation: {stray}"


def _contract(integration_id: str):
    for contract in list_integration_contracts():
        if contract.id == integration_id:
            return contract
    raise AssertionError(f"no integration contract {integration_id!r}")


async def _vllm_readiness(*, litellm_enabled: bool, chat_model: str = "openai.gpt-5.6-luna"):
    config = TriBridConfig()
    config.chat.litellm.enabled = litellm_enabled
    config.chat.litellm.default_model = chat_model
    config.chat.vllm.enabled = False
    return await _build_runtime_integration_readiness(config, _contract("vllm"))


@pytest.mark.asyncio
async def test_an_unready_vllm_blocks_chat_only_when_chat_runs_on_it() -> None:
    """``blocked_surfaces`` is read by operators as what stops working right now.

    The only production route to generation is ``select_provider_route``, and it fails closed
    when ``chat.litellm.enabled`` is false: there is no direct vLLM route. So an off or
    unreachable vLLM blocks chat and the benchmark only when the gateway is ON and the chat
    default model is the local serving alias (itself a gateway route). With the gateway off,
    chat is blocked by LiteLLM's own row -- not vLLM's (S31)."""
    gateway_on = await _vllm_readiness(litellm_enabled=True)
    assert gateway_on.state != "ready"
    assert gateway_on.blocked_surfaces == ["runtime"]

    # The premise, asserted rather than described: no gateway, no generation route at all.
    # This goes red the moment anyone adds a direct vLLM lane -- the drift that made the old
    # rule claim chat "falls back" to vLLM.
    gateway_off_config = TriBridConfig()
    gateway_off_config.chat.litellm.enabled = False
    with pytest.raises(RuntimeError, match="LiteLLM generation gateway is disabled"):
        select_provider_route(config=gateway_off_config)
    # Chat and the benchmark are blocked with the gateway off -- by LiteLLM's contract.
    assert _contract("litellm").blocked_surfaces == ["runtime", "chat", "benchmark"]

    gateway_off = await _vllm_readiness(litellm_enabled=False)
    assert gateway_off.blocked_surfaces == ["runtime"]

    # The local lane is itself a gateway route, so chat reaches vLLM with the gateway on
    # whenever the chat default model is that route.
    gateway_on_local_model = await _vllm_readiness(
        litellm_enabled=True, chat_model=LOCAL_GATEWAY_ALIAS
    )
    assert set(gateway_on_local_model.blocked_surfaces) == {"runtime", "chat", "benchmark"}


def test_mlflow_does_not_claim_the_eval_lane_it_never_touches() -> None:
    """MLflow is the training lane's run/artifact truth. The eval lane scores with
    Ragas/Promptfoo and imports nothing from MLflow, so an unready MLflow must not tell an
    operator that eval is blocked (S31). The source scan keeps that claim true."""
    assert _contract("mlflow").blocked_surfaces == ["training"]
    root = Path(__file__).resolve().parents[2]
    eval_sources = sorted((root / "server" / "evaluation").rglob("*.py")) + sorted(
        (root / "server" / "api").glob("eval*.py")
    )
    assert eval_sources, "the eval lane's modules moved; update this invariant"
    for source in eval_sources:
        assert "mlflow" not in source.read_text(encoding="utf-8").lower(), (
            f"{source.relative_to(root)} now uses MLflow; the mlflow contract must say it blocks eval"
        )
