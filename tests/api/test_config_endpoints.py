"""API tests for config endpoints."""

import asyncio
import json

import pytest
from httpx import AsyncClient

from server.models.tribrid_config_model import TriBridConfig
from server.services.config_store import get_config as load_scoped_config


@pytest.mark.asyncio
async def test_get_config(client: AsyncClient) -> None:
    """Test GET /api/config endpoint."""
    response = await client.get("/api/config")
    assert response.status_code == 200

    data = response.json()
    # Check for LAW's field names (from tribrid_config_model.py)
    assert "embedding" in data
    assert "fusion" in data
    assert "reranking" in data  # LAW uses 'reranking' not 'reranker'
    assert "chunking" in data   # LAW uses 'chunking' not 'chunker'
    assert "retrieval" in data
    assert "scoring" in data
    for removed_key in {
        "semantic_kg_enabled",
        "semantic_kg_mode",
        "semantic_kg_typed_entities_enabled",
        "semantic_kg_require_llm_success",
        "semantic_kg_relation_weight_llm",
        "semantic_kg_relation_weight_heuristic",
        "semantic_kg_max_concepts_per_chunk",
        "semantic_kg_min_concept_len",
        "semantic_kg_max_relations_per_chunk",
        "semantic_kg_allowed_entity_types",
        "semantic_kg_allowed_relation_types",
    }:
        assert removed_key not in data["graph_indexing"]
    assert data["graph_indexing"]["semantic_kg_max_chunks"] == 40000


@pytest.mark.asyncio
async def test_patch_graph_indexing_ignores_removed_semantic_toggle_and_preserves_schema_defaults(
    client: AsyncClient,
) -> None:
    response = await client.patch(
        "/api/config/graph_indexing",
        json={"semantic_kg_enabled": True},
    )
    assert response.status_code == 200

    graph_indexing = response.json()["graph_indexing"]
    assert "semantic_kg_enabled" not in graph_indexing
    assert "semantic_kg_mode" not in graph_indexing
    assert "semantic_kg_typed_entities_enabled" not in graph_indexing
    assert "semantic_kg_allowed_entity_types" not in graph_indexing
    assert "semantic_kg_allowed_relation_types" not in graph_indexing
    assert graph_indexing["semantic_kg_max_chunks"] == 40000


@pytest.mark.asyncio
async def test_update_config(client: AsyncClient, test_config: TriBridConfig) -> None:
    """Test PUT /api/config endpoint."""
    response = await client.put("/api/config", json=test_config.model_dump())
    assert response.status_code == 200

    data = response.json()
    # LAW's EmbeddingConfig uses 'embedding_type' not 'provider'
    assert data["embedding"]["embedding_type"] == test_config.embedding.embedding_type


@pytest.mark.asyncio
async def test_update_config_section(client: AsyncClient) -> None:
    """Test PATCH /api/config/{section} endpoint."""
    updates = {"top_k": 30}
    response = await client.patch("/api/config/vector_search", json=updates)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_nested_config_section_preserves_siblings(client: AsyncClient) -> None:
    """Nested PATCH payloads must not reset sibling keys back to defaults."""
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["chat"]["multimodal"]["image_detail"] = "high"
    cfg["chat"]["multimodal"]["max_images_per_message"] = 7
    saved = await client.put("/api/config", json=cfg)
    assert saved.status_code == 200

    response = await client.patch(
        "/api/config/chat",
        json={"multimodal": {"vision_enabled": False}},
    )
    assert response.status_code == 200

    multimodal = response.json()["chat"]["multimodal"]
    assert multimodal["vision_enabled"] is False
    assert multimodal["image_detail"] == "high"
    assert multimodal["max_images_per_message"] == 7


