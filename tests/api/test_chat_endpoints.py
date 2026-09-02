import asyncio
from pathlib import Path
import uuid
"""Tests for chat API endpoints with PydanticAI integration."""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.api.fake_gateway import (
    completion_gateway,
    empty_stream_gateway,
    gateway_env,
    slow_delta_gateway,
    slow_delta_requests,
)
from tests.api.live_server import live_app_subprocess
from server.config import load_config
from server.retrieval.qdrant_store import QdrantChunkStore
from server.models.index import Chunk
from server.db.postgres import PostgresClient
from server.api.chat import set_config
from server.gateway_catalog import warm_gateway_catalog
from server.main import app
from server.models.chat import Message
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig, TriBridConfig
from server.services.conversation_store import ConversationStore, get_conversation_store


@pytest.fixture
def mock_chunks() -> list[ChunkMatch]:
    """The two code chunks the seeded chat corpus holds (real stores, real retrieval)."""
    return [
        ChunkMatch(
            chunk_id="chunk_1",
            content="def main():\n    \"\"\"The application entry point: parses arguments and starts the API.\"\"\"",
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
            content="class SessionModel:\n    \"\"\"The session record persisted between chat turns.\"\"\"",
            file_path="src/models.py",
            start_line=10,
            end_line=12,
            language="python",
            score=0.85,
            source="sparse",
            metadata={},
        ),
    ]


@pytest_asyncio.fixture
async def real_corpus(mock_chunks: list[ChunkMatch]):
    """A real, retrievable corpus: the two chunks live in Postgres and Qdrant, so every chat
    below runs the real retrieval pipeline against them (no fusion stand-in)."""
    corpus_id = f"pytest_chat_suite_{uuid.uuid4().hex[:8]}"
    # Retrieval reads the corpus-scoped config: seed the stores and that config from the live
    # config so the embedding contract of the query matches the generation that was written.
    store_cfg = load_config()
    pg = PostgresClient(store_cfg.indexing.postgres_url)
    await pg.connect()
    await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
    await pg.upsert_corpus_config_json(corpus_id, store_cfg.model_dump(mode="serialization"))
    chunks = [
        Chunk(
            chunk_id=m.chunk_id,
            content=m.content,
            file_path=m.file_path,
            start_line=m.start_line,
            end_line=m.end_line,
            language=m.language,
            token_count=max(1, len(m.content.split())),
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        )
        for m in mock_chunks
    ]
    await pg.upsert_chunks(corpus_id, chunks)
    await QdrantChunkStore(store_cfg).upsert_chunks(
        corpus_id, chunks, embedding_dim=int(store_cfg.embedding.embedding_dim), pg=pg
    )
    try:
        yield corpus_id
    finally:
        try:
            await QdrantChunkStore(store_cfg).delete_corpus(corpus_id)
        except Exception:
            pass
        try:
            await pg.delete_corpus(corpus_id)
        except Exception:
            pass


@pytest_asyncio.fixture
async def chat_client() -> AsyncClient:
    """Test client on the real app: the live config (so retrieval's embedding contract matches
    the stores a seeded corpus was written to), real retrieval, a real local gateway per test."""
    warm_gateway_catalog()
    set_config(load_config())

    # Reset conversation store
    store = get_conversation_store()
    store._conversations.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up
    set_config(None)


async def _chat_cache_rows(pg: PostgresClient, corpus_id: str) -> int:
    """Generation-cache entries the chat lane wrote for this corpus (endpoint 'chat')."""
    from server.retrieval.cache import SemanticCacheService

    return len(await _chat_cache_entries(pg, corpus_id))


