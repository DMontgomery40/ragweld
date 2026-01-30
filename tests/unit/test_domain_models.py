"""Tests for domain models consolidated in THE LAW (tribrid_config_model.py).

Tests cover:
- Chunk and retrieval models (ChunkMatch, SearchRequest, SearchResponse)
- Graph models (Entity, Relationship, Community, GraphStats)
- Eval models (EvalDatasetItem, EvalRequest, EvalMetrics, EvalResult, EvalRun)
- Chat models (Message, ChatRequest, ChatResponse)
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from server.models.tribrid_config_model import (
    # Chunk/Retrieval models
    Chunk,
    ChunkMatch,
    SearchRequest,
    SearchResponse,
    AnswerRequest,
    AnswerResponse,
    # Index models
    IndexRequest,
    IndexStatus,
    IndexStats,
    # Graph models
    Entity,
    Relationship,
    Community,
    GraphStats,
    # Eval models
    EvalDatasetItem,
    EvalRequest,
    EvalMetrics,
    EvalResult,
    EvalRun,
    EvalComparisonResult,
    # Chat models
    Message,
    ChatRequest,
    ChatResponse,
    # Config for EvalRun
    TriBridConfig,
)


# ============================================================================
# Chunk/Retrieval Models
# ============================================================================

class TestChunk:
    """Tests for Chunk model."""

    def test_chunk_required_fields(self) -> None:
        """Test Chunk with required fields."""
        chunk = Chunk(
            chunk_id="chunk_001",
            content="def hello(): pass",
            file_path="/src/main.py",
            start_line=1,
            end_line=2,
        )
        assert chunk.chunk_id == "chunk_001"
        assert chunk.content == "def hello(): pass"
        assert chunk.language is None  # optional

    def test_chunk_with_all_fields(self) -> None:
        """Test Chunk with all optional fields."""
        chunk = Chunk(
            chunk_id="chunk_002",
            content="class Foo: pass",
            file_path="/src/foo.py",
            start_line=10,
            end_line=15,
            language="python",
            token_count=25,
            summary="A Foo class definition",
        )
        assert chunk.language == "python"
        assert chunk.token_count == 25
        assert chunk.summary == "A Foo class definition"


class TestChunkMatch:
    """Tests for ChunkMatch model - unified retrieval result shape."""

    def test_chunk_match_vector_source(self) -> None:
        """Test ChunkMatch with vector source."""
        match = ChunkMatch(
            chunk_id="chunk_001",
            content="Vector search result",
            file_path="/src/search.py",
            start_line=1,
            end_line=5,
            score=0.95,
            source="vector",
        )
        assert match.source == "vector"
        assert match.score == 0.95

    def test_chunk_match_sparse_source(self) -> None:
        """Test ChunkMatch with sparse (BM25) source."""
        match = ChunkMatch(
            chunk_id="chunk_002",
            content="BM25 result",
            file_path="/src/bm25.py",
            start_line=10,
            end_line=15,
            score=12.5,
            source="sparse",
        )
        assert match.source == "sparse"

    def test_chunk_match_graph_source(self) -> None:
        """Test ChunkMatch with graph source."""
        match = ChunkMatch(
            chunk_id="chunk_003",
            content="Graph traversal result",
            file_path="/src/graph.py",
            start_line=20,
            end_line=25,
            score=0.8,
            source="graph",
        )
        assert match.source == "graph"

    def test_chunk_match_invalid_source(self) -> None:
        """Test ChunkMatch rejects invalid source."""
        with pytest.raises(ValidationError) as exc_info:
            ChunkMatch(
                chunk_id="chunk_004",
                content="Invalid",
                file_path="/src/bad.py",
                start_line=1,
                end_line=2,
                score=0.5,
                source="invalid_source",  # type: ignore
            )
        assert "source" in str(exc_info.value)


class TestSearchModels:
    """Tests for SearchRequest and SearchResponse."""

    def test_search_request_defaults(self) -> None:
        """Test SearchRequest with defaults."""
        req = SearchRequest(query="find auth", repo_id="tribrid")
        assert req.top_k == 20
        assert req.include_vector is True
        assert req.include_sparse is True
        assert req.include_graph is True

    def test_search_request_selective_sources(self) -> None:
        """Test SearchRequest with selective sources."""
        req = SearchRequest(
            query="find class",
            repo_id="tribrid",
            include_vector=True,
            include_sparse=False,
            include_graph=False,
        )
        assert req.include_vector is True
        assert req.include_sparse is False
        assert req.include_graph is False

    def test_search_response(self) -> None:
        """Test SearchResponse with matches."""
        match = ChunkMatch(
            chunk_id="c1",
            content="Found it",
            file_path="/f.py",
            start_line=1,
            end_line=2,
            score=0.9,
            source="vector",
        )
        resp = SearchResponse(
            query="test query",
            matches=[match],
            fusion_method="rrf",
            reranker_mode="local",
            latency_ms=42.5,
        )
        assert len(resp.matches) == 1
        assert resp.latency_ms == 42.5


# ============================================================================
# Graph Models
# ============================================================================

class TestEntity:
    """Tests for Entity model - knowledge graph node."""

    def test_entity_function(self) -> None:
        """Test Entity with function type."""
        entity = Entity(
            entity_id="ent_001",
            name="process_data",
            entity_type="function",
            file_path="/src/processor.py",
            description="Processes input data",
        )
        assert entity.entity_type == "function"
        assert entity.name == "process_data"

    def test_entity_class(self) -> None:
        """Test Entity with class type."""
        entity = Entity(
            entity_id="ent_002",
            name="DataProcessor",
            entity_type="class",
            file_path="/src/processor.py",
        )
        assert entity.entity_type == "class"

    def test_entity_invalid_type(self) -> None:
        """Test Entity rejects invalid type."""
        with pytest.raises(ValidationError) as exc_info:
            Entity(
                entity_id="ent_003",
                name="InvalidType",
                entity_type="invalid",  # type: ignore
            )
        assert "entity_type" in str(exc_info.value)

    def test_entity_all_types(self) -> None:
        """Test all valid entity types."""
        for etype in ["function", "class", "module", "variable", "concept"]:
            entity = Entity(
                entity_id=f"ent_{etype}",
                name=f"Test{etype}",
                entity_type=etype,  # type: ignore
            )
            assert entity.entity_type == etype


class TestRelationship:
    """Tests for Relationship model - knowledge graph edge."""

    def test_relationship_calls(self) -> None:
        """Test Relationship with calls type."""
        rel = Relationship(
            source_id="ent_001",
            target_id="ent_002",
            relation_type="calls",
        )
        assert rel.relation_type == "calls"
        assert rel.weight == 1.0  # default

    def test_relationship_with_weight(self) -> None:
        """Test Relationship with custom weight."""
        rel = Relationship(
            source_id="ent_001",
            target_id="ent_002",
            relation_type="imports",
            weight=0.8,
        )
        assert rel.weight == 0.8

    def test_relationship_all_types(self) -> None:
        """Test all valid relationship types."""
        for rtype in ["calls", "imports", "inherits", "contains", "references", "related_to"]:
            rel = Relationship(
                source_id="src",
                target_id="tgt",
                relation_type=rtype,  # type: ignore
            )
            assert rel.relation_type == rtype


class TestCommunity:
    """Tests for Community model - graph cluster."""

    def test_community(self) -> None:
        """Test Community model."""
        community = Community(
            community_id="comm_001",
            name="Authentication Module",
            summary="Handles user authentication and session management",
            member_ids=["ent_001", "ent_002", "ent_003"],
            level=1,
        )
        assert len(community.member_ids) == 3
        assert community.level == 1


class TestGraphStats:
    """Tests for GraphStats model."""

    def test_graph_stats(self) -> None:
        """Test GraphStats model."""
        stats = GraphStats(
            repo_id="tribrid",
            total_entities=150,
            total_relationships=420,
            total_communities=12,
            entity_breakdown={"function": 100, "class": 30, "module": 20},
            relationship_breakdown={"calls": 200, "imports": 150, "contains": 70},
        )
        assert stats.total_entities == 150
        assert stats.entity_breakdown["function"] == 100


# ============================================================================
# Eval Models
# ============================================================================

class TestEvalDatasetItem:
    """Tests for EvalDatasetItem (renamed from DatasetEntry)."""

    def test_eval_dataset_item(self) -> None:
        """Test EvalDatasetItem model."""
        item = EvalDatasetItem(
            entry_id="q_001",
            question="How does authentication work?",
            expected_chunks=["chunk_auth_001", "chunk_auth_002"],
            expected_answer="Authentication uses JWT tokens...",
            tags=["auth", "security"],
            created_at=datetime.now(timezone.utc),
        )
        assert item.question == "How does authentication work?"
        assert len(item.expected_chunks) == 2
        assert "auth" in item.tags

    def test_eval_dataset_item_minimal(self) -> None:
        """Test EvalDatasetItem with only required fields."""
        item = EvalDatasetItem(
            entry_id="q_002",
            question="What is RAG?",
            expected_chunks=["chunk_rag_001"],
            created_at=datetime.now(timezone.utc),
        )
        assert item.expected_answer is None
        assert item.tags == []


class TestEvalMetrics:
    """Tests for EvalMetrics model."""

    def test_eval_metrics(self) -> None:
        """Test EvalMetrics model."""
        metrics = EvalMetrics(
            mrr=0.85,
            recall_at_5=0.7,
            recall_at_10=0.85,
            recall_at_20=0.95,
            precision_at_5=0.6,
            ndcg_at_10=0.78,
            latency_p50_ms=45.0,
            latency_p95_ms=120.0,
        )
        assert metrics.mrr == 0.85
        assert metrics.latency_p95_ms == 120.0


class TestEvalResult:
    """Tests for EvalResult model - per-entry result."""

    def test_eval_result(self) -> None:
        """Test EvalResult model."""
        result = EvalResult(
            entry_id="q_001",
            question="How does auth work?",
            retrieved_chunks=["chunk_001", "chunk_002", "chunk_003"],
            expected_chunks=["chunk_001", "chunk_004"],
            reciprocal_rank=1.0,
            recall=0.5,
            latency_ms=42.0,
        )
        assert result.reciprocal_rank == 1.0
        assert len(result.retrieved_chunks) == 3


class TestEvalRun:
    """Tests for EvalRun model - complete eval run."""

    def test_eval_run(self) -> None:
        """Test EvalRun model."""
        config = TriBridConfig()
        metrics = EvalMetrics(
            mrr=0.85,
            recall_at_5=0.7,
            recall_at_10=0.85,
            recall_at_20=0.95,
            precision_at_5=0.6,
            ndcg_at_10=0.78,
            latency_p50_ms=45.0,
            latency_p95_ms=120.0,
        )
        result = EvalResult(
            entry_id="q_001",
            question="Test?",
            retrieved_chunks=["c1"],
            expected_chunks=["c1"],
            reciprocal_rank=1.0,
            recall=1.0,
            latency_ms=30.0,
        )
        run = EvalRun(
            run_id="run_001",
            repo_id="tribrid",
            dataset_id="golden_v1",
            config_snapshot=config.model_dump(),
            metrics=metrics,
            results=[result],
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        assert run.run_id == "run_001"
        assert len(run.results) == 1
        assert run.metrics.mrr == 0.85


class TestEvalComparisonResult:
    """Tests for EvalComparisonResult model."""

    def test_eval_comparison(self) -> None:
        """Test EvalComparisonResult model."""
        baseline = EvalMetrics(
            mrr=0.75,
            recall_at_5=0.6,
            recall_at_10=0.75,
            recall_at_20=0.85,
            precision_at_5=0.5,
            ndcg_at_10=0.68,
            latency_p50_ms=50.0,
            latency_p95_ms=130.0,
        )
        current = EvalMetrics(
            mrr=0.85,
            recall_at_5=0.7,
            recall_at_10=0.85,
            recall_at_20=0.95,
            precision_at_5=0.6,
            ndcg_at_10=0.78,
            latency_p50_ms=45.0,
            latency_p95_ms=120.0,
        )
        comparison = EvalComparisonResult(
            baseline_run_id="run_001",
            current_run_id="run_002",
            baseline_metrics=baseline,
            current_metrics=current,
            delta_mrr=0.10,
            delta_recall_at_10=0.10,
            improved_entries=["q_001", "q_003"],
            degraded_entries=["q_002"],
        )
        assert comparison.delta_mrr == 0.10
        assert len(comparison.improved_entries) == 2


# ============================================================================
# Chat Models
# ============================================================================

class TestMessage:
    """Tests for Message model."""

    def test_message_user(self) -> None:
        """Test Message with user role."""
        msg = Message(role="user", content="Hello!")
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_message_assistant(self) -> None:
        """Test Message with assistant role."""
        msg = Message(role="assistant", content="Hi there!")
        assert msg.role == "assistant"

    def test_message_system(self) -> None:
        """Test Message with system role."""
        msg = Message(role="system", content="You are a helpful assistant.")
        assert msg.role == "system"

    def test_message_invalid_role(self) -> None:
        """Test Message rejects invalid role."""
        with pytest.raises(ValidationError):
            Message(role="invalid", content="Test")  # type: ignore


class TestChatModels:
    """Tests for ChatRequest and ChatResponse."""

    def test_chat_request(self) -> None:
        """Test ChatRequest model."""
        req = ChatRequest(
            message="Explain authentication",
            repo_id="tribrid",
            conversation_id="conv_001",
            stream=True,
        )
        assert req.message == "Explain authentication"
        assert req.stream is True

    def test_chat_request_defaults(self) -> None:
        """Test ChatRequest with defaults."""
        req = ChatRequest(message="Hello", repo_id="tribrid")
        assert req.conversation_id is None
        assert req.stream is False

    def test_chat_response(self) -> None:
        """Test ChatResponse model."""
        msg = Message(role="assistant", content="Here's the explanation...")
        source = ChunkMatch(
            chunk_id="c1",
            content="Auth code here",
            file_path="/src/auth.py",
            start_line=1,
            end_line=10,
            score=0.9,
            source="vector",
        )
        resp = ChatResponse(
            conversation_id="conv_001",
            message=msg,
            sources=[source],
            tokens_used=150,
        )
        assert resp.tokens_used == 150
        assert len(resp.sources) == 1


# ============================================================================
# Index Models
# ============================================================================

class TestIndexModels:
    """Tests for IndexRequest, IndexStatus, IndexStats."""

    def test_index_request(self) -> None:
        """Test IndexRequest model."""
        req = IndexRequest(
            repo_id="tribrid",
            repo_path="/path/to/repo",
            force_reindex=True,
        )
        assert req.force_reindex is True

    def test_index_status_idle(self) -> None:
        """Test IndexStatus with idle status."""
        status = IndexStatus(
            repo_id="tribrid",
            status="idle",
            progress=0.0,
        )
        assert status.status == "idle"

    def test_index_status_indexing(self) -> None:
        """Test IndexStatus with indexing status."""
        status = IndexStatus(
            repo_id="tribrid",
            status="indexing",
            progress=0.5,
            current_file="/src/main.py",
        )
        assert status.progress == 0.5
        assert status.current_file == "/src/main.py"

    def test_index_stats(self) -> None:
        """Test IndexStats model."""
        stats = IndexStats(
            repo_id="tribrid",
            total_files=100,
            total_chunks=1500,
            total_tokens=50000,
            embedding_model="text-embedding-3-large",
            embedding_dimensions=3072,
            file_breakdown={".py": 80, ".ts": 20},
            last_indexed=datetime.now(timezone.utc),
        )
        assert stats.total_chunks == 1500
        assert stats.file_breakdown[".py"] == 80
        assert stats.embedding_model == "text-embedding-3-large"
