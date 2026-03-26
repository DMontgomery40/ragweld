"""Chat should fail closed when no LLM provider is available."""

from __future__ import annotations

import json
import os

import pytest
from httpx import AsyncClient

from server.api.chat import set_config, set_fusion
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig, TriBridConfig


class _FakeFusion:
    def __init__(self, chunks: list[ChunkMatch]):
        self._chunks = chunks
        self.last_debug = {}

    async def search(
        self,
        corpus_ids: list[str],
        query: str,
        config: FusionConfig,
        *,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
    ) -> list[ChunkMatch]:
        _ = (corpus_ids, query, config, include_vector, include_sparse, include_graph, top_k)
        self.last_debug = {
            "fusion_corpora": list(corpus_ids),
            "fusion_vector_requested": bool(include_vector),
            "fusion_sparse_requested": bool(include_sparse),
            "fusion_graph_requested": bool(include_graph),
            "fusion_vector_enabled": False,
            "fusion_sparse_enabled": True,
            "fusion_graph_enabled": False,
            "fusion_vector_results": 0,
            "fusion_sparse_results": len(self._chunks),
            "fusion_graph_hydrated_chunks": 0,
        }
        return list(self._chunks)


def _disable_all_chat_providers(cfg: TriBridConfig) -> TriBridConfig:
    cfg.chat.openrouter.enabled = False
    cfg.chat.litellm.enabled = False
    for provider in cfg.chat.local_models.providers:
        provider.enabled = False
    return cfg


@pytest.fixture
def providerless_chat_config() -> TriBridConfig:
    return _disable_all_chat_providers(TriBridConfig())


@pytest.fixture
def providerless_fusion() -> _FakeFusion:
    return _FakeFusion(
        [
            ChunkMatch(
                chunk_id="c1",
                content="hello world",
                file_path="src/main.py",
                start_line=1,
                end_line=1,
                language="python",
                score=1.0,
                source="sparse",
                metadata={"corpus_id": "test-repo"},
            )
        ]
    )


@pytest.mark.asyncio
async def test_chat_returns_503_without_providers(
    client: AsyncClient,
    providerless_chat_config: TriBridConfig,
    providerless_fusion: _FakeFusion,
) -> None:
    old_openai = os.environ.pop("OPENAI_API_KEY", None)
    old_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)

    try:
        set_config(providerless_chat_config)
        set_fusion(providerless_fusion)

        response = await client.post(
            "/api/chat",
            json={"message": "hello", "sources": {"corpus_ids": ["test-repo"]}},
        )

        assert response.status_code == 503
        detail = str(response.json().get("detail") or "")
        assert detail
        assert "retrieval-only" not in detail.lower()
    finally:
        set_config(None)
        set_fusion(None)
        if old_openai is not None:
            os.environ["OPENAI_API_KEY"] = old_openai
        else:
            os.environ.pop("OPENAI_API_KEY", None)
        if old_openrouter is not None:
            os.environ["OPENROUTER_API_KEY"] = old_openrouter
        else:
            os.environ.pop("OPENROUTER_API_KEY", None)


@pytest.mark.asyncio
async def test_chat_stream_emits_error_event_without_providers(
    client: AsyncClient,
    providerless_chat_config: TriBridConfig,
    providerless_fusion: _FakeFusion,
) -> None:
    old_openai = os.environ.pop("OPENAI_API_KEY", None)
    old_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)

    try:
        set_config(providerless_chat_config)
        set_fusion(providerless_fusion)

        response = await client.post(
            "/api/chat/stream",
            json={
                "message": "hello",
                "stream": True,
                "sources": {"corpus_ids": ["test-repo"]},
            },
        )

        assert response.status_code == 200
        body = (await response.aread()).decode("utf-8")
        events: list[dict[str, object]] = []
        for block in body.split("\n\n"):
            part = block.strip()
            if not part.startswith("data:"):
                continue
            raw = part[len("data:") :].strip()
            if not raw:
                continue
            events.append(json.loads(raw))

        error_event = next((event for event in events if event.get("type") == "error"), None)
        done_event = next((event for event in events if event.get("type") == "done"), None)

        assert error_event is not None
        assert done_event is not None
        assert done_event.get("llm_used") is False
        assert isinstance(done_event.get("llm_error"), str) and str(done_event["llm_error"]).strip()
        assert "retrieval-only" not in body.lower()
    finally:
        set_config(None)
        set_fusion(None)
        if old_openai is not None:
            os.environ["OPENAI_API_KEY"] = old_openai
        else:
            os.environ.pop("OPENAI_API_KEY", None)
        if old_openrouter is not None:
            os.environ["OPENROUTER_API_KEY"] = old_openrouter
        else:
            os.environ.pop("OPENROUTER_API_KEY", None)
