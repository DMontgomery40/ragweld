"""Tests for chat API endpoints with PydanticAI integration."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from server.api.chat import set_config, set_fusion
from server.main import app
from server.models.chat import Message
from server.models.tribrid_config_model import FusionConfig, TriBridConfig
from server.models.retrieval import ChunkMatch
from server.services.conversation_store import ConversationStore, get_conversation_store


@pytest.fixture
def mock_chunks() -> list[ChunkMatch]:
    """Create mock code chunks for testing."""
    return [
        ChunkMatch(
            chunk_id="chunk_1",
            content="def hello(): return 'world'",
            file_path="src/main.py",
            start_line=1,
            end_line=2,
            language="python",
            score=0.95,
            source="vector",
            metadata={},
        ),
        ChunkMatch(
            chunk_id="chunk_2",
            content="class MyClass:\n    pass",
            file_path="src/models.py",
            start_line=10,
            end_line=12,
            language="python",
            score=0.85,
            source="sparse",
            metadata={},
        ),
    ]


class MockFusion:
    """Mock fusion service for testing."""

    def __init__(self, chunks: list[ChunkMatch]):
        self.chunks = chunks
        self.search_calls: list[tuple[str, str, FusionConfig]] = []

    async def search(
        self, repo_id: str, query: str, config: FusionConfig
    ) -> list[ChunkMatch]:
        self.search_calls.append((repo_id, query, config))
        return self.chunks


@pytest.fixture
def mock_fusion(mock_chunks: list[ChunkMatch]) -> MockFusion:
    """Create mock fusion service."""
    return MockFusion(mock_chunks)


@pytest_asyncio.fixture
async def chat_client(
    test_config: TriBridConfig, mock_fusion: MockFusion
) -> AsyncClient:
    """Create test client with mocked dependencies."""
    # Set up mocked dependencies
    set_config(test_config)
    set_fusion(mock_fusion)

    # Reset conversation store
    store = get_conversation_store()
    store._conversations.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up
    set_config(None)
    set_fusion(None)


class TestConversationStore:
    """Tests for ConversationStore service."""

    def test_get_or_create_new(self):
        """Test creating a new conversation."""
        store = ConversationStore()
        conv = store.get_or_create(None)

        assert conv.id is not None
        assert len(conv.messages) == 0
        assert conv.last_provider_response_id is None

    def test_get_or_create_existing(self):
        """Test getting an existing conversation."""
        store = ConversationStore()
        conv1 = store.get_or_create("test-id")
        conv2 = store.get_or_create("test-id")

        assert conv1.id == conv2.id
        assert conv1 is conv2

    def test_add_message(self):
        """Test adding messages to a conversation."""
        store = ConversationStore()
        conv = store.get_or_create("test-id")

        msg = Message(role="user", content="Hello")
        store.add_message("test-id", msg, None)

        assert len(conv.messages) == 1
        assert conv.messages[0].content == "Hello"

    def test_add_message_with_provider_id(self):
        """Test adding message with provider response ID."""
        store = ConversationStore()
        conv = store.get_or_create("test-id")

        msg = Message(role="assistant", content="Hi there")
        store.add_message("test-id", msg, "resp_abc123")

        assert conv.last_provider_response_id == "resp_abc123"

    def test_get_messages(self):
        """Test retrieving conversation messages."""
        store = ConversationStore()
        store.get_or_create("test-id")

        store.add_message("test-id", Message(role="user", content="Hello"), None)
        store.add_message("test-id", Message(role="assistant", content="Hi"), None)

        messages = store.get_messages("test-id")
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_get_messages_nonexistent(self):
        """Test getting messages from nonexistent conversation."""
        store = ConversationStore()
        messages = store.get_messages("nonexistent")
        assert messages == []

    def test_clear_conversation(self):
        """Test clearing a conversation."""
        store = ConversationStore()
        store.get_or_create("test-id")
        store.add_message("test-id", Message(role="user", content="Hello"), None)

        result = store.clear("test-id")
        assert result is True
        assert store.get("test-id") is None

    def test_clear_nonexistent(self):
        """Test clearing nonexistent conversation."""
        store = ConversationStore()
        result = store.clear("nonexistent")
        assert result is False


class TestChatHistoryEndpoints:
    """Tests for chat history endpoints (no LLM calls)."""

    @pytest.mark.asyncio
    async def test_get_history_empty(self, chat_client: AsyncClient):
        """Test getting history for conversation with no messages."""
        # First create a conversation
        store = get_conversation_store()
        store.get_or_create("test-conv-1")

        response = await chat_client.get("/api/chat/history/test-conv-1")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_history_with_messages(self, chat_client: AsyncClient):
        """Test getting history for conversation with messages."""
        store = get_conversation_store()
        store.get_or_create("test-conv-2")
        store.add_message("test-conv-2", Message(role="user", content="Hello"), None)
        store.add_message(
            "test-conv-2", Message(role="assistant", content="Hi there"), None
        )

        response = await chat_client.get("/api/chat/history/test-conv-2")
        assert response.status_code == 200

        messages = response.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi there"

    @pytest.mark.asyncio
    async def test_get_history_nonexistent(self, chat_client: AsyncClient):
        """Test getting history for nonexistent conversation returns empty."""
        response = await chat_client.get("/api/chat/history/nonexistent")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_clear_history(self, chat_client: AsyncClient):
        """Test clearing conversation history."""
        store = get_conversation_store()
        store.get_or_create("test-conv-3")
        store.add_message("test-conv-3", Message(role="user", content="Hello"), None)

        response = await chat_client.delete("/api/chat/history/test-conv-3")
        assert response.status_code == 200
        assert response.json()["status"] == "cleared"

        # Verify it's gone
        assert store.get("test-conv-3") is None

    @pytest.mark.asyncio
    async def test_clear_history_nonexistent(self, chat_client: AsyncClient):
        """Test clearing nonexistent conversation returns 404."""
        response = await chat_client.delete("/api/chat/history/nonexistent")
        assert response.status_code == 404


class TestChatEndpointWithMockedLLM:
    """Tests for chat endpoint with mocked PydanticAI agent."""

    @pytest.mark.asyncio
    async def test_chat_creates_conversation(self, chat_client: AsyncClient):
        """Test that chat creates a new conversation when none provided."""
        with patch("server.api.chat.generate_response") as mock_gen:
            mock_gen.return_value = ("Test response", [], "resp_123")

            response = await chat_client.post(
                "/api/chat",
                json={"message": "Hello", "repo_id": "test-repo"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "conversation_id" in data
            assert data["message"]["content"] == "Test response"
            assert data["message"]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_chat_uses_existing_conversation(self, chat_client: AsyncClient):
        """Test that chat uses provided conversation ID."""
        store = get_conversation_store()
        store.get_or_create("existing-conv")

        with patch("server.api.chat.generate_response") as mock_gen:
            mock_gen.return_value = ("Response 1", [], "resp_1")

            response = await chat_client.post(
                "/api/chat",
                json={
                    "message": "Hello",
                    "repo_id": "test-repo",
                    "conversation_id": "existing-conv",
                },
            )

            assert response.status_code == 200
            assert response.json()["conversation_id"] == "existing-conv"

    @pytest.mark.asyncio
    async def test_chat_stores_messages(self, chat_client: AsyncClient):
        """Test that chat stores user and assistant messages."""
        with patch("server.api.chat.generate_response") as mock_gen:
            mock_gen.return_value = ("Assistant says hi", [], "resp_456")

            response = await chat_client.post(
                "/api/chat",
                json={"message": "User says hello", "repo_id": "test-repo"},
            )

            conv_id = response.json()["conversation_id"]
            store = get_conversation_store()
            messages = store.get_messages(conv_id)

            assert len(messages) == 2
            assert messages[0].role == "user"
            assert messages[0].content == "User says hello"
            assert messages[1].role == "assistant"
            assert messages[1].content == "Assistant says hi"

    @pytest.mark.asyncio
    async def test_chat_returns_sources(self, chat_client: AsyncClient, mock_chunks: list[ChunkMatch]):
        """Test that chat returns sources from retrieval."""
        with patch("server.api.chat.generate_response") as mock_gen:
            mock_gen.return_value = ("Response with sources", mock_chunks, "resp_789")

            response = await chat_client.post(
                "/api/chat",
                json={"message": "How does X work?", "repo_id": "test-repo"},
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data["sources"]) == 2
            assert data["sources"][0]["file_path"] == "src/main.py"

    @pytest.mark.asyncio
    async def test_chat_handles_error(self, chat_client: AsyncClient):
        """Test that chat handles errors gracefully."""
        with patch("server.api.chat.generate_response") as mock_gen:
            mock_gen.side_effect = Exception("LLM unavailable")

            response = await chat_client.post(
                "/api/chat",
                json={"message": "Hello", "repo_id": "test-repo"},
            )

            assert response.status_code == 500
            assert "LLM unavailable" in response.json()["detail"]


class TestStreamEndpoint:
    """Tests for streaming chat endpoint."""

    @pytest.mark.asyncio
    async def test_stream_returns_sse(self, chat_client: AsyncClient):
        """Test that stream endpoint returns SSE format."""

        async def mock_stream(*args, **kwargs):
            yield 'data: {"type": "text", "content": "Hello"}\n\n'
            yield 'data: {"type": "text", "content": " world"}\n\n'
            yield 'data: {"type": "done", "sources": []}\n\n'

        with patch("server.api.chat.stream_response", mock_stream):
            response = await chat_client.post(
                "/api/chat/stream",
                json={"message": "Test", "repo_id": "test-repo"},
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    @pytest.mark.asyncio
    async def test_stream_stores_user_message(self, chat_client: AsyncClient):
        """Test that streaming stores user message before streaming."""

        async def mock_stream(*args, **kwargs):
            yield 'data: {"type": "done", "sources": []}\n\n'

        with patch("server.api.chat.stream_response", mock_stream):
            response = await chat_client.post(
                "/api/chat/stream",
                json={
                    "message": "Stream test message",
                    "repo_id": "test-repo",
                    "conversation_id": "stream-conv",
                },
            )

            assert response.status_code == 200

            store = get_conversation_store()
            messages = store.get_messages("stream-conv")
            assert len(messages) == 1
            assert messages[0].content == "Stream test message"
            assert messages[0].role == "user"
