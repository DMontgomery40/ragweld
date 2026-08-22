"""Tests for validated configuration models."""

import pytest
from pydantic import ValidationError

from server.config import DEFAULT_CONFIG_PATH, load_config
from server.models.tribrid_config_model import (
    ChunkingConfig,
    EmbeddingConfig,
    EvaluationConfig,
    FusionConfig,
    GraphIndexingConfig,
    RerankingConfig,
    TriBridConfig,
)


def test_embedding_config_defaults() -> None:
    """Test embedding config with defaults."""
    config = EmbeddingConfig()
    assert config.embedding_type == "openai"  # LAW uses 'embedding_type'
    assert config.embedding_model == "text-embedding-3-large"
    assert config.embedding_dim == 3072


def test_embedding_config_custom() -> None:
    """Test embedding config with custom values."""
    config = EmbeddingConfig(
        embedding_type="voyage",
        embedding_model="voyage-code-3",
        embedding_dim=1024,
    )
    assert config.embedding_type == "voyage"
    assert config.embedding_batch_size == 64  # default


def test_fusion_config_weights() -> None:
    """Test fusion config weight validation - LAW auto-normalizes."""
    config = FusionConfig(
        method="weighted",
        vector_weight=0.5,
        sparse_weight=0.3,
        graph_weight=0.2,
        rrf_k=60,
    )
    # LAW normalizes weights to sum to 1.0
    total = config.vector_weight + config.sparse_weight + config.graph_weight
    assert abs(total - 1.0) < 0.01


def test_reranker_modes() -> None:
    """Test reranker mode options - LAW uses 'reranker_mode' not 'mode'."""
    # LAW's supported modes: cloud, learning, none (legacy aliases normalize).
    assert RerankingConfig(reranker_mode="none").reranker_mode == "none"
    assert RerankingConfig(reranker_mode="learning").reranker_mode == "learning"
    assert RerankingConfig(reranker_mode="cloud").reranker_mode == "cloud"

    # Back-compat: legacy configs used 'local'/'hf' for the old CrossEncoder path.
    assert RerankingConfig(reranker_mode="local").reranker_mode == "learning"
    assert RerankingConfig(reranker_mode="hf").reranker_mode == "learning"


def test_tribrid_config_defaults() -> None:
    """Test full TriBridConfig with defaults."""
    config = TriBridConfig()
    assert config.embedding.embedding_type == "openai"
    assert config.fusion.method == "rrf"
    assert config.reranking.reranker_mode == "none"  # LAW default
    assert config.chunking.chunking_strategy == "ast"


def test_tribrid_config_nested_access() -> None:
    """Test nested config access."""
    config = TriBridConfig()
    # Access patterns that match the component code
    assert hasattr(config, 'retrieval')
    assert hasattr(config, 'scoring')
    assert hasattr(config, 'reranking')  # LAW uses 'reranking' not 'reranker'
    assert hasattr(config, 'chunking')   # LAW uses 'chunking' not 'chunker'


def test_graph_indexing_config_weight_defaults() -> None:
    cfg = GraphIndexingConfig()
    assert cfg.ast_contains_weight == 1.0
    assert cfg.ast_inherits_weight == 1.0
    assert cfg.ast_imports_weight == 1.0
    assert cfg.ast_calls_weight == 1.0
    assert cfg.semantic_kg_mode == "llm"
    assert cfg.semantic_kg_typed_entities_enabled is True
    assert cfg.semantic_kg_allowed_entity_types == ["person", "org", "location", "event", "concept"]
    assert cfg.semantic_kg_allowed_relation_types == [
        "associated_with",
        "met_with",
        "communicated_with",
        "works_for",
        "member_of",
        "founded",
        "owns",
        "funded",
        "participated_in",
        "located_in",
        "references",
        "related_to",
    ]
    assert cfg.semantic_kg_max_chunks == 40000
    assert cfg.semantic_kg_relation_weight_llm == 0.7
    assert cfg.semantic_kg_relation_weight_heuristic == 0.5


def test_checked_in_global_config_matches_graph_branch_defaults() -> None:
    cfg = load_config(DEFAULT_CONFIG_PATH).graph_indexing
    assert cfg.semantic_kg_mode == "llm"
    assert cfg.semantic_kg_typed_entities_enabled is True
    assert cfg.semantic_kg_allowed_entity_types == ["person", "org", "location", "event", "concept"]
    assert cfg.semantic_kg_allowed_relation_types == [
        "associated_with",
        "met_with",
        "communicated_with",
        "works_for",
        "member_of",
        "founded",
        "owns",
        "funded",
        "participated_in",
        "located_in",
        "references",
        "related_to",
    ]
    assert cfg.semantic_kg_max_chunks == 40000


def test_graph_indexing_config_weight_validation() -> None:
    with pytest.raises(ValidationError):
        GraphIndexingConfig(ast_contains_weight=-0.01)
    with pytest.raises(ValidationError):
        GraphIndexingConfig(ast_inherits_weight=1.01)


def test_chunking_config_rejects_semantic_strategy() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(chunking_strategy="semantic")


