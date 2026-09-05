"""Catalog -> LiteLLM gateway lockstep contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from server.gateway_catalog import (
    CATALOG_PATH,
    LITELLM_CONFIG_PATH,
    LOCAL_GATEWAY_ALIAS,
    WEB_CATALOG_PATH,
    GatewayCatalogError,
    build_litellm_config,
    build_model_list,
    gateway_alias_for_openrouter_id,
    gateway_rows,
    gateway_rows_by_alias,
    gateway_rows_snapshot,
    gateway_upstream_for_alias,
    load_catalog,
    render_litellm_config,
    warm_gateway_catalog,
    write_catalog_trio,
    write_litellm_config,
)
from server.models.runtime_gateway import validate_litellm_alias
from server.models.tribrid_config_model import ModelCatalogEntry

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("model_id", [
    "openai/gpt-4", "openai/gpt-4-turbo-preview", "openai/gpt-4o",
    "openai/gpt-4o-mini:batch", "openai/gpt-4o-mini-2024-07-18",
    "openai/gpt-4.1", "openai/gpt-4.1-nano:batch",
])
def test_blocked_model_family_cannot_become_a_gateway_alias(model_id: str) -> None:
    with pytest.raises(GatewayCatalogError, match="GPT-4-class models are blocked"):
        gateway_alias_for_openrouter_id(model_id)


def test_gateway_catalog_rejects_blocked_upstream_behind_local_alias() -> None:
    row = _local_row(model="openai/gpt-4o-mini")
    with pytest.raises(GatewayCatalogError, match="GPT-4-class models are blocked"):
        gateway_rows({"models": [row]})


def test_published_catalog_model_identities_are_unique() -> None:
    rows = load_catalog()["models"]
    identities = [(row["provider"], row["model"]) for row in rows]
    assert len(identities) == len(set(identities)), "duplicate model identities produce duplicate picker choices"


def _local_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "provider": "ragweld",
        "family": "Qwen3.8-27B",
        "model": "mlx-community/Qwen3.8-27B-4bit",
        "components": ["GEN"],
        "unit": "1k_tokens",
        "context": 32768,
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "base_url": "http://host.docker.internal:58080/v1",
        "gateway_alias": LOCAL_GATEWAY_ALIAS,
        "gateway_upstream": "openai/ragweld-local",
    }
    row.update(overrides)
    return row


def _openrouter_row(model_id: str, **overrides: Any) -> dict[str, Any]:
    provider, _slug = model_id.split("/", 1)
    row: dict[str, Any] = {
        "provider": provider,
        "family": model_id.split("/", 1)[1],
        "model": model_id,
        "components": ["GEN"],
        "unit": "1k_tokens",
        "context": 128000,
        "input_per_1k": 0.001,
        "output_per_1k": 0.002,
        "base_url": "https://openrouter.ai/api/v1",
        "display_name": f"Display {model_id}",
        "gateway_alias": gateway_alias_for_openrouter_id(model_id),
        "gateway_upstream": f"openrouter/{model_id}",
        "supports_vision": True,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("model_id", "alias"),
    [
        ("openai/gpt-5.4-mini", "openai.gpt-5.4-mini"),
        ("qwen/qwen3-coder:free", "qwen.qwen3-coder.free"),
        ("meta-llama/llama-4-maverick", "meta-llama.llama-4-maverick"),
        ("z-ai/glm-5.1", "z-ai.glm-5.1"),
        ("Qwen/Qwen3-4B", "qwen.qwen3-4b"),
    ],
)
def test_alias_derivation_is_slash_free_and_valid(model_id: str, alias: str) -> None:
    derived = gateway_alias_for_openrouter_id(model_id)
    assert derived == alias
    assert validate_litellm_alias(derived, allow_empty=False) == alias
    assert "/" not in derived and ":" not in derived


@pytest.mark.parametrize("model_id", ["", "gpt-5.4-mini", "~openai/gpt-latest", "/gpt", "openai/", "openrouter/auto", "openrouter/free"])
def test_alias_derivation_rejects_non_route_ids(model_id: str) -> None:
    with pytest.raises(GatewayCatalogError):
        gateway_alias_for_openrouter_id(model_id)


def test_model_list_puts_local_serving_row_first_and_routes_openrouter_by_env_key() -> None:
    catalog = {"models": [_openrouter_row("openai/gpt-5.4-mini"), _local_row(), _openrouter_row("anthropic/claude-sonnet-4.5")]}

    model_list = build_model_list(catalog)

    assert [row["model_name"] for row in model_list] == [
        LOCAL_GATEWAY_ALIAS,
        "anthropic.claude-sonnet-4.5",
        "openai.gpt-5.4-mini",
    ]
    assert model_list[0]["litellm_params"] == {
        "model": "openai/ragweld-local",
        "api_base": "http://host.docker.internal:58080/v1",
        "api_key": "none",
    }
    assert model_list[1]["litellm_params"] == {
        "model": "openrouter/anthropic/claude-sonnet-4.5",
        "api_key": "os.environ/OPENROUTER_API_KEY",
    }


def test_rendered_config_has_no_retries_or_fallbacks_and_is_file_authoritative() -> None:
    config = build_litellm_config({"models": [_local_row(), _openrouter_row("openai/gpt-5.4-mini")]})

    assert config["litellm_settings"] == {
        "num_retries": 0,
        "fallbacks": [],
        "context_window_fallbacks": [],
        "callbacks": ["prometheus"],
        "require_auth_for_metrics_endpoint": False,
        "include_cost_in_streaming_usage": True,
    }
    assert config["router_settings"] == {"num_retries": 0}
    assert config["general_settings"] == {"master_key": "os.environ/LITELLM_MASTER_KEY", "store_model_in_db": False}
    rendered = render_litellm_config({"models": [_local_row(), _openrouter_row("openai/gpt-5.4-mini")]})
    assert rendered.startswith("# GENERATED from data/models.json")
    assert yaml.safe_load(rendered) == config


def test_gateway_rows_expose_catalog_metadata_for_discovery_join() -> None:
    rows = gateway_rows_by_alias({"models": [_local_row(), _openrouter_row("openai/gpt-5.4-mini")]})

    paid = rows["openai.gpt-5.4-mini"]
    assert paid.provider == "openai"
    assert paid.model == "openai/gpt-5.4-mini"
    assert paid.display_name == "Display openai/gpt-5.4-mini"
    assert paid.context == 128000
    assert paid.input_per_1k == 0.001
    assert paid.output_per_1k == 0.002
    assert paid.supports_vision is True
    assert rows[LOCAL_GATEWAY_ALIAS].supports_vision is False


def _direct_gen_row() -> dict[str, Any]:
    return {
        "provider": "openai",
        "family": "gpt-5.6",
        "model": "gpt-5.6",
        "components": ["GEN"],
        "unit": "1k_tokens",
        "context": 1_000_000,
        "input_per_1k": 0.002,
        "output_per_1k": 0.008,
        "base_url": "https://api.openai.com/v1",
    }


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        ([_openrouter_row("openai/gpt-5.4-mini")], "exactly one ragweld-local"),
        ([_local_row(), _local_row(model="Qwen/Other")], "duplicate gateway_alias"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", gateway_alias=LOCAL_GATEWAY_ALIAS)], "duplicate"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", gateway_alias="openai/gpt-5.4-mini")], "invalid gateway_alias"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", gateway_upstream=None)], "both be set"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", components=["EMB"])], "only valid on GEN"),
        ([_local_row(base_url=None)], "requires base_url"),
        ([_local_row(), _direct_gen_row()], "must be gateway-served"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", gateway_alias="anthropic.claude")], "does not match the model id"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", gateway_upstream="openrouter/meta-llama/llama-4")], "does not match the model id"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", provider="anthropic")], "provider must equal"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", gateway_upstream="openai/gpt-5.4-mini")], "must be openrouter/<id>"),
        ([_local_row(provider="openai")], "local serving row must be provider"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", context=-5)], "invalid catalog row"),
        ([_local_row(), _openrouter_row("openai/gpt-5.4-mini", supports_vision="sometimes")], "invalid catalog row"),
        ([_local_row(), "not-an-object"], "models\\[1\\] is not an object"),
        ([_local_row(), {"provider": "openrouter", "family": "auto", "model": "openrouter/auto", "components": ["GEN"], "context": 1, "gateway_alias": "openrouter.auto", "gateway_upstream": "openrouter/openrouter/auto"}], "meta-router"),
    ],
)
def test_gateway_rows_fail_closed_on_contract_violations(rows: list[dict[str, Any]], match: str) -> None:
    with pytest.raises(GatewayCatalogError, match=match):
        gateway_rows({"models": rows})


def test_snapshot_is_memory_only_until_warmed_and_tracks_file_changes(tmp_path: Path) -> None:
    target = tmp_path / "models.json"
    target.write_text(json.dumps({"models": [_local_row()]}), encoding="utf-8")

    assert gateway_rows_snapshot(target) == {}
    assert warm_gateway_catalog(target) == 1
    assert set(gateway_rows_snapshot(target)) == {LOCAL_GATEWAY_ALIAS}

    target.write_text(json.dumps({"models": [_local_row(), _openrouter_row("openai/gpt-5.4-mini")]}), encoding="utf-8")
    assert set(gateway_rows_snapshot(target)) == {LOCAL_GATEWAY_ALIAS}, "snapshot never touches disk"
    assert warm_gateway_catalog(target) == 2
    assert "openai.gpt-5.4-mini" in gateway_rows_snapshot(target)


def test_load_catalog_rejects_non_object_roots(tmp_path: Path) -> None:
    target = tmp_path / "models.json"
    target.write_text(json.dumps([_local_row()]), encoding="utf-8")
    with pytest.raises(GatewayCatalogError, match="JSON object"):
        load_catalog(target)


def test_write_catalog_trio_validates_before_writing_and_keeps_all_three_in_lockstep(tmp_path: Path) -> None:
    canonical = tmp_path / "data" / "models.json"
    mirror = tmp_path / "web" / "models.json"
    gateway = tmp_path / "infra" / "litellm-config.yaml"

    with pytest.raises(GatewayCatalogError):
        write_catalog_trio({"models": [_openrouter_row("openai/gpt-5.4-mini")]}, canonical_path=canonical, mirror_path=mirror, litellm_config_path=gateway)
    assert not canonical.exists() and not mirror.exists() and not gateway.exists(), "nothing is written on a contract violation"

    catalog = {"models": [_local_row(), _openrouter_row("openai/gpt-5.4-mini")]}
    write_catalog_trio(catalog, canonical_path=canonical, mirror_path=mirror, litellm_config_path=gateway)
    assert json.loads(canonical.read_text(encoding="utf-8")) == json.loads(mirror.read_text(encoding="utf-8")) == catalog
    assert gateway.read_text(encoding="utf-8") == render_litellm_config(catalog)
    assert (tmp_path / "data" / "models.json.lock").exists()
    assert not list((tmp_path / "data").glob("*.tmp")), "temp files are renamed away"


def test_write_litellm_config_rewrites_in_place_for_the_bind_mount(tmp_path: Path) -> None:
    target = tmp_path / "litellm-config.yaml"
    target.write_text("stale\n", encoding="utf-8")
    inode_before = target.stat().st_ino

    write_litellm_config({"models": [_local_row()]}, target)

    assert target.stat().st_ino == inode_before
    assert yaml.safe_load(target.read_text(encoding="utf-8"))["model_list"][0]["model_name"] == LOCAL_GATEWAY_ALIAS


def test_the_daily_refresh_commits_every_file_it_regenerates() -> None:
    """The catalog refresh workflow must stage all three files `write_catalog_trio` writes.

    The daily job runs `refresh_models_catalog.py --apply`, which rewrites the catalog, the
    web mirror AND the generated `infra/litellm-config.yaml`, but its commit step staged only
    the two JSON files. Every refresh that changed the alias set therefore pushed a catalog
    whose generated gateway config was left behind, and the lockstep test above went red on
    main (2026-09-02: catalog 3ec37d3c added the claude-fable-5.1 aliases and dropped the
    -fast rows while the YAML kept the old ones).
    """
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "refresh-models-catalog.yml"
    ).read_text(encoding="utf-8")
    staged = {
        line.strip().removeprefix("git add ").strip()
        for line in workflow.splitlines()
        if line.strip().startswith("git add ")
    }
    staged_paths = {path for entry in staged for path in entry.split()}
    repo_root = Path(__file__).resolve().parents[2]
    for written in (CATALOG_PATH, WEB_CATALOG_PATH, LITELLM_CONFIG_PATH):
        relative = written.relative_to(repo_root).as_posix()
        assert relative in staged_paths, (
            f"{relative} is regenerated by the refresh but never staged: "
            "the pushed catalog and the generated gateway config would drift apart"
        )


def test_checked_in_gateway_config_is_in_lockstep_with_the_catalog() -> None:
    catalog = load_catalog(CATALOG_PATH)

    assert LITELLM_CONFIG_PATH.read_text(encoding="utf-8") == render_litellm_config(catalog)
    assert json.loads(WEB_CATALOG_PATH.read_text(encoding="utf-8")) == json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_checked_in_catalog_serves_the_openrouter_route_set_through_the_gateway() -> None:
    catalog = load_catalog(CATALOG_PATH)
    rows = gateway_rows(catalog)
    by_alias = {row.alias: row for row in rows}

    assert rows[0].alias == LOCAL_GATEWAY_ALIAS
    assert rows[0].upstream == "openai/ragweld-local"
    openrouter = [row for row in rows if row.upstream.startswith("openrouter/")]
    assert len(openrouter) >= 300
    assert len(openrouter) == len(rows) - 1
    assert "openai.gpt-5.4-mini" in by_alias
    assert by_alias["openai.gpt-5.4-mini"].upstream == "openrouter/openai/gpt-5.4-mini"
    assert all(row.alias == row.alias.lower() for row in rows)
    assert not any(row.provider == "openrouter" for row in rows), "meta-routers are not fixed models"
    assert all(row.context and row.context > 0 for row in rows)
    assert all(row.model == row.upstream.removeprefix("openrouter/") for row in openrouter)
    assert all(row.provider == row.model.split("/", 1)[0] for row in openrouter)
    assert not any(alias.startswith("~") for alias in by_alias)

    catalog_rows = [row for row in catalog["models"] if isinstance(row, dict)]
    gen_rows = [row for row in catalog_rows if row.get("components") == ["GEN"]]
    assert all(row.get("gateway_alias") for row in gen_rows), "every GEN row must be gateway-served"
    assert not any(row.get("provider") in {"ollama", "local"} and row.get("components") == ["GEN"] for row in catalog_rows)
    for row in catalog_rows:
        ModelCatalogEntry.model_validate(row)


@pytest.mark.parametrize("context", [None, 0])
def test_gateway_rows_require_a_positive_context_window(context: int | None) -> None:
    row = _openrouter_row("openai/gpt-5.4-mini")
    if context is None:
        row.pop("context", None)
    else:
        row["context"] = context
    with pytest.raises(GatewayCatalogError, match="positive context window"):
        gateway_rows({"models": [_local_row(), row]})


def test_gateway_upstream_for_alias_reads_the_warmed_snapshot_and_fails_closed() -> None:
    """Follow-up finding D25: the extraction LLM chooses its reasoning transport from the
    alias's LiteLLM upstream, so the lookup must answer from the warmed snapshot (event-loop
    safe) and refuse an alias the catalog does not serve rather than guess a protocol."""
    warm_gateway_catalog(CATALOG_PATH)
    assert gateway_upstream_for_alias("openai.gpt-5.6-luna", CATALOG_PATH) == "openrouter/openai/gpt-5.6-luna"
    assert gateway_upstream_for_alias("ragweld-local", CATALOG_PATH).startswith("openai/")
    with pytest.raises(RuntimeError, match="not in the loaded generation catalog"):
        gateway_upstream_for_alias("nope.not-an-alias", CATALOG_PATH)


def test_checked_in_local_serving_row_names_the_lane_not_a_serving_backend() -> None:
    """Which backend fronts the local alias, and whether the lane is on, is host truth
    (GET /api/runtime-capabilities generation.local_serving); the catalog row must not
    claim one, or every host that does not run it lies in the model pickers."""
    catalog = load_catalog(CATALOG_PATH)
    row = next(item for item in catalog["models"] if item.get("gateway_alias") == LOCAL_GATEWAY_ALIAS)

    assert row["display_name"] == "Ragweld local (self-hosted)"
    for text in (str(row.get("display_name") or ""), str(row.get("notes") or "")):
        lowered = text.lower()
        for backend_claim in ("vllm", "metal", "mlx", "apple"):
            assert backend_claim not in lowered, f"local row still claims a serving backend: {text!r}"
