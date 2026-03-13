from __future__ import annotations

import json
from pathlib import Path

from server.runtime_capabilities import (
    SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS,
    SUPPORTED_RERANKER_CLOUD_PROVIDERS,
    SUPPORTED_CHUNKING_STRATEGIES,
    build_runtime_capabilities_response,
    validate_catalog_selection_metadata,
)


def test_runtime_capabilities_response_matches_backend_constants() -> None:
    response = build_runtime_capabilities_response()

    assert {item.provider for item in response.embedding.providers} == SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS
    assert {item.id for item in response.reranker.cloud_providers} == SUPPORTED_RERANKER_CLOUD_PROVIDERS
    assert {item.id for item in response.chunking.strategies} == SUPPORTED_CHUNKING_STRATEGIES


def test_repo_catalog_selection_metadata_matches_runtime_rules() -> None:
    catalog_path = Path(__file__).resolve().parents[2] / "data" / "models.json"
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows = raw.get("models")
    assert isinstance(rows, list)
    models = [row for row in rows if isinstance(row, dict)]

    errors = validate_catalog_selection_metadata(models)
    assert not errors
