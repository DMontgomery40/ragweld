"""MCP tool implementations for TriBridRAG."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Literal

from mcp.server.fastmcp import FastMCP

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import AnswerResponse, ChunkMatch, Corpus, MCPConfig
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import get_config as load_scoped_config
from server.services.answer_service import answer_best_effort

MCPMode = Literal["tribrid", "dense_only", "sparse_only", "graph_only"]


def _mode_to_flags(mode: MCPMode) -> tuple[bool, bool, bool]:
    if mode == "tribrid":
        return True, True, True
    if mode == "dense_only":
        return True, False, False
    if mode == "sparse_only":
        return False, True, False
    return False, False, True


async def _ensure_corpus_exists(repo_id: str) -> None:
    global_cfg = load_config()
    pg = PostgresClient(global_cfg.indexing.postgres_url)
    await pg.connect()
    corpus = await pg.get_corpus(repo_id)
    if corpus is None:
        raise ValueError(f"Corpus not found: {repo_id}")


def register_mcp_tools(mcp: FastMCP, cfg: MCPConfig) -> None:
    """Register all MCP tools on a FastMCP server."""

    @mcp.tool()
    async def search(
        query: str,
        corpus_id: str,
        mode: MCPMode | None = None,
        top_k: int | None = None,
    ) -> list[ChunkMatch]:
        """Search a corpus with tri-brid retrieval (vector + sparse + graph)."""
        if not query.strip():
            raise ValueError("Query must not be empty")

        await _ensure_corpus_exists(corpus_id)
        scoped_cfg = await load_scoped_config(repo_id=corpus_id)

        effective_mode: MCPMode = mode or cfg.default_mode
        include_vector, include_sparse, include_graph = _mode_to_flags(effective_mode)
        effective_top_k = int(top_k or cfg.default_top_k)

        fusion = TriBridFusion(vector=None, sparse=None, graph=None)
        return await fusion.search(
            [corpus_id],
            query,
            scoped_cfg.fusion,
            include_vector=include_vector,
            include_sparse=include_sparse,
            include_graph=include_graph,
            top_k=effective_top_k,
        )

    @mcp.tool()
    async def answer(
        query: str,
        corpus_id: str,
        mode: MCPMode | None = None,
        top_k: int | None = None,
    ) -> AnswerResponse:
        """Answer a question using tri-brid retrieval + an LLM."""
        if not query.strip():
            raise ValueError("Query must not be empty")

        await _ensure_corpus_exists(corpus_id)
        scoped_cfg = await load_scoped_config(repo_id=corpus_id)

        effective_mode: MCPMode = mode or cfg.default_mode
        include_vector, include_sparse, include_graph = _mode_to_flags(effective_mode)
        effective_top_k = int(top_k or cfg.default_top_k)

        fusion = TriBridFusion(vector=None, sparse=None, graph=None)

        t0 = time.perf_counter()
        text, sources, provider_info, debug = await answer_best_effort(
            query=query,
            corpus_id=corpus_id,
            config=scoped_cfg,
            fusion=fusion,
            include_vector=include_vector,
            include_sparse=include_sparse,
            include_graph=include_graph,
            top_k=effective_top_k,
        )
        dt_ms = (time.perf_counter() - t0) * 1000.0

        # Note: The current /api/answer endpoint also reports tokens_used=0 (provider-specific).
        return AnswerResponse(
            query=query,
            answer=text,
            sources=sources,
            model=(provider_info.model if (provider_info is not None and debug.llm_used) else "retrieval-only"),
            tokens_used=0,
            latency_ms=float(dt_ms),
            debug=debug,
        )

    @mcp.tool()
    async def list_corpora() -> list[Corpus]:
        """List available corpora (repo_id == corpus_id)."""
        global_cfg = load_config()
        pg = PostgresClient(global_cfg.indexing.postgres_url)
        await pg.connect()
        rows = await pg.list_corpora()

        out: list[Corpus] = []
        for r in rows:
            meta = r.get("meta") or {}
            out.append(
                Corpus(
                    repo_id=str(r["repo_id"]),
                    name=str(r["name"]),
                    path=str(r["path"]),
                    slug=(meta.get("slug") or str(r["repo_id"])),
                    branch=meta.get("branch"),
                    default=meta.get("default"),
                    exclude_paths=meta.get("exclude_paths"),
                    keywords=meta.get("keywords"),
                    path_boosts=meta.get("path_boosts"),
                    layer_bonuses=meta.get("layer_bonuses"),
                    description=r.get("description"),
                    created_at=r.get("created_at") or datetime.now(UTC),
                    last_indexed=r.get("last_indexed"),
                )
            )
        return out
