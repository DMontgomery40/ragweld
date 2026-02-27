"""Integration tests for semantic cache behavior on API endpoints."""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig


def _postgres_available() -> bool:
    return bool(os.getenv("POSTGRES_DSN") or os.getenv("POSTGRES_HOST"))


async def _seed_repo(pg: PostgresClient, repo_id: str) -> None:
    await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")

    cfg = TriBridConfig()
    cfg.semantic_cache.enabled = 1
    cfg.semantic_cache.mode = "read_write"
    cfg.semantic_cache.min_query_chars = 3
    cfg.semantic_cache.similarity_threshold_search = 0.10
    cfg.semantic_cache.ttl_seconds_search = 3600

    await pg.upsert_corpus_config_json(repo_id, cfg.model_dump(mode="serialization"))

    chunks = [
        Chunk(
            chunk_id="c1",
            content="login controller handles authentication and session tokens",
            file_path="src/auth/login_controller.py",
            start_line=1,
            end_line=1,
            language="python",
            token_count=9,
            embedding=None,
            summary=None,
            metadata={"kind": "semantic-cache-test"},
        )
    ]
    await pg.upsert_fts(repo_id, chunks, ts_config="english")


@pytest.mark.asyncio
async def test_search_semantic_cache_exact_then_hit(client: AsyncClient) -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_semcache_exact_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await _seed_repo(pg, repo_id)

        req = {
            "query": "login controller",
            "repo_id": repo_id,
            "top_k": 5,
            "include_vector": False,
            "include_sparse": True,
            "include_graph": False,
        }
        first = await client.post("/api/search", json=req)
        assert first.status_code == 200
        d1 = first.json()
        assert d1.get("debug", {}).get("cache_hit") is False
        assert isinstance(d1.get("matches"), list) and len(d1["matches"]) >= 1

        second = await client.post("/api/search", json=req)
        assert second.status_code == 200
        d2 = second.json()
        assert d2.get("debug", {}).get("cache_hit") is True
        assert d2.get("debug", {}).get("cache_match_type") == "exact"
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_search_semantic_cache_semantic_hit_and_bypass_mode(client: AsyncClient) -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_semcache_sem_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await _seed_repo(pg, repo_id)

        prime = await client.post(
            "/api/search",
            json={
                "query": "login controller",
                "repo_id": repo_id,
                "top_k": 5,
                "include_vector": False,
                "include_sparse": True,
                "include_graph": False,
            },
        )
        assert prime.status_code == 200

        semantic_hit = await client.post(
            "/api/search",
            json={
                "query": "controller for login auth",
                "repo_id": repo_id,
                "top_k": 5,
                "include_vector": False,
                "include_sparse": True,
                "include_graph": False,
            },
        )
        assert semantic_hit.status_code == 200
        d_sem = semantic_hit.json()
        assert d_sem.get("debug", {}).get("cache_hit") is True
        assert d_sem.get("debug", {}).get("cache_match_type") in {"semantic", "exact"}

        # Bypass should skip writes; two bypass calls should not prime cache.
        bypass_req = {
            "query": "session tokens",
            "repo_id": repo_id,
            "top_k": 5,
            "include_vector": False,
            "include_sparse": True,
            "include_graph": False,
            "cache_mode": "bypass",
        }
        b1 = await client.post("/api/search", json=bypass_req)
        b2 = await client.post("/api/search", json=bypass_req)
        assert b1.status_code == 200 and b2.status_code == 200
        assert b1.json().get("debug", {}).get("cache_hit") is False
        assert b2.json().get("debug", {}).get("cache_hit") is False

        # First default should still miss; second default should hit.
        default_req = dict(bypass_req)
        default_req["cache_mode"] = "default"
        d1 = await client.post("/api/search", json=default_req)
        d2 = await client.post("/api/search", json=default_req)
        assert d1.status_code == 200 and d2.status_code == 200
        assert d1.json().get("debug", {}).get("cache_hit") is False
        assert d2.json().get("debug", {}).get("cache_hit") is True
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass
