"""Embedding behavior through the actual OpenAI SDK and local HTTP bytes."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import threading
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import SecretStr

from server.indexing.embedder import Embedder, configure_postgres_embedding_cache_backend
from server.indexing.embedding_gateway import EmbeddingGateway, EmbeddingGatewayError
from server.models.index import Chunk
from server.models.tribrid_config_model import EmbeddingConfig
from server.observability.run_census import RunCensusScope, RunIdentity


@dataclass
class _EmbeddingHTTP:
    base_url: str = ""
    mode: str = "valid"
    requests: list[dict] = field(default_factory=list)
    received: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def embedding_http() -> Iterator[_EmbeddingHTTP]:
    state = _EmbeddingHTTP()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
            state.received.set()
            mode = state.mode
            if mode == "held":
                state.release.wait(5)
            if mode == "disconnect":
                self.close_connection = True
                return
            status = 503 if mode in {"unavailable", "recover"} else 400 if mode == "invalid_request" else 200
            if mode.startswith(("http_", "recover_")):
                status = int(mode.rsplit("_", 1)[1])
            if mode == "recover" or mode.startswith("recover_"):
                state.mode = "valid"
            data = [{"object": "embedding", "index": index,
                     "embedding": [float(index + 1)] * body["dimensions"]}
                    for index, _ in enumerate(body["input"])]
            data.reverse()  # Ordering is defined by index, never by wire array position.
            if mode == "duplicate_index":
                data[-1]["index"] = data[0]["index"]
            elif mode == "missing":
                data.pop()
            elif mode == "dimension":
                data[0]["embedding"].pop()
            elif mode == "nonfinite":
                data[0]["embedding"][0] = float("nan")
            elif mode == "wrong_shape":
                data = None
            elif mode == "string_value":
                data[0]["embedding"][0] = "1.0"
            payload = {"object": "list", "model": body["model"], "data": data,
                       "usage": {"prompt_tokens": 11, "total_tokens": 11}}
            if status != 200:
                payload = {"error": {"message": "synthetic error with secret-looking data", "type": "server_error"}}
            encoded = b"{invalid json" if mode == "malformed" else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    state.base_url = f"http://127.0.0.1:{server.server_port}/v1"
    thread.start()
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _cloud_embedder(state: _EmbeddingHTTP, *, session: str = "embedding-unit", lane="index_embeddings",
                    scope: RunCensusScope | None = None, **changes) -> Embedder:
    config = EmbeddingConfig(embedding_backend="provider", embedding_type="openai",
        embedding_model="text-embedding-3-small", embedding_dim=128, embedding_retry_max=1,
        **changes)
    identity = RunIdentity(session, "embedding-corpus", lane)
    return Embedder(config, gateway=EmbeddingGateway(
        state.base_url, "openai.text-embedding-3-small", config.effective_model, 1536, identity,
        api_key=SecretStr("synthetic-gateway-client"), census_scope=scope,
        trace_headers={"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"},
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", ["index_embeddings", "retrieval_embeddings", "cache_embeddings"])
async def test_embed_single(embedding_http: _EmbeddingHTTP, lane: str) -> None:
    embedder = _cloud_embedder(embedding_http, lane=lane, embed_text_prefix="prefix:", embed_text_suffix=":suffix")
    assert await embedder.embed("input") == [1.0] * 128
    request = embedding_http.requests[0]
    assert request["path"] == "/v1/embeddings"
    # Preserve the established provider single-input preprocessing contract.
    assert request["body"]["input"] == [embedder._prepare_text(embedder._prepare_text("input"))]
    assert request["body"]["model"] == "openai.text-embedding-3-small"
    assert request["body"]["dimensions"] == 128
    assert request["body"]["encoding_format"] == "float"
    assert {key: request["body"][key] for key in ("max_retries", "num_retries", "disable_fallbacks")} == {
        "max_retries": 0, "num_retries": 0, "disable_fallbacks": True,
    }
    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert headers["authorization"] == "Bearer synthetic-gateway-client"
    assert headers["x-litellm-session-id"] == headers["x-litellm-trace-id"] == "embedding-unit"
    assert json.loads(headers["x-litellm-spend-logs-metadata"]) == {
        "run_id": "embedding-unit", "corpus_id": "embedding-corpus", "lane": lane,
    }
    assert headers["traceparent"].startswith("00-" + "1" * 32)


@pytest.mark.asyncio
async def test_embed_batch(embedding_http: _EmbeddingHTTP) -> None:
    embedder = _cloud_embedder(embedding_http, embed_text_prefix="prefix:")
    vectors = await embedder.embed_batch(["first", "second"])
    assert vectors == [[1.0] * 128, [2.0] * 128]
    assert embedding_http.requests[0]["body"]["input"] == ["prefix:first", "prefix:second"]


@pytest.mark.asyncio
async def test_embed_chunks(embedding_http: _EmbeddingHTTP) -> None:
    embedder = _cloud_embedder(embedding_http)
    chunks = [Chunk(chunk_id=str(index), content=f"text {index}", file_path="a.py",
        start_line=index + 1, end_line=index + 1, token_count=2) for index in range(2)]
    result = await embedder.embed_chunks(chunks, embed_texts=["context first", "context second"])
    assert [chunk.embedding for chunk in result] == [[1.0] * 128, [2.0] * 128]
    assert embedding_http.requests[0]["body"]["input"] == ["context first", "context second"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["duplicate_index", "missing", "dimension", "nonfinite", "wrong_shape", "string_value", "malformed"])
async def test_invalid_native_embedding_batch_never_enters_cache(embedding_http: _EmbeddingHTTP, mode: str) -> None:
    embedding_http.mode = mode
    embedder = _cloud_embedder(embedding_http)
    written: dict = {}

    async def lookup(_keys):
        return {}

    async def upsert(entries):
        written.update(entries)
        return len(entries)

    embedder.configure_cache_backend(lookup_batch=lookup, upsert_batch=upsert)
    with pytest.raises(EmbeddingGatewayError):
        await embedder.embed_batch(["first", "second"])
    assert written == {} and len(embedding_http.requests) == 1


@pytest.mark.asyncio
async def test_cloud_cache_hit_preserves_keys_without_a_gateway_or_credentials(embedding_http: _EmbeddingHTTP) -> None:
    embedder = _cloud_embedder(embedding_http, embed_text_prefix="document:")
    entries: dict = {}

    async def lookup(keys):
        return {key: entries[key][1] for key in keys if key in entries}

    async def upsert(values):
        entries.update(values)
        return len(values)

    embedder.configure_cache_backend(lookup_batch=lookup, upsert_batch=upsert)
    first = await embedder.embed_batch(["one", "one", "two"])
    assert set(entries) == {hashlib.sha256(value.encode()).hexdigest() for value in ("document:one", "document:two")}
    second_run = Embedder(embedder.config)
    second_run.configure_cache_backend(lookup_batch=lookup, upsert_batch=upsert)
    assert await second_run.embed_batch(["one", "one", "two"]) == first
    assert len(embedding_http.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,attempts", [
    ("recover", 2), ("unavailable", 3), ("invalid_request", 1), ("disconnect", 3),
    *[(f"recover_{status}", 2) for status in (408, 409, 429, 500, 503)],
    *[(f"http_{status}", 3) for status in (408, 409, 429, 500, 503)],
    *[(f"http_{status}", 1) for status in (400, 401, 403, 404, 422)],
])
async def test_retry_owner_matches_actual_http_dispatch_and_durable_census(embedding_http: _EmbeddingHTTP, tmp_path: Path, mode: str, attempts: int) -> None:
    identity = RunIdentity("retry-unit", "embedding-corpus", "index_embeddings")
    checkpoint_path = tmp_path / "census.json"
    def persist(checkpoint):
        checkpoint_path.write_text(json.dumps(asdict(checkpoint)))
    scope = RunCensusScope(identity, persist)
    embedder = _cloud_embedder(embedding_http, session=identity.session_id, scope=scope)
    embedding_http.mode = mode
    embedder.config.embedding_retry_max = 3
    if mode == "recover" or mode.startswith("recover_"):
        assert await embedder.embed_batch(["calibration"]) == [[1.0] * 128]
    else:
        with pytest.raises(EmbeddingGatewayError) as error:
            await embedder.embed_batch(["calibration"])
        assert "secret-looking" not in str(error.value)
    scope.finish_owner()
    checkpoint = json.loads(checkpoint_path.read_text())
    assert checkpoint["state"] == "closed"
    assert checkpoint["started_requests"] == checkpoint["completed_requests"] == attempts
    assert len(embedding_http.requests) == attempts
    assert checkpoint["uncertain_requests"] == (attempts if mode == "disconnect" else 0)


@pytest.mark.asyncio
async def test_cancellation_settles_the_original_scope_and_new_run_keeps_its_identity(embedding_http: _EmbeddingHTTP, tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "cancel.json"
    def persist(checkpoint):
        checkpoint_path.write_text(json.dumps(asdict(checkpoint)))
    identity = RunIdentity("cancelled-run", "embedding-corpus", "index_embeddings")
    scope = RunCensusScope(identity, persist)
    embedding_http.mode = "held"
    task = asyncio.create_task(_cloud_embedder(embedding_http, session=identity.session_id, scope=scope).embed_batch(["held"]))
    assert await asyncio.to_thread(embedding_http.received.wait, 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    scope.finish_owner()
    checkpoint = json.loads(checkpoint_path.read_text())
    assert checkpoint["started_requests"] == checkpoint["completed_requests"] == checkpoint["uncertain_requests"] == 1
    assert checkpoint["state"] == "closed"
    embedding_http.mode = "valid"
    embedding_http.release.set()
    assert await _cloud_embedder(embedding_http, session="later-run").embed_batch(["next"])
    sessions = [{k.lower(): v for k, v in row["headers"].items()}["x-litellm-session-id"] for row in embedding_http.requests]
    assert sessions == ["cancelled-run", "later-run"]


@pytest.mark.asyncio
async def test_cloud_without_explicit_route_refuses_before_any_dispatch() -> None:
    embedder = Embedder(EmbeddingConfig(embedding_backend="provider", embedding_dim=128))
    with pytest.raises(EmbeddingGatewayError, match="explicit"):
        await embedder.embed_batch(["input"])


@pytest.mark.asyncio
async def test_embed_batch_persistent_cache_reuses_vectors() -> None:
    embedder = Embedder(
        EmbeddingConfig(
            embedding_backend="deterministic",
            embedding_type="openai",
            embedding_model="text-embedding-3-small",
            embedding_dim=128,
            embedding_cache_enabled=True,
        )
    )

    cache_store: dict[str, list[float]] = {}
    upsert_calls = 0

    async def _lookup(input_hashes: list[str]) -> dict[str, list[float]]:
        return {h: cache_store[h] for h in input_hashes if h in cache_store}

    async def _upsert(entries: dict[str, tuple[str, list[float]]]) -> int:
        nonlocal upsert_calls
        upsert_calls += 1
        for h, (_, vec) in entries.items():
            cache_store[h] = list(vec)
        return len(entries)

    embedder.configure_cache_backend(lookup_batch=_lookup, upsert_batch=_upsert)

    first = await embedder.embed_batch(["hello cache"])
    second = await embedder.embed_batch(["hello cache"])

    assert len(first) == 1 and len(first[0]) == 128
    assert first == second
    assert upsert_calls == 1


@pytest.mark.asyncio
async def test_embed_chunks_accepts_contextual_override_texts() -> None:
    embedder = Embedder(
        EmbeddingConfig(
            embedding_backend="deterministic",
            embedding_type="openai",
            embedding_model="text-embedding-3-small",
            embedding_dim=128,
        )
    )
    chunk = Chunk(
        chunk_id="c1",
        content="same content",
        file_path="a.py",
        start_line=1,
        end_line=3,
        language="python",
        token_count=4,
    )

    plain = await embedder.embed_chunks([chunk])
    with_context = await embedder.embed_chunks([chunk], embed_texts=["[file=a.py] [line_range=1-3]\nsame content"])

    assert plain[0].embedding != with_context[0].embedding


def test_embedder_provider_methods_live_on_class() -> None:
    assert callable(Embedder._embed_openai)
    assert callable(Embedder._embed_mlx_embeddings)
    assert callable(Embedder._embed_local_sentence_transformers)


def test_configure_postgres_embedding_cache_backend_clears_stale_backend_when_postgres_lacks_cache_api() -> None:
    embedder = Embedder(
        EmbeddingConfig(
            embedding_backend="provider",
            embedding_type="local",
            embedding_model_local="all-MiniLM-L6-v2",
            embedding_dim=384,
            embedding_cache_enabled=True,
        )
    )

    async def _lookup(_input_hashes: list[str]) -> dict[str, list[float]]:
        return {}

    async def _upsert(_entries: dict[str, tuple[str, list[float]]]) -> int:
        return 0

    embedder.configure_cache_backend(lookup_batch=_lookup, upsert_batch=_upsert)
    assert embedder._cache_lookup_batch is not None
    assert embedder._cache_upsert_batch is not None

    configure_postgres_embedding_cache_backend(embedder, object())  # type: ignore[arg-type]

    assert embedder._cache_lookup_batch is None
    assert embedder._cache_upsert_batch is None


@pytest.mark.parametrize("provider,backend", [
    ("openai", "deterministic"), ("local", "provider"),
    ("huggingface", "provider"), ("mlx", "provider"),
])
def test_noncloud_constructor_family_needs_no_gateway(provider: str, backend: str) -> None:
    from server.indexing.embedding_gateway import embedding_gateway_for_config
    from server.models.tribrid_config_model import TriBridConfig
    from server.retrieval.cache import SemanticCacheService

    cfg = TriBridConfig()
    cfg.embedding.embedding_backend = backend
    cfg.embedding.embedding_type = provider
    identity = RunIdentity("constructor-run", "constructor-corpus", "cache_embeddings")
    assert embedding_gateway_for_config(cfg, identity=identity) is None
    service = SemanticCacheService(cfg, identity=identity)
    assert service._embedder._gateway is None
    assert service._embedder.config.effective_model == cfg.embedding.effective_model
    assert service._embedder.tokenization == cfg.tokenization


def test_semantic_cache_constructor_captures_each_run_without_mutating_config() -> None:
    from server.gateway_catalog import warm_gateway_catalog
    from server.models.tribrid_config_model import TriBridConfig
    from server.retrieval.cache import SemanticCacheService

    warm_gateway_catalog()
    cfg = TriBridConfig()
    cfg.embedding.embedding_backend = "provider"
    original = cfg.model_dump()
    first = RunIdentity("cache-run-one", "corpus-one", "cache_embeddings")
    second = RunIdentity("cache-run-two", "corpus-two", "cache_embeddings")
    service_one = SemanticCacheService(cfg, identity=first)
    service_two = SemanticCacheService(cfg, identity=second)
    assert service_one._embedder._gateway.identity == first
    assert service_two._embedder._gateway.identity == second
    assert cfg.model_dump() == original


@pytest.mark.asyncio
async def test_durable_admission_failure_prevents_cloud_dispatch(embedding_http: _EmbeddingHTTP) -> None:
    checkpoints = []
    def persist(checkpoint):
        if checkpoint.started_requests:
            raise OSError("synthetic full disk")
        checkpoints.append(checkpoint)
    identity = RunIdentity("disk-failure", "embedding-corpus", "index_embeddings")
    scope = RunCensusScope(identity, persist)
    embedder = _cloud_embedder(embedding_http, session=identity.session_id, scope=scope)
    with pytest.raises(EmbeddingGatewayError):
        await embedder.embed_batch(["must not leave"])
    assert embedding_http.requests == []
    assert scope.snapshot().state == "interrupted"


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_does_not_start_an_sdk_retry(embedding_http: _EmbeddingHTTP) -> None:
    route = _cloud_embedder(embedding_http)._gateway
    assert route is not None
    embedding_http.mode = "held"
    started = asyncio.get_running_loop().time()
    with pytest.raises(EmbeddingGatewayError):
        await route.embed(["held"], model=route.provider_model, dimensions=128, timeout_s=0.1, max_attempts=1)
    assert asyncio.get_running_loop().time() - started < 2
    assert len(embedding_http.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("model,dimensions", [("different-model", 128), ("text-embedding-3-small", 3072)])
async def test_route_mismatch_is_refused_before_dispatch(embedding_http: _EmbeddingHTTP, model: str, dimensions: int) -> None:
    route = _cloud_embedder(embedding_http)._gateway
    assert route is not None
    with pytest.raises(EmbeddingGatewayError):
        await route.embed(["input"], model=model, dimensions=dimensions, timeout_s=1, max_attempts=1)
    assert embedding_http.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", ["index_embeddings", "retrieval_embeddings", "cache_embeddings"])
@pytest.mark.parametrize("scope_trace", ["owned", "absent", "no_scope"])
async def test_embedding_factory_keeps_owner_trace_when_ambient_request_differs(
    embedding_http: _EmbeddingHTTP, tmp_path: Path, lane: str, scope_trace: str,
) -> None:
    from dataclasses import replace

    from opentelemetry import trace
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

    from server.indexing.embedding_gateway import embedding_gateway_for_config
    from server.models.tribrid_config_model import TriBridConfig

    identity = RunIdentity("trace-owner", "embedding-corpus", lane)
    owned = {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01", "tracestate": "owner=run"}
    checkpoint_path = tmp_path / "trace-census.json"

    def persist(checkpoint):
        checkpoint_path.write_text(json.dumps(asdict(checkpoint)))

    scope = (None if scope_trace == "no_scope" else
             RunCensusScope(identity, persist, trace_headers=owned if scope_trace == "owned" else {}))
    config = TriBridConfig()
    config.embedding = EmbeddingConfig(embedding_backend="provider", embedding_type="openai",
                                      embedding_model="text-embedding-3-small", embedding_dim=128)
    config.chat.litellm.base_url = embedding_http.base_url
    ambient = NonRecordingSpan(SpanContext(trace_id=int("1" * 32, 16), span_id=int("2" * 16, 16),
        is_remote=False, trace_flags=TraceFlags(1), trace_state=TraceState([("ambient", "request")])))
    with trace.use_span(ambient):
        route = embedding_gateway_for_config(config, identity=identity, census_scope=scope)
        assert route is not None
        route = replace(route, api_key=SecretStr("synthetic-gateway-client"))
        await Embedder(config.embedding, gateway=route).embed_batch(["trace fixture"])
    headers = {key.lower(): value for key, value in embedding_http.requests[0]["headers"].items()}
    if scope_trace == "owned":
        assert {key: headers[key] for key in owned} == owned
    elif scope_trace == "absent":
        assert "traceparent" not in headers and "tracestate" not in headers
    else:
        assert headers["traceparent"] == "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
        assert headers["tracestate"] == "ambient=request"
    assert json.loads(headers["x-litellm-spend-logs-metadata"])["lane"] == lane
    if scope is not None:
        scope.finish_owner()
        saved = json.loads(checkpoint_path.read_text())
        assert saved["started_requests"] == saved["completed_requests"] == 1