def test_evaluation_config_metric_k_defaults() -> None:
    cfg = EvaluationConfig()
    assert cfg.recall_at_5_k == 5
    assert cfg.recall_at_10_k == 10
    assert cfg.recall_at_20_k == 20
    assert cfg.precision_at_5_k == 5
    assert cfg.ndcg_at_10_k == 10


def test_evaluation_config_metric_k_validation() -> None:
    with pytest.raises(ValidationError):
        EvaluationConfig(recall_at_10_k=0)
    with pytest.raises(ValidationError):
        EvaluationConfig(ndcg_at_10_k=999)


BOOLEAN_SEMANTIC_CONFIG_PATHS = (
    "chunking.preserve_imports",
    "docker.docker_logs_timestamps",
    "embedding.embedding_cache_enabled",
    "enrichment.chunk_summaries_enrich_default",
    "enrichment.enrich_code_chunks",
    "generation.enrich_disabled",
    "indexing.parquet_extract_include_column_names",
    "indexing.parquet_extract_text_columns_only",
    "indexing.skip_dense",
    "keywords.keywords_auto_generate",
    "reranking.tribrid_reranker_reload_on_change",
    "retrieval.chunk_summary_search_enabled",
    "retrieval.eval_multi",
    "retrieval.query_expansion_enabled",
    "retrieval.use_semantic_synonyms",
    "semantic_cache.bypass_if_images",
    "semantic_cache.enabled",
    "tracing.alert_include_resolved",
    "tracing.cost_tracking_enabled",
    "tracing.langfuse_enabled",
    "tracing.metrics_enabled",
    "tracing.otel_export_enabled",
    "tracing.tracing_enabled",
    "training.learning_reranker_promote_if_improves",
    "training.ragweld_agent_promote_if_improves",
    "training.tribrid_reranker_mine_reset",
    "ui.chat_show_citations",
    "ui.chat_show_confidence",
    "ui.chat_show_debug_footer",
    "ui.chat_show_trace",
    "ui.chat_stream_include_thinking",
    "ui.chat_streaming_enabled",
    "ui.editor_embed_enabled",
    "ui.editor_enabled",
    "ui.grafana_embed_enabled",
    "ui.learning_reranker_show_setup_row",
    "ui.learning_reranker_studio_immersive",
    "ui.learning_reranker_studio_v2_enabled",
    "ui.learning_reranker_visualizer_reduce_motion",
    "ui.learning_reranker_visualizer_show_vector_field",
    "ui.open_browser",
)


@pytest.mark.parametrize("path", BOOLEAN_SEMANTIC_CONFIG_PATHS)
def test_boolean_semantic_config_fields_are_declared_bool(path: str) -> None:
    """Boolean operator switches must be typed `bool` so the UI renders toggles, not spinbuttons."""
    section, field = path.split(".")
    section_model = TriBridConfig.model_fields[section].annotation
    annotation = section_model.model_fields[field].annotation
    assert annotation is bool, f"{path} is {annotation!r}, expected bool"


def test_boolean_semantic_config_fields_have_no_integer_range_bounds() -> None:
    """A 0/1 `ge`/`le` pair is the int-boolean smell this slice replaced; it must not come back."""
    offenders = []
    for path in BOOLEAN_SEMANTIC_CONFIG_PATHS:
        section, field = path.split(".")
        section_model = TriBridConfig.model_fields[section].annotation
        for meta in section_model.model_fields[field].metadata:
            if hasattr(meta, "ge") or hasattr(meta, "le"):
                offenders.append(path)
    assert offenders == []


def test_stored_config_with_integer_zero_one_loads_as_bool() -> None:
    """Operator configs persisted before the bool migration still validate into real booleans."""
    stored = {
        "tracing": {"tracing_enabled": 1, "langfuse_enabled": 0},
        "ui": {"open_browser": 0, "chat_show_citations": 1},
        "indexing": {"skip_dense": 1},
        "semantic_cache": {"enabled": 1},
    }
    cfg = TriBridConfig.model_validate(stored)

    assert cfg.tracing.tracing_enabled is True
    assert cfg.tracing.langfuse_enabled is False
    assert cfg.ui.open_browser is False
    assert cfg.ui.chat_show_citations is True
    assert cfg.indexing.skip_dense is True
    assert cfg.semantic_cache.enabled is True


def test_stored_config_with_string_zero_one_loads_as_bool() -> None:
    """Env-sourced flat values arrive as strings and must coerce to the same booleans."""
    cfg = TriBridConfig.model_validate({"tracing": {"tracing_enabled": "0", "metrics_enabled": "1"}})

    assert cfg.tracing.tracing_enabled is False
    assert cfg.tracing.metrics_enabled is True


def test_checked_in_global_config_stores_booleans_for_boolean_semantic_fields() -> None:
    """The canonical tribrid_config.json must carry real booleans, not legacy 0/1 integers."""
    import json

    raw = json.loads(DEFAULT_CONFIG_PATH.read_text())
    for path in BOOLEAN_SEMANTIC_CONFIG_PATHS:
        section, field = path.split(".")
        if section in raw and field in raw[section]:
            assert isinstance(raw[section][field], bool), f"{path} is stored as {raw[section][field]!r}"