async def _chat_cache_entries(pg: PostgresClient, corpus_id: str) -> list[dict]:
    """The generation-cache rows for this corpus: the chat lane's retrieval cache shares the
    endpoint, so only rows whose payload carries the answer (`message`) count."""
    from server.retrieval.cache import SemanticCacheService

    pool = pg._pool  # the client's own pool; a read-only query
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT exact_key, request_fingerprint, hit_count, expires_at > now() AS live, payload "
            "FROM semantic_cache_entries WHERE endpoint = 'chat' AND scope_key = $1;",
            SemanticCacheService.scope_key([corpus_id]),
        )
    out = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict) and "message" in payload:
            out.append({"exact_key": r["exact_key"], "fingerprint": r["request_fingerprint"], "hit_count": r["hit_count"], "live": r["live"]})
    return out

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

        msg = Message(role="user", content="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?")
        store.add_message("test-id", msg, None)

        assert len(conv.messages) == 1
        assert conv.messages[0].content == "Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?"

    def test_add_message_with_provider_id(self):
        """Test adding message with provider response ID."""
        store = ConversationStore()
        conv = store.get_or_create("test-id")

        msg = Message(role="assistant", content="Epstein arranged two flights for Barry Cohen in October 2017.")
        store.add_message("test-id", msg, "resp_abc123")

        assert conv.last_provider_response_id == "resp_abc123"

    def test_get_messages(self):
        """Test retrieving conversation messages."""
        store = ConversationStore()
        store.get_or_create("test-id")

        store.add_message("test-id", Message(role="user", content="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?"), None)
        store.add_message("test-id", Message(role="assistant", content="Epstein arranged two flights for Barry Cohen in October 2017."), None)

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
        store.add_message("test-id", Message(role="user", content="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?"), None)

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
        store.add_message("test-conv-2", Message(role="user", content="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?"), None)
        store.add_message(
            "test-conv-2", Message(role="assistant", content="Epstein arranged two flights for Barry Cohen in October 2017."), None
        )

        response = await chat_client.get("/api/chat/history/test-conv-2")
        assert response.status_code == 200

        messages = response.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Epstein arranged two flights for Barry Cohen in October 2017."

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
        store.add_message("test-conv-3", Message(role="user", content="Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?"), None)

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
        with completion_gateway("Barry Cohen weighed moving plane management to Jet Aviation in 2017.") as base_url, gateway_env(base_url):

            response = await chat_client.post(
                "/api/chat",
                json={"message": "Who arranged Barry Cohen's October 2017 flights?", "sources": {"corpus_ids": []}},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data.get("run_id"), str)
            assert isinstance(data.get("started_at_ms"), int)
            assert isinstance(data.get("ended_at_ms"), int)
            assert isinstance(data.get("debug"), dict)
            assert "conversation_id" in data
            assert data["message"]["content"] == "Barry Cohen weighed moving plane management to Jet Aviation in 2017."
            assert data["message"]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_chat_uses_existing_conversation(self, chat_client: AsyncClient):
        """Test that chat uses provided conversation ID."""
        store = get_conversation_store()
        store.get_or_create("existing-conv")

        with completion_gateway("The first flight left Teterboro on 3 October 2017.") as base_url, gateway_env(base_url):

            response = await chat_client.post(
                "/api/chat",
                json={
                    "message": "Who arranged Barry Cohen's October 2017 flights?",
                    "sources": {"corpus_ids": []},
                    "conversation_id": "existing-conv",
                },
            )

            assert response.status_code == 200
            assert response.json()["conversation_id"] == "existing-conv"

    @pytest.mark.asyncio
    async def test_chat_stores_messages(self, chat_client: AsyncClient):
        """Test that chat stores user and assistant messages."""
        with completion_gateway("Barry Cohen weighed moving plane management to Jet Aviation in 2017.") as base_url, gateway_env(base_url):

            response = await chat_client.post(
                "/api/chat",
                json={"message": "Which plane management company did Barry Cohen consider switching to?", "sources": {"corpus_ids": []}},
            )

            conv_id = response.json()["conversation_id"]
            store = get_conversation_store()
            messages = store.get_messages(conv_id)

            assert len(messages) == 2
            assert messages[0].role == "user"
            assert messages[0].content == "Which plane management company did Barry Cohen consider switching to?"
            assert messages[1].role == "assistant"
            assert messages[1].content == "Barry Cohen weighed moving plane management to Jet Aviation in 2017."

    @pytest.mark.requires_postgres
    @pytest.mark.requires_qdrant
    @pytest.mark.asyncio
    async def test_chat_returns_sources(self, chat_client: AsyncClient, real_corpus: str):
        """Chat returns the sources real retrieval found in the seeded corpus."""
        with completion_gateway("The entry point is main() in src/main.py.") as base_url, gateway_env(base_url):

            response = await chat_client.post(
                "/api/chat",
                json={"message": "Which function is the application entry point?", "sources": {"corpus_ids": [real_corpus]}},
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data["sources"]) >= 1
            assert "src/main.py" in {s["file_path"] for s in data["sources"]}