@pytest.mark.asyncio
async def test_put_config_persists_hard_cut_observability_fields(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["tracing"]["tracing_mode"] = "otel_langfuse"
    cfg["tracing"]["otel_export_enabled"] = True
    cfg["tracing"]["otlp_endpoint"] = "http://localhost:4318/v1/traces"
    cfg["tracing"]["otlp_headers"] = "Authorization=Bearer test"
    cfg["tracing"]["otel_service_name"] = "ragweld-api-test"
    cfg["tracing"]["langfuse_enabled"] = True
    cfg["tracing"]["langfuse_base_url"] = "http://localhost:3005"
    cfg["tracing"]["langfuse_project"] = "ragweld-test"
    cfg["tracing"]["tempo_base_url"] = "http://localhost:3200"
    cfg["tracing"]["alloy_base_url"] = "http://localhost:12345"
    cfg["tracing"]["cost_tracking_enabled"] = True

    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 200

    tracing = response.json()["tracing"]
    assert tracing["tracing_mode"] == "otel_langfuse"
    assert tracing["otel_export_enabled"] is True
    assert tracing["otlp_endpoint"] == "http://localhost:4318/v1/traces"
    assert tracing["otel_service_name"] == "ragweld-api-test"
    assert tracing["langfuse_enabled"] is True
    assert tracing["langfuse_base_url"] == "http://localhost:3005"
    assert tracing["langfuse_project"] == "ragweld-test"
    assert tracing["tempo_base_url"] == "http://localhost:3200"
    assert tracing["alloy_base_url"] == "http://localhost:12345"
    assert tracing["cost_tracking_enabled"] is True

    # The authorization header is a credential and never comes back on the wire; the
    # response carries the marker while the real value is on disk (see
    # tests/api/test_config_redaction.py for the full round trip).
    assert tracing["otlp_headers"] == "Authorization=[redacted]"
    stored = await load_scoped_config(repo_id=None)
    assert stored.tracing.otlp_headers == "Authorization=Bearer test"


@pytest.mark.asyncio
async def test_reset_config(client: AsyncClient) -> None:
    """Test POST /api/config/reset endpoint."""
    response = await client.post("/api/config/reset")
    assert response.status_code == 200

    data = response.json()
    # Should return default config
    assert "embedding" in data
    assert data["tracing"]["langfuse_public_base_url"] == "http://127.0.0.1:53000"
    assert data["training"]["ragweld_agent_mlflow_console_base_url"] == "http://127.0.0.1:55500"


@pytest.mark.asyncio
async def test_invalid_config_section(client: AsyncClient) -> None:
    """Test updating invalid config section."""
    response = await client.patch("/api/config/invalid_section", json={})
    assert response.status_code in [400, 404, 422]


@pytest.mark.asyncio
async def test_patch_validation_error_detail_is_field_parseable(client: AsyncClient) -> None:
    """A rejected value PATCH returns a 422 whose ``detail`` is the string dump the GUI's shared
    error formatter parses into per-field messages (GUI-drive M-20).

    ``web/src/utils/configPatchErrors.ts`` keys on an unindented dotted-path line followed by an
    indented message line ending in ``[type=...]``. If the server ever stopped emitting
    ``detail=str(ValidationError)`` for a bad value, the operator would fall back to axios's
    opaque ``Request failed with status code 422`` -- exactly the regression M-20 fixed. This
    pins the contract the client depends on.
    """
    response = await client.patch("/api/config/vector_search", json={"top_k": "not-a-number"})
    assert response.status_code == 422
    detail = response.json().get("detail")
    assert isinstance(detail, str), f"422 detail must be a string dump, got {type(detail)}"
    # The offending field name and the Pydantic type marker the parser anchors on.
    assert "top_k" in detail
    assert "[type=" in detail


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_get_config_unknown_corpus_does_not_autocreate(client: AsyncClient) -> None:
    """GET /api/config for an unknown corpus must 404 and must not create a corpus row."""
    before = await client.get("/api/corpora")
    assert before.status_code == 200
    before_ids = {c.get("corpus_id") for c in before.json() if isinstance(c, dict)}

    missing_id = "does_not_exist_corpus__should_404"
    resp = await client.get("/api/config", params={"corpus_id": missing_id})
    assert resp.status_code == 404

    after = await client.get("/api/corpora")
    assert after.status_code == 200
    after_ids = {c.get("corpus_id") for c in after.json() if isinstance(c, dict)}

    assert missing_id not in after_ids
    assert after_ids == before_ids


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_concurrent_section_patches_do_not_lose_updates(client: AsyncClient) -> None:
    """Concurrent PATCHes to different sections must not clobber each other."""
    corpus_id = "test_concurrent_config_patches"
    corpus_path = "."

    # Create corpus (idempotent across reruns)
    existing = await client.get("/api/corpora")
    assert existing.status_code == 200
    if not any(c.get("corpus_id") == corpus_id for c in existing.json() if isinstance(c, dict)):
        created = await client.post(
            "/api/corpora",
            json={"corpus_id": corpus_id, "name": corpus_id, "path": corpus_path, "description": "test corpus"},
        )
        assert created.status_code == 200

    try:
        # Seed cache + per-corpus config row.
        seeded = await client.get("/api/config", params={"corpus_id": corpus_id})
        assert seeded.status_code == 200

        # Two different sections patched concurrently should both stick.
        tokenization_patch = client.patch(
            "/api/config/tokenization",
            params={"corpus_id": corpus_id},
            json={"normalize_unicode": False},
        )
        indexing_patch = client.patch(
            "/api/config/indexing",
            params={"corpus_id": corpus_id},
            json={"large_file_mode": "read_all"},
        )

        tokenization_resp, indexing_resp = await asyncio.gather(tokenization_patch, indexing_patch)
        assert tokenization_resp.status_code == 200
        assert indexing_resp.status_code == 200

        final = await client.get("/api/config", params={"corpus_id": corpus_id})
        assert final.status_code == 200
        cfg = final.json()
        assert bool(cfg["tokenization"]["normalize_unicode"]) is False
        assert str(cfg["indexing"]["large_file_mode"]).lower() == "read_all"
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_put_config_rejects_direct_provider_id_for_generation_override(client: AsyncClient) -> None:
    """Generation config stores LiteLLM aliases, never upstream provider ids."""
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["generation"]["gen_model_mcp"] = "cohere/rerank-3.5"
    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 422

    detail = str(response.json().get("detail") or "")
    assert "generation" in detail
    assert "gen_model_mcp" in detail
    assert "LiteLLM alias" in detail


@pytest.mark.asyncio
async def test_put_config_rejects_prefixed_upstream_id_for_generation_override(client: AsyncClient) -> None:
    """A LiteLLM prefix does not turn an upstream provider id into an alias."""
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["generation"]["gen_model_mcp"] = "litellm:cohere/rerank-3.5"
    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 422

    detail = str(response.json().get("detail") or "")
    assert "generation" in detail
    assert "gen_model_mcp" in detail
    assert "LiteLLM alias" in detail


@pytest.mark.asyncio
async def test_put_config_rejects_removed_flat_generation_keys_at_root(client: AsyncClient) -> None:
    response = await client.put("/api/config", json={"GEN_BACKEND": "openai"})
    assert response.status_code == 422
    assert "GEN_BACKEND" in str(response.json())


@pytest.mark.asyncio
async def test_put_config_rejects_unsupported_embedding_provider_runtime(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["indexing"]["skip_dense"] = False
    cfg["embedding"]["embedding_backend"] = "provider"
    cfg["embedding"]["embedding_type"] = "cohere"

    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 422
    detail = str(response.json().get("detail") or "")
    assert "Unsupported embedding provider" in detail


@pytest.mark.asyncio
async def test_put_config_rejects_unsupported_reranker_cloud_provider_runtime(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["reranking"]["reranker_mode"] = "cloud"
    cfg["reranking"]["reranker_cloud_provider"] = "voyage"
    cfg["reranking"]["reranker_cloud_model"] = "rerank-2"

    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 422
    detail = str(response.json().get("detail") or "")
    # The Pydantic field pattern is the only contract: the rejection names the
    # field and the offending value, and the runtime option set matches it.
    assert "reranker_cloud_provider" in detail
    assert "voyage" in detail


@pytest.mark.asyncio
async def test_put_config_rejects_embedding_tokenizer_mismatch(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["indexing"]["skip_dense"] = False
    cfg["embedding"]["embedding_backend"] = "provider"
    cfg["embedding"]["embedding_type"] = "openai"
    cfg["tokenization"]["strategy"] = "huggingface"

    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 422
    detail = str(response.json().get("detail") or "")
    assert "requires tokenization.strategy" in detail


@pytest.mark.asyncio
async def test_put_config_rejects_unknown_tiktoken_encoding(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["indexing"]["skip_dense"] = False
    cfg["embedding"]["embedding_backend"] = "provider"
    cfg["embedding"]["embedding_type"] = "openai"
    cfg["tokenization"]["strategy"] = "tiktoken"
    cfg["tokenization"]["tiktoken_encoding"] = "definitely_not_a_real_encoding"

    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 422
    detail = str(response.json().get("detail") or "")
    assert "Unknown tiktoken encoding" in detail


@pytest.mark.asyncio
async def test_put_config_accepts_mlx_model_id_with_slash(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["indexing"]["skip_dense"] = False
    cfg["embedding"]["embedding_backend"] = "provider"
    cfg["embedding"]["embedding_type"] = "mlx"
    cfg["embedding"]["embedding_model_mlx"] = "mlx-community/all-MiniLM-L6-v2-4bit"
    cfg["embedding"]["embedding_dim"] = 384
    cfg["tokenization"]["strategy"] = "huggingface"
    cfg["tokenization"]["hf_tokenizer_name"] = "sentence-transformers/all-MiniLM-L6-v2"

    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 200
    body = response.json()
    assert str(body["embedding"]["embedding_type"]).lower() == "mlx"
    assert str(body["embedding"]["embedding_model_mlx"]) == "mlx-community/all-MiniLM-L6-v2-4bit"


@pytest.mark.asyncio
async def test_put_config_rejects_legacy_semantic_chunking_strategy(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["chunking"]["chunking_strategy"] = "semantic"

    response = await client.put("/api/config", json=cfg)
    assert response.status_code == 422
    detail = json.dumps(response.json())
    assert "chunking_strategy" in detail
    assert "semantic" in detail
