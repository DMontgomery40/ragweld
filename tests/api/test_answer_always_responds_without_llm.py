"""API tests for always-answer behavior (LLM optional)."""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.qdrant_store import QdrantChunkStore

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_qdrant]


def _disable_all_chat_providers(cfg: TriBridConfig) -> TriBridConfig:
    # Ensure provider routing fails fast (no network calls) so the endpoint
    # deterministically falls back to retrieval-only.
    cfg.chat.litellm.enabled = False
    return cfg


@pytest.mark.asyncio
async def test_answer_returns_200_without_any_llm_keys(client: AsyncClient) -> None:
    # Ensure env keys don't accidentally route cloud-direct.
    old_litellm = os.environ.pop("LITELLM_API_KEY", None)

    repo_id = f"test_ans_nollm_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")

        cfg = _disable_all_chat_providers(load_config())
        await pg.upsert_corpus_config_json(repo_id, cfg.model_dump(mode="serialization"))
        qdrant = QdrantChunkStore(cfg)

        ch = Chunk(
            chunk_id="c1",
            content="login controller handles authentication",
            file_path="src/auth/login_controller.py",
            start_line=1,
            end_line=1,
            language="python",
            token_count=5,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        )
        await pg.upsert_chunks(repo_id, [ch])
        await qdrant.upsert_chunks(repo_id, [ch], embedding_dim=int(cfg.embedding.embedding_dim))

        resp = await client.post(
            "/api/answer",
            json={
                "query": "login controller",
                "repo_id": repo_id,
                "top_k": 5,
                "include_vector": False,
                "include_sparse": True,
                "include_graph": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("answer"), str) and data["answer"].strip()
        assert data.get("model") == "retrieval-only"
        assert isinstance(data.get("sources"), list) and len(data["sources"]) >= 1
        assert data.get("sources")[0].get("file_path") == "src/auth/login_controller.py"
        assert data.get("debug", {}).get("llm_used") is False
        assert isinstance(data.get("debug", {}).get("llm_error"), str)
    finally:
        try:
            await QdrantChunkStore(load_config()).delete_corpus(repo_id)
        except Exception:
            pass
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass
        if old_litellm is not None:
            os.environ["LITELLM_API_KEY"] = old_litellm
        else:
            os.environ.pop("LITELLM_API_KEY", None)
