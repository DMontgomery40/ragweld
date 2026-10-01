"""Real config API and Postgres round trips for production generation settings."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

from deploy.proxmox.render_config import _apply_production_defaults
from server.config import load_config
from server.config_redaction import redact_config_secrets
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import TriBridConfig
from server.services.config_store import ConfigStore, get_config_store

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]
LUNA = "openai.gpt-6-luna"
SOL = "openai.gpt-6-sol"


def public_payload(config: TriBridConfig) -> dict:
    return redact_config_secrets(config).model_dump(mode="json")


@pytest_asyncio.fixture
async def generation_scope() -> AsyncIterator[tuple[str, PostgresClient]]:
    # conftest owns a private runtime config; no live/global operator file is written.
    config = _apply_production_defaults(load_config())
    config.generation.gen_model = LUNA
    config.generation.enrich_model = SOL
    await get_config_store().save(config)
    postgres = PostgresClient(config.indexing.postgres_url, schema_mode="control")
    await postgres.connect()
    corpus_id = f"pytest_generation_settings_{uuid4().hex}"
    await postgres.upsert_corpus(corpus_id, "Generation settings persistence", ".")
    try:
        yield corpus_id, postgres
    finally:
        get_config_store().clear_cache(corpus_id)
        await postgres.delete_corpus(corpus_id)
        await postgres.disconnect()


@pytest.mark.parametrize("primary", [SOL, LUNA, "z-ai.glm-5.3-flash"])
async def test_apply_readback_and_new_store_preserve_primary_and_http_alias(
    client: AsyncClient, generation_scope: tuple[str, PostgresClient], primary: str,
) -> None:
    corpus_id, postgres = generation_scope
    params = {"corpus_id": corpus_id}
    baseline = await client.get("/api/config", params=params)
    assert baseline.status_code == 200, baseline.text
    payload = baseline.json()
    assert payload["generation"]["gen_model"] == LUNA
    payload["generation"]["gen_model"] = primary
    payload["generation"]["gen_model_http"] = LUNA
    payload["generation"]["gen_model_mcp"] = SOL
    payload["generation"]["gen_model_cli"] = "z-ai.glm-5.3-flash"
    payload["vector_search"]["top_k"] = 31

    applied = await client.put("/api/config", params=params, json=payload)
    assert applied.status_code == 200, applied.text
    assert applied.json() == payload
    stored = await postgres.get_corpus_config_json(corpus_id)
    assert stored is not None
    assert public_payload(TriBridConfig.model_validate(stored)) == payload
    for clear_cache in (False, True):
        if clear_cache:
            get_config_store().clear_cache()
        readback = await client.get("/api/config", params=params)
        assert readback.status_code == 200, readback.text
        assert readback.json() == payload
    restarted = ConfigStore(load_config().indexing.postgres_url)
    assert public_payload(await restarted.get(corpus_id)) == payload

    # A later global default change cannot migrate an explicit corpus choice.
    global_config = await get_config_store().get()
    global_config.generation.gen_model = SOL if primary == LUNA else LUNA
    await get_config_store().save(global_config)
    assert (await client.get("/api/config", params=params)).json() == payload
    restarted.clear_cache()
    assert public_payload(await restarted.get(corpus_id)) == payload


@pytest.mark.parametrize("raw", [{}, {"generation": {"gen_model_http": SOL}}])
async def test_partial_stored_config_adopts_global_generation_default(
    client: AsyncClient, generation_scope: tuple[str, PostgresClient], raw: dict,
) -> None:
    corpus_id, postgres = generation_scope
    await postgres.upsert_corpus_config_json(corpus_id, raw)
    get_config_store().clear_cache(corpus_id)
    before = await get_config_store().get(corpus_id, persist=False)
    assert before.generation.gen_model == LUNA
    assert await postgres.get_corpus_config_json(corpus_id) == raw
    response = await client.get("/api/config", params={"corpus_id": corpus_id})
    assert response.status_code == 200, response.text
    assert response.json()["generation"]["gen_model"] == LUNA
    assert response.json()["generation"]["gen_model_http"] == raw.get("generation", {}).get("gen_model_http", "")
    assert (await postgres.get_corpus_config_json(corpus_id))["generation"]["gen_model"] == LUNA


async def test_corpus_reset_uses_current_production_generation_default(
    client: AsyncClient, generation_scope: tuple[str, PostgresClient],
) -> None:
    corpus_id, postgres = generation_scope
    params = {"corpus_id": corpus_id}
    changed = await client.patch("/api/config/generation", params=params, json={"gen_model": SOL})
    assert changed.status_code == 200, changed.text
    reset = await client.post("/api/config/reset", params=params)
    assert reset.status_code == 200, reset.text
    assert reset.json()["generation"]["gen_model"] == LUNA
    get_config_store().clear_cache()
    assert (await client.get("/api/config", params=params)).json()["generation"]["gen_model"] == LUNA
    assert (await postgres.get_corpus_config_json(corpus_id))["generation"]["gen_model"] == LUNA


async def test_rejected_alias_leaves_persisted_settings_unchanged(
    client: AsyncClient, generation_scope: tuple[str, PostgresClient],
) -> None:
    corpus_id, postgres = generation_scope
    params = {"corpus_id": corpus_id}
    baseline = await client.get("/api/config", params=params)
    assert baseline.status_code == 200, baseline.text
    stored_before = await postgres.get_corpus_config_json(corpus_id)
    payload = baseline.json()
    payload["generation"]["gen_model_http"] = "openai/gpt-6-luna"
    rejected = await client.put("/api/config", params=params, json=payload)
    assert rejected.status_code == 422, rejected.text
    assert "gen_model_http" in str(rejected.json()["detail"])
    assert await postgres.get_corpus_config_json(corpus_id) == stored_before
    get_config_store().clear_cache()
    assert (await client.get("/api/config", params=params)).json() == baseline.json()


async def test_generation_unlock_preserves_other_deployment_owned_settings(
    client: AsyncClient, generation_scope: tuple[str, PostgresClient],
) -> None:
    corpus_id, postgres = generation_scope
    params = {"corpus_id": corpus_id}
    global_response = await client.get("/api/config")
    assert global_response.status_code == 200, global_response.text
    global_payload = global_response.json()
    payload = global_response.json()
    payload["generation"]["gen_model"] = "z-ai.glm-5.3-flash"
    payload["generation"]["enrich_model"] = "z-ai.glm-5.3-flash"
    payload["chat"]["max_tokens"] = 4096
    payload["chat"]["litellm"]["default_model"] = SOL
    payload["ui"]["chat_default_model"] = SOL
    payload["chat"]["web"]["max_results"] = 1
    payload["synthetic"]["generator"]["max_tokens"] = 4096
    payload["ui"]["grafana_base_url"] = "https://grafana.ragweld.com"
    payload["tracing"]["langfuse_public_base_url"] = "https://langfuse.ragweld.com"
    payload["tracing"]["faro_base_url"] = "https://me.ragweld.com/faro/collect"
    payload["tracing"]["trace_store_path"] = ""
    payload["training"]["ragweld_agent_flyte_console_base_url"] = "https://flyte.ragweld.com"
    payload["training"]["ragweld_agent_mlflow_console_base_url"] = "https://mlflow.ragweld.com"
    payload["evaluation"]["ragas_judge_model"] = "z-ai.glm-5.3-flash"
    payload["evaluation"]["promptfoo_grader_model"] = "z-ai.glm-5.3-flash"
    payload["chat"]["temperature"] = 1.7
    await postgres.upsert_corpus_config_json(corpus_id, payload)
    get_config_store().clear_cache(corpus_id)

    response = await client.get("/api/config", params=params)
    assert response.status_code == 200, response.text
    actual = response.json()
    assert actual["generation"]["gen_model"] == "z-ai.glm-5.3-flash"
    assert actual["chat"]["temperature"] == 1.7
    for section, field in (
        ("generation", "enrich_model"), ("chat", "max_tokens"),
        ("ui", "chat_default_model"), ("chat", "litellm"), ("chat", "web"),
        ("synthetic", "generator"), ("ui", "grafana_base_url"),
        ("tracing", "langfuse_public_base_url"), ("tracing", "faro_base_url"),
        ("tracing", "trace_store_path"), ("training", "ragweld_agent_flyte_console_base_url"),
        ("training", "ragweld_agent_mlflow_console_base_url"),
        ("evaluation", "ragas_judge_model"), ("evaluation", "promptfoo_grader_model"),
    ):
        assert actual[section][field] == global_payload[section][field]
    persisted = await postgres.get_corpus_config_json(corpus_id)
    assert persisted is not None
    assert public_payload(TriBridConfig.model_validate(persisted)) == actual