class TestStreamEndpoint:
    """Tests for streaming chat endpoint."""

    @pytest.mark.asyncio
    async def test_stream_returns_sse(self, chat_client: AsyncClient):
        """The stream endpoint answers as SSE from a real (local) gateway: text deltas, then
        the terminal `done` event."""
        cfg = TriBridConfig()
        cfg.chat.litellm.enabled = True
        cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
        with slow_delta_gateway(delay_seconds=0.05) as base_url, gateway_env(base_url):
            cfg.chat.litellm.base_url = base_url
            set_config(cfg)
            try:
                response = await chat_client.post(
                    "/api/chat/stream",
                    json={
                        "message": "Which plane management company did Barry Cohen consider switching to?",
                        "sources": {"corpus_ids": []},
                    },
                )
                assert response.status_code == 200
                assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
                events = [
                    json.loads(line[len("data: ") :])
                    for line in response.text.splitlines()
                    if line.startswith("data: ")
                ]
                kinds = [str(e.get("type")) for e in events]
                assert "text" in kinds and kinds[-1] == "done", kinds
                assert "".join(e.get("content", "") for e in events if e.get("type") == "text").startswith("The plane")
            finally:
                set_config(None)

    @pytest.mark.asyncio
    async def test_stream_with_no_provider_output_persists_no_exchange(self, chat_client: AsyncClient):
        """A provider that streams nothing is a failed generation: the stream reports it and
        the durable history keeps neither an assistant message built from the failure text nor
        the unanswered question (the old behaviour stored both, and Recall indexed them)."""

        question = "Which plane management company did Barry Cohen consider switching to?"
        cfg = TriBridConfig()
        cfg.chat.litellm.enabled = True
        cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
        with empty_stream_gateway() as base_url, gateway_env(base_url):
            cfg.chat.litellm.base_url = base_url
            set_config(cfg)
            response = await chat_client.post(
                "/api/chat/stream",
                json={
                    "message": question,
                    "sources": {"corpus_ids": []},
                    "conversation_id": "stream-conv",
                },
            )

            assert response.status_code == 200
            body = response.text
            assert '"type": "error"' in body or '"type":"error"' in body
            assert "Error: LLM stream produced no content" not in body

            try:
                store = get_conversation_store()
                messages = store.get_messages("stream-conv")
                assert [m.role for m in messages] == []
            finally:
                set_config(None)

    @pytest.mark.requires_postgres
    @pytest.mark.requires_qdrant
    @pytest.mark.asyncio
    async def test_stream_closed_by_the_client_mid_answer_persists_no_exchange(self, tmp_path: Path):
        """A client that goes away after the first delta ends the exchange without a `done`
        event. Whatever streamed so far is not an answer: the durable history keeps neither a
        partial assistant message nor the question (the old wrapper stored the fragment).

        Served by a uvicorn subprocess over a real loopback socket (httpx's ASGI transport
        buffers the whole body and cannot disconnect mid-stream). Persistence is observed
        through the app's own history route on that server.
        """
        import httpx

        first_question = "Which plane management company did Barry Cohen consider switching to?"
        conversation_id = f"stream-closed-{uuid.uuid4().hex[:8]}"
        with slow_delta_gateway(delay_seconds=0.5) as base_url, gateway_env(base_url):
            cfg = load_config()
            cfg.chat.litellm.enabled = True
            cfg.chat.litellm.base_url = base_url
            cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
            cfg.chat.recall.enabled = False
            cfg.semantic_cache.enabled = 0
            config_path = tmp_path / "tribrid_config.json"
            config_path.write_text(json.dumps(cfg.model_dump(mode="serialization")), encoding="utf-8")
            with live_app_subprocess(
                config_path=config_path,
                env={"LITELLM_BASE_URL": base_url, "LITELLM_API_KEY": "pytest-fake-gateway-key"},
            ) as live_url:
                async with httpx.AsyncClient(base_url=live_url, timeout=60.0) as client:
                    first_delta_seen = False
                    async with client.stream(
                        "POST",
                        "/api/chat/stream",
                        json={
                            "message": first_question,
                            "sources": {"corpus_ids": []},
                            "conversation_id": conversation_id,
                        },
                    ) as response:
                        assert response.status_code == 200
                        async for line in response.aiter_lines():
                            if line.startswith("data: ") and '"text"' in line:
                                first_delta_seen = True
                                break
                    assert first_delta_seen
                    await asyncio.sleep(2.0)  # the server's response task is cancelled on close
                    # The durable history, read through the app's own boundary: nothing from
                    # the abandoned exchange may be in it.
                    history = await client.get(f"/api/chat/history/{conversation_id}")
                    assert history.status_code == 200, history.text
                    messages = history.json()
                    assert messages == [], messages


    @pytest.mark.requires_postgres
    @pytest.mark.requires_qdrant
    @pytest.mark.asyncio
    async def test_stream_closed_after_the_last_delta_is_committed_atomically_or_not_at_all(self, tmp_path: Path):
        """The client has every content token and leaves before the terminal `done` event is
        sent. Whether the server's cancellation reaches the handler before generation
        completes is a race with the disconnect listener, so the contract is atomicity, not a
        side: an exchange is committed iff the server produced `done`, and then the history,
        the generation cache and the query log all hold it - or none of them do. Either way
        the trace is ended, and a repeat from a fresh conversation is served from the cache
        exactly when the exchange was committed. Observed on a uvicorn subprocess."""
        import httpx

        question = "Which plane management company did Barry Cohen consider switching to?"
        conversation_id = f"stream-late-{uuid.uuid4().hex[:8]}"
        corpus_id = f"pytest_stream_late_{uuid.uuid4().hex[:8]}"
        query_log = tmp_path / "queries.jsonl"
        pg = PostgresClient("postgresql://ignored")
        await pg.connect()
        with slow_delta_gateway(delay_seconds=0.1, final_delay_seconds=3.0) as base_url, gateway_env(base_url):
            cfg = load_config()
            cfg.chat.litellm.enabled = True
            cfg.chat.litellm.base_url = base_url
            cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
            cfg.chat.recall.enabled = False
            cfg.semantic_cache.enabled = 1
            cfg.semantic_cache.mode = "read_write"
            cfg.semantic_cache.min_query_chars = 1
            cfg.tracing.tribrid_log_path = str(query_log)
            config_path = tmp_path / "tribrid_config.json"
            config_path.write_text(json.dumps(cfg.model_dump(mode="serialization")), encoding="utf-8")
            # A real corpus with retrievable chunks, so retrieval runs and has a query record to write.
            await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
            await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
            chunk = Chunk(
                chunk_id="c1",
                content="Barry Cohen considered switching plane management to Jet Aviation in 2017",
                file_path="emails/cohen-2017.txt",
                start_line=1,
                end_line=1,
                language="text",
                token_count=12,
                embedding=None,
                summary=None,
                metadata={"kind": "unit_test"},
            )
            await pg.upsert_chunks(corpus_id, [chunk])
            await QdrantChunkStore(cfg).upsert_chunks(corpus_id, [chunk], embedding_dim=int(cfg.embedding.embedding_dim), pg=pg)
            with live_app_subprocess(
                config_path=config_path,
                env={"LITELLM_BASE_URL": base_url, "LITELLM_API_KEY": "pytest-fake-gateway-key"},
            ) as live_url:
                async with httpx.AsyncClient(base_url=live_url, timeout=60.0) as client:
                    text_events = 0
                    async with client.stream(
                        "POST",
                        "/api/chat/stream",
                        json={"message": question, "sources": {"corpus_ids": [corpus_id]}, "conversation_id": conversation_id},
                    ) as response:
                        assert response.status_code == 200
                        async for line in response.aiter_lines():
                            if line.startswith("data: ") and '"text"' in line:
                                text_events += 1
                                if text_events == 4:
                                    break  # every delta received; the terminator is still 3 s away
                    assert text_events == 4
                    await asyncio.sleep(4.5)  # past the terminator: the server side has settled
                    history = await client.get(f"/api/chat/history/{conversation_id}")
                    assert history.status_code == 200, history.text
                    roles = [m["role"] for m in history.json()]
                    logged = query_log.read_text(encoding="utf-8") if query_log.exists() else ""
                    cache_rows = await _chat_cache_rows(pg, corpus_id)
                    committed = roles == ["user", "assistant"]
                    assert roles in ([], ["user", "assistant"]), roles
                    assert logged.count(question) == (1 if committed else 0), (committed, logged)
                    assert cache_rows == (1 if committed else 0), (committed, cache_rows)
                    latest = await client.get("/api/traces/latest")
                    assert latest.status_code == 200, latest.text
                    trace = (latest.json() or {}).get("trace") or {}
                    assert trace.get("ended_at_ms") is not None, trace
                    # A repeat from a fresh conversation is served from the cache exactly when the
                    # exchange was committed; otherwise it goes to the provider again.
                    again = await client.post(
                        "/api/chat/stream",
                        json={"message": question, "sources": {"corpus_ids": [corpus_id]}, "conversation_id": f"{conversation_id}-again"},
                    )
                    assert again.status_code == 200
                    assert len(slow_delta_requests()) == (1 if committed else 2), (committed, len(slow_delta_requests()))
                    await asyncio.sleep(0.5)
                    # Every completed exchange records its query, the cache-served repeat included:
                    # two records when the first exchange committed, one when only the repeat did.
                    logged = query_log.read_text(encoding="utf-8") if query_log.exists() else ""
                    assert logged.count(question) == (2 if committed else 1), (committed, logged)
                    assert await _chat_cache_rows(pg, corpus_id) == 1
        try:
            await QdrantChunkStore(load_config()).delete_corpus(corpus_id)
        except Exception:
            pass
        try:
            await pg.delete_corpus(corpus_id)
        except Exception:
            pass


    @pytest.mark.requires_postgres
    @pytest.mark.requires_qdrant
    @pytest.mark.asyncio
    async def test_stream_closed_on_done_commits_the_whole_exchange(self, tmp_path: Path):
        """A client that reads the terminal `done` event and leaves at once must find the
        whole exchange committed: both messages in the history and the answer in the
        generation cache (the repeat is a cache hit). The exchange is committed before `done`
        goes out, so nothing depends on the client staying to read another byte."""
        import httpx

        question = "Which plane management company did Barry Cohen consider switching to?"
        conversation_id = f"stream-done-{uuid.uuid4().hex[:8]}"
        corpus_id = f"pytest_stream_done_{uuid.uuid4().hex[:8]}"
        pg = PostgresClient("postgresql://ignored")
        await pg.connect()
        with slow_delta_gateway(delay_seconds=0.05) as base_url, gateway_env(base_url):
            cfg = load_config()
            cfg.chat.litellm.enabled = True
            cfg.chat.litellm.base_url = base_url
            cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
            cfg.chat.recall.enabled = False
            cfg.semantic_cache.enabled = 1
            cfg.semantic_cache.mode = "read_write"
            cfg.semantic_cache.min_query_chars = 1
            config_path = tmp_path / "tribrid_config.json"
            config_path.write_text(json.dumps(cfg.model_dump(mode="serialization")), encoding="utf-8")
            # The generation cache is scoped to a corpus: seed a real one for the exchange.
            await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
            await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
            chunk = Chunk(
                chunk_id="c1",
                content="Barry Cohen considered switching plane management to Jet Aviation in 2017",
                file_path="emails/cohen-2017.txt",
                start_line=1,
                end_line=1,
                language="text",
                token_count=12,
                embedding=None,
                summary=None,
                metadata={"kind": "unit_test"},
            )
            await pg.upsert_chunks(corpus_id, [chunk])
            await QdrantChunkStore(cfg).upsert_chunks(corpus_id, [chunk], embedding_dim=int(cfg.embedding.embedding_dim), pg=pg)
            with live_app_subprocess(
                config_path=config_path,
                env={"LITELLM_BASE_URL": base_url, "LITELLM_API_KEY": "pytest-fake-gateway-key"},
            ) as live_url:
                async with httpx.AsyncClient(base_url=live_url, timeout=60.0) as client:
                    first_done: dict | None = None
                    async with client.stream(
                        "POST",
                        "/api/chat/stream",
                        json={"message": question, "sources": {"corpus_ids": [corpus_id]}, "conversation_id": conversation_id},
                    ) as response:
                        assert response.status_code == 200
                        async for line in response.aiter_lines():
                            if line.startswith("data: ") and '"done"' in line:
                                first_done = json.loads(line[len("data: ") :])
                                break  # leave the moment the terminal event arrives
                    assert first_done is not None
                    await asyncio.sleep(1.0)
                    # The generation cache holds the exchange: written before `done` went out.
                    assert await _chat_cache_rows(pg, corpus_id) == 1
                    history = await client.get(f"/api/chat/history/{conversation_id}")
                    assert history.status_code == 200, history.text
                    roles = [m["role"] for m in history.json()]
                    assert roles == ["user", "assistant"], history.json()
                    assert "Jet Aviation" in history.json()[1]["content"]
                    # The same question from a fresh conversation (the cache fingerprint carries
                    # the conversation history): served from the generation cache.
                    again = await client.post(
                        "/api/chat/stream",
                        json={"message": question, "sources": {"corpus_ids": [corpus_id]}, "conversation_id": f"{conversation_id}-again"},
                    )
                    assert again.status_code == 200
                    events = [
                        json.loads(line[len("data: ") :])
                        for line in again.text.splitlines()
                        if line.startswith("data: ")
                    ]
                    done = next(e for e in events if e.get("type") == "done")
                    assert "Jet Aviation" in "".join(e.get("content", "") for e in events if e.get("type") == "text")
                    # Served from the generation cache: the provider saw exactly one request.
                    assert len(slow_delta_requests()) == 1, (
                        len(slow_delta_requests()),
                        await _chat_cache_entries(pg, corpus_id),
                    )
                    assert done.get("llm_used") is True
        try:
            await QdrantChunkStore(load_config()).delete_corpus(corpus_id)
        except Exception:
            pass
        try:
            await pg.delete_corpus(corpus_id)
        except Exception:
            pass


