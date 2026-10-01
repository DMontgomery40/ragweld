"""Generation choices are operator-owned; production only supplies their default."""

import json
from pathlib import Path

import pytest

from deploy.proxmox.render_config import _apply_production_defaults, _load_source
from scripts.refresh_models_catalog import production_aliases
from server.models.tribrid_config_model import TriBridConfig
from server.services.config_store import _reconcile_production_scope

LUNA = "openai.gpt-6-luna"
SOL = "openai.gpt-6-sol"


@pytest.mark.parametrize("primary", [SOL, LUNA, "z-ai.glm-5.3-flash"])
def test_production_reconciliation_preserves_explicit_generation_alias(primary: str) -> None:
    global_config = _apply_production_defaults(TriBridConfig())
    global_config.generation.gen_model = LUNA
    scoped = global_config.model_copy(deep=True)
    scoped.generation.gen_model = primary
    scoped.generation.gen_model_http = LUNA
    scoped.generation.gen_model_mcp = SOL
    scoped.generation.gen_model_cli = "z-ai.glm-5.3-flash"
    scoped.ui.open_browser = True

    actual, changed, paths = _reconcile_production_scope(scoped, global_config)

    assert actual.generation == scoped.generation
    assert actual.ui.open_browser is False
    assert changed
    assert "generation.gen_model" not in paths
    assert "ui.open_browser" in paths


def test_production_renderer_defaults_only_primary_generation_to_luna() -> None:
    development = TriBridConfig()
    assert development.generation.gen_model == "ragweld-local"
    actual = _apply_production_defaults(development)
    assert actual.generation.gen_model == LUNA
    assert actual.generation.enrich_model == SOL
    assert actual.evaluation.ragas_judge_model == SOL
    assert actual.evaluation.promptfoo_grader_model == SOL
    assert actual.chat.litellm.default_model == "z-ai.glm-5.3-flash"
    assert actual.chat.multimodal.vision_model_override == "anthropic.claude-sonnet-5"


@pytest.mark.parametrize("runtime_mode", ["development", "production"])
@pytest.mark.parametrize("primary", [SOL, LUNA, "z-ai.glm-5.3-flash"])
def test_renderer_preserves_explicit_primary_and_transport_aliases(runtime_mode: str, primary: str) -> None:
    source = TriBridConfig()
    source.ui.runtime_mode = runtime_mode
    source.generation.gen_model = primary
    source.generation.gen_model_http = LUNA
    source.generation.gen_model_mcp = SOL
    source.generation.gen_model_cli = "z-ai.glm-5.3-flash"

    actual = _apply_production_defaults(source)
    assert actual.generation.gen_model == primary
    assert actual.generation.gen_model_http == LUNA
    assert actual.generation.gen_model_mcp == SOL
    assert actual.generation.gen_model_cli == "z-ai.glm-5.3-flash"
    assert _apply_production_defaults(actual).model_dump() == actual.model_dump()


def test_catalog_refresh_retains_generation_and_other_production_aliases() -> None:
    assert set(production_aliases()) == {
        LUNA, SOL, "z-ai.glm-5.3-flash", "anthropic.claude-sonnet-5",
    }


@pytest.mark.parametrize("payload", [
    {},
    {"generation": {}},
    {"generation": {"gen_model": "ragweld-local"}},
    {"ui": {"runtime_mode": "production"}},
    {"ui": {"runtime_mode": "production"}, "generation": {"gen_model_http": SOL}},
], ids=["omitted-generation", "empty-generation", "development-default", "production-omitted", "production-partial"])
def test_json_renderer_seeds_luna_for_missing_or_development_default(
    tmp_path: Path, payload: dict,
) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    actual = _apply_production_defaults(_load_source(source))
    assert actual.generation.gen_model == LUNA
    assert actual.generation.gen_model_http == payload.get("generation", {}).get("gen_model_http", "")
    assert actual.generation.enrich_model == SOL
    assert actual.evaluation.ragas_judge_model == SOL
    assert actual.evaluation.promptfoo_grader_model == SOL


@pytest.mark.parametrize("primary", [SOL, LUNA, "z-ai.glm-5.3-flash", "ragweld-local", ""])
def test_json_renderer_preserves_present_production_primary(
    tmp_path: Path, primary: str,
) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "ui": {"runtime_mode": "production"},
        "generation": {"gen_model": primary, "gen_model_http": LUNA, "gen_model_mcp": SOL},
    }), encoding="utf-8")
    actual = _apply_production_defaults(_load_source(source))
    assert actual.generation.gen_model == primary
    assert actual.generation.gen_model_http == LUNA
    assert actual.generation.gen_model_mcp == SOL
    assert _apply_production_defaults(actual).model_dump() == actual.model_dump()
