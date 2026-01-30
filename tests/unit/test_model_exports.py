"""Tests for model re-exports from THE LAW.

Verifies that all model files correctly re-export from tribrid_config_model.py
and backward compatibility aliases work.
"""

import pytest


class TestEvalModelExports:
    """Test eval.py re-exports from THE LAW."""

    def test_imports_from_eval_module(self) -> None:
        """Test all exports are available from server.models.eval."""
        from server.models.eval import (
            EvalComparisonResult,
            EvalDatasetItem,
            EvalMetrics,
            EvalRequest,
            EvalResult,
            EvalRun,
        )

        # All should be classes
        assert callable(EvalDatasetItem)
        assert callable(EvalRequest)
        assert callable(EvalMetrics)
        assert callable(EvalResult)
        assert callable(EvalRun)
        assert callable(EvalComparisonResult)

    def test_backward_compat_alias(self) -> None:
        """Test DatasetEntry alias for EvalDatasetItem."""
        from server.models.eval import DatasetEntry, EvalDatasetItem

        # Should be same class
        assert DatasetEntry is EvalDatasetItem


class TestGraphModelExports:
    """Test graph.py re-exports from THE LAW."""

    def test_imports_from_graph_module(self) -> None:
        """Test all exports are available from server.models.graph."""
        from server.models.graph import (
            Community,
            Entity,
            GraphStats,
            Relationship,
        )

        assert callable(Entity)
        assert callable(Relationship)
        assert callable(Community)
        assert callable(GraphStats)


class TestRetrievalModelExports:
    """Test retrieval.py re-exports from THE LAW."""

    def test_imports_from_retrieval_module(self) -> None:
        """Test all exports are available from server.models.retrieval."""
        from server.models.retrieval import (
            AnswerRequest,
            AnswerResponse,
            ChunkMatch,
            SearchRequest,
            SearchResponse,
        )

        assert callable(ChunkMatch)
        assert callable(SearchRequest)
        assert callable(SearchResponse)
        assert callable(AnswerRequest)
        assert callable(AnswerResponse)


class TestChatModelExports:
    """Test chat.py re-exports from THE LAW."""

    def test_imports_from_chat_module(self) -> None:
        """Test all exports are available from server.models.chat."""
        from server.models.chat import (
            ChatRequest,
            ChatResponse,
            Message,
        )

        assert callable(Message)
        assert callable(ChatRequest)
        assert callable(ChatResponse)


class TestIndexModelExports:
    """Test index.py re-exports from THE LAW."""

    def test_imports_from_index_module(self) -> None:
        """Test all exports are available from server.models.index."""
        from server.models.index import (
            Chunk,
            IndexRequest,
            IndexStats,
            IndexStatus,
        )

        assert callable(Chunk)
        assert callable(IndexRequest)
        assert callable(IndexStatus)
        assert callable(IndexStats)


class TestModelsInitExports:
    """Test server/models/__init__.py exports all models."""

    def test_all_models_from_init(self) -> None:
        """Test all models are available from server.models."""
        from server.models import (
            # Config
            TriBridConfig,
            # Chunk/Retrieval
            Chunk,
            ChunkMatch,
            SearchRequest,
            SearchResponse,
            AnswerRequest,
            AnswerResponse,
            # Index
            IndexRequest,
            IndexStatus,
            IndexStats,
            # Chat
            Message,
            ChatRequest,
            ChatResponse,
            # Graph
            Entity,
            Relationship,
            Community,
            GraphStats,
            # Eval
            EvalDatasetItem,
            EvalRequest,
            EvalMetrics,
            EvalResult,
            EvalRun,
            EvalComparisonResult,
        )

        # Verify all are importable (no ImportError)
        assert TriBridConfig is not None
        assert Chunk is not None
        assert ChunkMatch is not None
        assert Entity is not None
        assert EvalDatasetItem is not None


class TestTypesMatchTheLaw:
    """Test that exported types match THE LAW definitions."""

    def test_types_are_same_class(self) -> None:
        """Verify re-exported types are the exact same class from THE LAW."""
        from server.models.tribrid_config_model import (
            ChunkMatch as LawChunkMatch,
            Entity as LawEntity,
            EvalDatasetItem as LawEvalDatasetItem,
        )
        from server.models.eval import EvalDatasetItem
        from server.models.graph import Entity
        from server.models.retrieval import ChunkMatch

        # Should be exact same class, not copies
        assert ChunkMatch is LawChunkMatch
        assert Entity is LawEntity
        assert EvalDatasetItem is LawEvalDatasetItem
