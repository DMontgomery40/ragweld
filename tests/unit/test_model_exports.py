"""Tests for focused model re-exports from the boundary-model aggregate.

Verifies that all model files correctly re-export from tribrid_config_model.py
and backward compatibility aliases work.
"""

class TestEvalModelExports:
    """Test eval.py re-exports from the boundary-model aggregate."""

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
    """Test graph.py re-exports from the boundary-model aggregate."""

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
    """Test retrieval.py re-exports from the boundary-model aggregate."""

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
    """Test chat.py re-exports from the boundary-model aggregate."""

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
    """Test index.py re-exports from the boundary-model aggregate."""

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


class TestTypesMatchBoundaryAggregate:
    """Test that focused exports preserve boundary-model identity."""

    def test_types_are_same_class(self) -> None:
        """Verify re-exported types are the exact same boundary class."""
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