class TestChatCitationsRealPipeline:
    """Exercise the real rag pipeline without external API calls.

    Provider calls are replaced at the live chat-handler boundary so citation
    collection and SSE completion payloads remain deterministic.
    """

    @pytest.mark.requires_postgres
    @pytest.mark.requires_qdrant
    @pytest.mark.asyncio
    async def test_chat_collects_sources_and_passes_leg_toggles(
        self, chat_client: AsyncClient, real_corpus: str
    ):
        with completion_gateway("Config persistence lives in server/services/config_store.py.") as base_url, gateway_env(base_url):
            response = await chat_client.post(
                "/api/chat",
                json={
                    "message": "Which function is the application entry point?",
                    "sources": {"corpus_ids": [real_corpus]},
                    "include_vector": False,
                    "include_sparse": True,
                    "include_graph": False,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"]
        assert data["message"]["role"] == "assistant"
        assert data["message"]["content"] == "Config persistence lives in server/services/config_store.py."
        assert isinstance(data["sources"], list)
        assert len(data["sources"]) >= 1
        assert "src/main.py" in {s["file_path"] for s in data["sources"]}

        # The per-message leg toggles reached retrieval: the debug block reports what the
        # request asked for and what fusion actually requested of the stores.
        debug = data["debug"]
        assert debug["include_vector"] is False
        assert debug["include_sparse"] is True
        assert debug["include_graph"] is False
        rag = (debug.get("fusion_debug") or {}).get("chat_rag_fusion") or {}
        assert rag.get("fusion_vector_requested") is False
        assert rag.get("fusion_sparse_requested") is True
        assert rag.get("fusion_graph_requested") is False

    @pytest.mark.requires_postgres
    @pytest.mark.requires_qdrant
    @pytest.mark.asyncio
    async def test_stream_done_includes_conversation_id_and_sources(
        self, chat_client: AsyncClient, real_corpus: str
    ):
        payload = {
            "message": "Which function is the application entry point?",
            "sources": {"corpus_ids": [real_corpus]},
            "conversation_id": "stream-conv-2",
        }

        body = ""
        with completion_gateway() as base_url, gateway_env(base_url):
            async with chat_client.stream("POST", "/api/chat/stream", json=payload) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                async for chunk in resp.aiter_text():
                    body += chunk

        # Parse SSE events and locate the done event
        done: dict | None = None
        for block in body.split("\n\n"):
            block = block.strip()
            if not block.startswith("data:"):
                continue
            data = block[len("data:") :].strip()
            if not data:
                continue
            parsed = json.loads(data)
            if parsed.get("type") == "done":
                done = parsed
                break

        assert done is not None, f"Expected done event in SSE body, got: {body!r}"
        assert isinstance(done.get("run_id"), str)
        assert isinstance(done.get("started_at_ms"), int)
        assert isinstance(done.get("ended_at_ms"), int)
        assert isinstance(done.get("debug"), dict)
        assert done.get("conversation_id") == "stream-conv-2"
        assert isinstance(done.get("sources"), list)
        assert len(done["sources"]) >= 1
        assert "src/main.py" in {s["file_path"] for s in done["sources"]}

        # Streaming now stores assistant message on completion
        store = get_conversation_store()
        msgs = store.get_messages("stream-conv-2")
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"


class TestTraceEndpoint:
    """Tests for local trace endpoint."""

    @pytest.mark.asyncio
    async def test_traces_latest_by_run_id(self, chat_client: AsyncClient):
        with completion_gateway("Barry Cohen's October 2017 flights were arranged through Jeffrey Epstein's office.") as base_url, gateway_env(base_url):
            resp = await chat_client.post(
                "/api/chat",
                json={"message": "Who arranged Barry Cohen's October 2017 flights?", "sources": {"corpus_ids": []}},
            )
            assert resp.status_code == 200
            run_id = resp.json().get("run_id")
            assert isinstance(run_id, str)

        tr = await chat_client.get(f"/api/traces/latest?run_id={run_id}")
        assert tr.status_code == 200
        data = tr.json()
        assert data.get("run_id") == run_id
        assert data.get("trace") is not None
        assert isinstance(data["trace"].get("events"), list)
        kinds = [ev.get("kind") for ev in data["trace"]["events"]]
        assert "chat.request" in kinds
        assert "chat.response" in kinds
