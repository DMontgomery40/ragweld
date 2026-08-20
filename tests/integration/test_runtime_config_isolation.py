from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.config import DEFAULT_CONFIG_PATH, load_config


@pytest.mark.requires_postgres
@pytest.mark.requires_neo4j
def test_strict_integration_app_uses_disposable_service_bindings() -> None:
    config = load_config()

    assert DEFAULT_CONFIG_PATH.is_absolute()
    assert DEFAULT_CONFIG_PATH.resolve() != Path(os.environ["RAGWELD_SOURCE_CONFIG_PATH"]).resolve()
    assert DEFAULT_CONFIG_PATH.parent.resolve() == Path(os.environ["RAGWELD_INTEGRATION_RUNTIME_DIR"]).resolve()
    assert config.indexing.postgres_url == os.environ["POSTGRES_DSN"]
    assert config.graph_storage.neo4j_uri == os.environ["NEO4J_URI"]


@pytest.mark.requires_postgres
@pytest.mark.requires_neo4j
@pytest.mark.asyncio
async def test_global_config_api_writes_only_private_runtime_copy(client: AsyncClient) -> None:
    source_path = Path(os.environ["RAGWELD_SOURCE_CONFIG_PATH"]).resolve()
    runtime_path = DEFAULT_CONFIG_PATH.resolve()
    source_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    response = await client.get("/api/config")
    assert response.status_code == 200, response.text
    payload = response.json()
    current_max = int(payload["ui"]["chat_history_max"])
    payload["ui"]["chat_history_max"] = 49 if current_max == 50 else 50

    saved = await client.put("/api/config", json=payload)
    assert saved.status_code == 200, saved.text
    assert int(saved.json()["ui"]["chat_history_max"]) != current_max
    assert runtime_path.exists()
    persisted = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert persisted["ui"]["chat_history_max"] == payload["ui"]["chat_history_max"]
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_before
