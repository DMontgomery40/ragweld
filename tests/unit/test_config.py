"""Tests for configuration models - using THE LAW (tribrid_config_model.py)."""

import pytest
from pydantic import ValidationError

from server.models.tribrid_config_model import (
    EmbeddingConfig,
    FusionConfig,
    GraphIndexingConfig,
    EvaluationConfig,
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
    # LAW's valid modes: cloud, local, learning, none
    for mode in ["none", "local", "learning", "cloud"]:
        config = RerankingConfig(reranker_mode=mode)
        assert config.reranker_mode == mode


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
    assert cfg.semantic_kg_relation_weight_llm == 0.7
    assert cfg.semantic_kg_relation_weight_heuristic == 0.5


def test_graph_indexing_config_weight_validation() -> None:
    with pytest.raises(ValidationError):
        GraphIndexingConfig(ast_contains_weight=-0.01)
    with pytest.raises(ValidationError):
        GraphIndexingConfig(ast_inherits_weight=1.01)


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
