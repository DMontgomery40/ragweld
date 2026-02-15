"""Chat API should always respond even with no providers configured."""

from __future__ import annotations

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
    for p in cfg.chat.local_models.providers:
        p.enabled = False
    return cfg


@pytest.mark.asyncio
async def test_chat_returns_200_without_providers(client: AsyncClient) -> None:
    old_openai = os.environ.pop("OPENAI_API_KEY", None)
    old_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)

    cfg = _disable_all_chat_providers(TriBridConfig())
    fusion = _FakeFusion(
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
                metadata={},
            )
        ]
    )

    try:
        set_config(cfg)
        set_fusion(fusion)

        resp = await client.post(
            "/api/chat",
            json={"message": "hello", "sources": {"corpus_ids": ["test-repo"]}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("debug", {}).get("llm_used") is False
        assert isinstance(data.get("debug", {}).get("llm_error"), str)
        assert isinstance(data.get("message", {}).get("content"), str) and data["message"]["content"].strip()
        assert isinstance(data.get("sources"), list) and len(data["sources"]) >= 1
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

