from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from prometheus_client import REGISTRY

from server.config import DEFAULT_CONFIG_PATH, load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.qdrant_store import QdrantChunkStore
from tests.api.fake_gateway import (
    completion_gateway,
    empty_stream_gateway,
    gateway_env,
    slow_delta_gateway,
)


def _set_feedback_log_parent_to_file(tmp_path: Path) -> str:
    config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        pytest.skip("tribrid_config.json missing in test environment")

    original = config_path.read_text(encoding="utf-8")
    cfg = TriBridConfig.model_validate_json(original)
    parent_file = tmp_path / "feedback-log-parent"
    parent_file.write_text("not a directory", encoding="utf-8")
    cfg.tracing.tribrid_log_path = str((parent_file / "queries.jsonl").resolve())
    config_path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return original


async def test_feedback_endpoint_accepts_chat_signal(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"event_id": "evt_1", "signal": "thumbsup", "surface": "chat"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


async def test_feedback_endpoint_accepts_ui_rating(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"rating": 5, "comment": "Great eval UX", "timestamp": "2026-02-04T00:00:00Z", "context": "evaluation"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


async def test_feedback_endpoint_rejects_invalid_signal(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"event_id": "evt_2", "signal": "not_a_real_signal"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 400


async def test_feedback_endpoint_rejects_mixed_rating_and_signal(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"rating": 5, "signal": "thumbsup"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 422


@pytest.mark.requires_postgres
async def test_feedback_endpoint_rejects_unknown_corpus_scope(client) -> None:
    r = await client.post(
        "/api/feedback?corpus_id=definitely-not-a-real-corpus",
        json={"event_id": "evt_bad_scope", "signal": "thumbsup", "surface": "chat"},
    )
    assert r.status_code == 404


async def test_feedback_endpoint_returns_typed_503_on_log_write_failure(client, tmp_path: Path) -> None:
    config_path = DEFAULT_CONFIG_PATH
    original = _set_feedback_log_parent_to_file(tmp_path)
    try:
        r = await client.post("/api/feedback", json={"event_id": "evt_io_fail", "signal": "thumbsup", "surface": "chat"})
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "feedback_log"
        assert detail["operation"] == "Feedback API"
        assert detail["retryable"] is True
        assert detail["operator_hint"]
        assert str(tmp_path) not in json.dumps(r.json())
    finally:
        config_path.write_text(original, encoding="utf-8")


async def test_reranker_click_endpoint_accepts_payload(client) -> None:
    r = await client.post(
        "/api/reranker/click",
        json={"event_id": "evt_3", "doc_id": "server/api/chat.py"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


@pytest.mark.requires_postgres
async def test_reranker_click_endpoint_rejects_unknown_corpus_scope(client) -> None:
    r = await client.post(
        "/api/reranker/click?corpus_id=definitely-not-a-real-corpus",
        json={"event_id": "evt_bad_click_scope", "doc_id": "missing.md"},
    )
    assert r.status_code == 404


async def test_reranker_click_endpoint_returns_typed_503_on_log_write_failure(client, tmp_path: Path) -> None:
    config_path = DEFAULT_CONFIG_PATH
    original = _set_feedback_log_parent_to_file(tmp_path)
    try:
        r = await client.post(
            "/api/reranker/click",
            json={"event_id": "evt_click_io_fail", "doc_id": "server/api/chat.py"},
        )
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "feedback_log"
        assert detail["operation"] == "Reranker click feedback"
        assert detail["retryable"] is True
        assert detail["operator_hint"]
        assert str(tmp_path) not in json.dumps(r.json())
    finally:
        config_path.write_text(original, encoding="utf-8")


# ---------------------------------------------------------------------------------------
# Chunk-level query records and event feedback, end to end on a real corpus
# ---------------------------------------------------------------------------------------

_ENTRY_POINT_QUESTION = "Which function is the application entry point?"
_LONG_DOCSTRING = (
    "The application entry point parses the command-line arguments, loads the corpus "
    "configuration, starts the API server and registers the shutdown hooks. " * 8
)


def _feedback_count(signal: str, surface: str) -> float:
    return float(REGISTRY.get_sample_value("tribrid_feedback_events_total", {"signal": signal, "surface": surface}) or 0.0)


def _log_records(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sse_events(body: str) -> list[dict]:
    return [json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")]


@pytest_asyncio.fixture
async def logged_corpus(tmp_path: Path):
    """A real, retrievable pytest_ corpus (Postgres + Qdrant) whose scoped config writes its
    query log under tmp_path, with local tracing so every run's trace is kept in-process."""
    corpus_id = f"pytest_feedback_{uuid.uuid4().hex[:8]}"
    log_path = tmp_path / "queries.jsonl"
    cfg = load_config()
    cfg.tracing.tracing_enabled = True
    cfg.tracing.tracing_mode = "local"
    cfg.tracing.otel_export_enabled = False
    cfg.tracing.langfuse_enabled = False
    cfg.tracing.trace_sampling_rate = 1.0
    cfg.tracing.tribrid_log_path = str(log_path)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
    await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
    chunks = [
        Chunk(
            chunk_id=f"{corpus_id}-main",
            content=f'def main():\n    """{_LONG_DOCSTRING}"""',
            file_path="src/main.py",
            start_line=1,
            end_line=2,
            language="python",
            token_count=180,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        ),
        Chunk(
            chunk_id=f"{corpus_id}-session",
            content='class SessionModel:\n    """The session record persisted between chat turns."""',
            file_path="src/models.py",
            start_line=10,
            end_line=12,
            language="python",
            token_count=12,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        ),
    ]
    await pg.upsert_chunks(corpus_id, chunks)
    await QdrantChunkStore(cfg).upsert_chunks(corpus_id, chunks, embedding_dim=int(cfg.embedding.embedding_dim), pg=pg)
    try:
        yield corpus_id, log_path, cfg
    finally:
        try:
            await QdrantChunkStore(cfg).delete_corpus(corpus_id)
        except Exception:
            pass
        try:
            await pg.delete_corpus(corpus_id)
        except Exception:
            pass


def _chat_config(cfg, base_url: str):  # noqa: ANN001, ANN202 - TriBridConfig in, TriBridConfig out
    chat_cfg = cfg.model_copy(deep=True)
    chat_cfg.chat.litellm.enabled = True
    chat_cfg.chat.litellm.base_url = base_url
    chat_cfg.chat.litellm.default_model = "openai.gpt-6-luna"
    chat_cfg.chat.recall.enabled = False
    chat_cfg.semantic_cache.enabled = False
    return chat_cfg


async def _stream_chat(client, corpus_id: str, chat_cfg) -> list[dict]:  # noqa: ANN001
    from server.api.chat import set_config

    set_config(chat_cfg)
    try:
        response = await client.post(
            "/api/chat/stream",
            json={
                "message": _ENTRY_POINT_QUESTION,
                "sources": {"corpus_ids": [corpus_id]},
                "include_graph": False,
            },
        )
    finally:
        set_config(None)
    assert response.status_code == 200, response.text
    return _sse_events(response.text)


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
async def test_chat_record_is_chunk_level_and_feedback_of_both_polarities_is_recorded(client, logged_corpus) -> None:
    corpus_id, log_path, cfg = logged_corpus
    with completion_gateway("The entry point is main() in src/main.py.") as base_url, gateway_env(base_url):
        events = await _stream_chat(client, corpus_id, _chat_config(cfg, base_url))
    done = events[-1]
    assert done["type"] == "done" and done["llm_used"] is True, events
    run_id = done["run_id"]
    cited = [source["chunk_id"] for source in done["sources"]]
    assert f"{corpus_id}-main" in cited

    [record] = [r for r in _log_records(log_path) if r.get("kind") == "chat"]
    assert record["event_id"] == run_id and record["outcome"] == "ok"
    assert record["top_paths"] == [s["file_path"] for s in done["sources"]][:5]
    candidates = record["candidates"]
    assert [c["rank"] for c in candidates] == list(range(1, len(candidates) + 1))
    assert [c["chunk_id"] for c in candidates] == cited[: len(candidates)]
    main = next(c for c in candidates if c["chunk_id"] == f"{corpus_id}-main")
    assert (main["file_path"], main["start_line"], main["end_line"]) == ("src/main.py", 1, 2)
    assert main["page_start"] is None and main["page_end"] is None  # code chunk: lines, no pages
    assert main["source"] in {"vector", "sparse", "graph"} and isinstance(main["score"], float)
    assert len(main["text"]) == 500 and main["text"].startswith('def main():\n    """The application entry point')

    up_before, down_before = _feedback_count("thumbsup", "chat"), _feedback_count("thumbsdown", "chat")
    liked = await client.post(
        f"/api/feedback?corpus_id={corpus_id}",
        json={"event_id": run_id, "signal": "thumbsup", "chunk_ids": cited[:1]},
    )
    disliked = await client.post(
        f"/api/feedback?corpus_id={corpus_id}",
        json={"event_id": run_id, "signal": "thumbsdown", "chunk_ids": cited, "surface": "chat", "note": "cites the wrong file"},
    )
    assert liked.status_code == 200, liked.text
    assert disliked.status_code == 200, disliked.text

    feedback = [r for r in _log_records(log_path) if r.get("kind") == "feedback"]
    assert [(f["signal"], f["event_id"], f["surface"], f["chunk_ids"]) for f in feedback] == [
        ("thumbsup", run_id, "chat", cited[:1]),
        ("thumbsdown", run_id, "chat", cited),
    ]
    assert _feedback_count("thumbsup", "chat") == up_before + 1
    assert _feedback_count("thumbsdown", "chat") == down_before + 1


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
async def test_feedback_on_a_failed_chat_run_is_refused_with_a_typed_409(client, logged_corpus) -> None:
    corpus_id, log_path, cfg = logged_corpus
    with empty_stream_gateway() as base_url, gateway_env(base_url):
        events = await _stream_chat(client, corpus_id, _chat_config(cfg, base_url))
    done = events[-1]
    assert [e["type"] for e in events][-2:] == ["error", "done"] and done["llm_used"] is False
    [record] = [r for r in _log_records(log_path) if r.get("kind") == "chat"]
    assert record["event_id"] == done["run_id"] and record["outcome"] == "gateway_error"
    assert record["candidates"], "retrieval ran, so the failed run still records its candidates"

    before = _feedback_count("thumbsdown", "chat")
    r = await client.post(
        f"/api/feedback?corpus_id={corpus_id}",
        json={"event_id": done["run_id"], "signal": "thumbsdown", "surface": "chat"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {
        "code": "feedback_event_not_answered",
        "event_id": done["run_id"],
        "outcome": "gateway_error",
        "message": "The rated event failed or was aborted; there is no answer to rate.",
    }
    assert not [rec for rec in _log_records(log_path) if rec.get("kind") == "feedback"]
    assert _feedback_count("thumbsdown", "chat") == before


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
async def test_feedback_on_an_aborted_chat_run_is_refused_from_its_trace(client, logged_corpus) -> None:
    """An aborted stream writes no query record (nothing commits before `done`); its trace
    carries the outcome, and that is what refuses the feedback."""
    from server.api.chat import set_config
    from server.main import app
    from server.services.traces import get_trace_store
    from tests.api.live_server import post_stream_then_disconnect

    from server.services.conversation_store import get_conversation_store

    corpus_id, log_path, cfg = logged_corpus
    conversation_id = f"pytest-aborted-{uuid.uuid4().hex[:8]}"
    with slow_delta_gateway(delay_seconds=0.5) as base_url, gateway_env(base_url):
        set_config(_chat_config(cfg, base_url))
        try:
            await post_stream_then_disconnect(
                app,
                "/api/chat/stream",
                {
                    "message": _ENTRY_POINT_QUESTION,
                    "sources": {"corpus_ids": [corpus_id]},
                    "include_graph": False,
                    "conversation_id": conversation_id,
                },
                disconnect_when=lambda chunk: b'"type": "text"' in chunk,
            )
        finally:
            set_config(None)
    # Nothing of the abandoned exchange was committed.
    assert get_conversation_store().get_messages(conversation_id) == []
    latest = await get_trace_store().latest(repo=corpus_id)
    assert latest.trace is not None and latest.run_id
    outcomes = [e.data.get("outcome") for e in latest.trace.events if e.kind == "chat.outcome"]
    assert outcomes == ["client_disconnect"]
    assert not [r for r in _log_records(log_path) if r.get("kind") == "chat"]

    r = await client.post(
        f"/api/feedback?corpus_id={corpus_id}",
        json={"event_id": latest.run_id, "signal": "thumbsup", "surface": "chat"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["outcome"] == "client_disconnect"


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
async def test_search_returns_its_event_id_and_search_feedback_links_to_it(client, logged_corpus) -> None:
    corpus_id, log_path, _cfg = logged_corpus
    response = await client.post(
        "/api/search",
        json={
            "query": "application entry point that starts the API server",
            "corpus_id": corpus_id,
            "top_k": 5,
            "include_vector": False,
            "include_sparse": True,
            "include_graph": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    event_id = body["event_id"]
    assert isinstance(event_id, str) and event_id
    assert body["matches"] and body["matches"][0]["file_path"] == "src/main.py"

    [record] = [r for r in _log_records(log_path) if r.get("kind") == "search"]
    assert record["event_id"] == event_id and record["outcome"] == "ok"
    assert [c["chunk_id"] for c in record["candidates"]] == [m["chunk_id"] for m in body["matches"]]

    before = _feedback_count("click", "search")
    clicked = await client.post(
        f"/api/feedback?corpus_id={corpus_id}",
        json={
            "event_id": event_id,
            "signal": "click",
            "doc_id": "src/main.py",
            "chunk_ids": [body["matches"][0]["chunk_id"]],
            "surface": "search",
        },
    )
    assert clicked.status_code == 200, clicked.text
    [feedback] = [r for r in _log_records(log_path) if r.get("kind") == "feedback"]
    assert (feedback["event_id"], feedback["surface"], feedback["chunk_ids"]) == (
        event_id,
        "search",
        [body["matches"][0]["chunk_id"]],
    )
    assert _feedback_count("click", "search") == before + 1

    mislabelled = await client.post(
        f"/api/feedback?corpus_id={corpus_id}",
        json={"event_id": event_id, "signal": "thumbsup", "surface": "chat"},
    )
    assert mislabelled.status_code == 422, mislabelled.text


async def test_feedback_on_an_event_this_server_does_not_know_needs_a_surface(client) -> None:
    unknown = f"evt-{uuid.uuid4().hex}"
    without = await client.post(
        "/api/feedback", json={"event_id": unknown, "signal": "thumbsup"}, headers={"x-tribrid-test": "1"}
    )
    assert without.status_code == 422, without.text
    with_surface = await client.post(
        "/api/feedback",
        json={"event_id": unknown, "signal": "thumbsup", "surface": "chat"},
        headers={"x-tribrid-test": "1"},
    )
    assert with_surface.status_code == 200, with_surface.text


def test_feedback_rejects_chunk_ids_or_surface_on_rating_feedback() -> None:
    from pydantic import ValidationError

    from server.models.tribrid_config_model import FeedbackRequest

    with pytest.raises(ValidationError):
        FeedbackRequest(rating=4, chunk_ids=["chunk-1"])
    with pytest.raises(ValidationError):
        FeedbackRequest(rating=4, surface="chat")
