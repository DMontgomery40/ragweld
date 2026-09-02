"""MCP tool implementations for TriBridRAG."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from server.config import load_config
from server.db.postgres import PostgresClient
from server.dependency_errors import DependencyUnavailableError
from server.models.tribrid_config_model import (
    AnswerResponse,
    ChunkMatch,
    Corpus,
    DependencyUnavailableDetail,
    MCPConfig,
    MCPSearchToolResult,
    RequiredRetrievalLegFailureDetail,
    AnswerRetrievalFailureDetail,
    GenerationUnavailableDetail,
    MCPAnswerToolResult,
    RerankerFailureDetail,
    RetrievalContractMismatchDetail,
)
from server.chat.generation_failure import generation_unavailable_detail
from server.dependency_errors import (
    DependencyName,
    is_neo4j_unavailable,
    is_postgres_unavailable,
    is_required_dependency_unavailable,
)
from server.retrieval.errors import (
    AnswerRetrievalFailedError,
    RequiredRetrievalLegError,
    RerankerFailedError,
    RetrievalContractMismatchError,
)
from server.retrieval.fusion import TriBridFusion
from server.services.answer_service import answer_best_effort
from server.services.config_store import get_config as load_scoped_config

MCPMode = Literal["tribrid", "dense_only", "sparse_only", "graph_only"]


def _answer_tool_result(
    *,
    result: AnswerResponse | None = None,
    error: (
        DependencyUnavailableDetail
        | RequiredRetrievalLegFailureDetail
        | RerankerFailureDetail
        | RetrievalContractMismatchDetail
        | AnswerRetrievalFailureDetail
        | GenerationUnavailableDetail
        | None
    ) = None,
) -> CallToolResult:
    payload = MCPAnswerToolResult(result=result, error=error).model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, separators=(",", ":")))],
        structuredContent=payload,
        isError=error is not None,
    )


def _search_tool_result(
    *,
    rows: list[ChunkMatch] | None = None,
    error: (
        DependencyUnavailableDetail
        | RequiredRetrievalLegFailureDetail
        | RerankerFailureDetail
        | RetrievalContractMismatchDetail
        | None
    ) = None,
) -> CallToolResult:
    payload = MCPSearchToolResult(result=rows, error=error).model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, separators=(",", ":")))],
        structuredContent=payload,
        isError=error is not None,
    )


def _dependency_error_detail(exc: DependencyUnavailableError) -> DependencyUnavailableDetail:
    dependency = str(exc.dependency)
    return DependencyUnavailableDetail(
        dependency=exc.dependency,
        operation=exc.operation,
        message=f"The required {dependency} dependency is unavailable.",
        operator_hint=(
            f"Restore the {dependency} runtime used by {exc.operation}, then retry. "
            "Ragweld did not substitute a partial retrieval result."
        ),
    )


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
    ) -> Annotated[CallToolResult, MCPSearchToolResult]:
        """Search a corpus with tri-brid retrieval (vector + sparse + graph)."""
        if not query.strip():
            raise ValueError("Query must not be empty")

        effective_mode: MCPMode = mode or cfg.default_mode
        include_vector, include_sparse, include_graph = _mode_to_flags(effective_mode)
        effective_top_k = int(top_k or cfg.default_top_k)

        fusion = TriBridFusion()
        # The corpus and config lookups sit under the same typed guard as retrieval, so a
        # store outage there is the typed dependency error, not FastMCP's generic text.
        try:
            try:
                await _ensure_corpus_exists(corpus_id)
                scoped_cfg = await load_scoped_config(repo_id=corpus_id)
            except (ConnectionError, TimeoutError, OSError) as exc:
                # A raw driver transport failure at the Postgres lookup boundary, typed the
                # way the API's Postgres boundary types it.
                raise DependencyUnavailableError("postgres", "MCP search corpus lookup") from exc
            rows = await fusion.search(
                [corpus_id],
                query,
                scoped_cfg.fusion,
                include_vector=include_vector,
                include_sparse=include_sparse,
                include_graph=include_graph,
                top_k=effective_top_k,
            )
        except RetrievalContractMismatchError as exc:
            return _search_tool_result(
                error=RetrievalContractMismatchDetail.model_validate(exc.to_detail())
            )
        except RequiredRetrievalLegError as exc:
            return _search_tool_result(
                error=RequiredRetrievalLegFailureDetail.model_validate(exc.to_detail())
            )
        except RerankerFailedError as exc:
            return _search_tool_result(error=RerankerFailureDetail.model_validate(exc.to_detail()))
        except DependencyUnavailableError as exc:
            return _search_tool_result(error=_dependency_error_detail(exc))
        except ValueError:
            raise  # "Corpus not found": the tool's own argument error, not a runtime failure
        except Exception as exc:
            if is_required_dependency_unavailable(exc):
                dependency: DependencyName = (
                    "postgres" if is_postgres_unavailable(exc) else "neo4j" if is_neo4j_unavailable(exc) else "qdrant"
                )
                return _search_tool_result(
                    error=_dependency_error_detail(
                        DependencyUnavailableError(dependency=dependency, operation="MCP search retrieval")
                    )
                )
            raise
        return _search_tool_result(rows=rows)

    @mcp.tool()
    async def answer(
        query: str,
        corpus_id: str,
        mode: MCPMode | None = None,
        top_k: int | None = None,
    ) -> Annotated[CallToolResult, MCPAnswerToolResult]:
        """Answer a question using tri-brid retrieval + an LLM."""
        if not query.strip():
            raise ValueError("Query must not be empty")

        effective_mode: MCPMode = mode or cfg.default_mode
        include_vector, include_sparse, include_graph = _mode_to_flags(effective_mode)
        effective_top_k = int(top_k or cfg.default_top_k)

        fusion = TriBridFusion()

        t0 = time.perf_counter()
        # Every failure is a typed tool error (isError=true), never an answer without context
        # or a "retrieval-only" text: the same boundary contract as /api/answer. The corpus
        # and config lookups are inside the same guard, so a store outage there is typed too.
        try:
            try:
                await _ensure_corpus_exists(corpus_id)
                scoped_cfg = await load_scoped_config(repo_id=corpus_id)
            except (ConnectionError, TimeoutError, OSError) as exc:
                raise DependencyUnavailableError("postgres", "MCP answer corpus lookup") from exc
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
        except RetrievalContractMismatchError as exc:
            return _answer_tool_result(error=RetrievalContractMismatchDetail.model_validate(exc.to_detail()))
        except RequiredRetrievalLegError as exc:
            return _answer_tool_result(error=RequiredRetrievalLegFailureDetail.model_validate(exc.to_detail()))
        except RerankerFailedError as exc:
            return _answer_tool_result(error=RerankerFailureDetail.model_validate(exc.to_detail()))
        except AnswerRetrievalFailedError as exc:
            return _answer_tool_result(
                error=AnswerRetrievalFailureDetail.model_validate(exc.to_detail(operation="MCP answer retrieval"))
            )
        except DependencyUnavailableError as exc:
            return _answer_tool_result(error=_dependency_error_detail(exc))
        except ValueError:
            raise  # "Corpus not found": the tool's own argument error, not a runtime failure
        except Exception as exc:
            if is_required_dependency_unavailable(exc):
                dependency: DependencyName = (
                    "postgres" if is_postgres_unavailable(exc) else "neo4j" if is_neo4j_unavailable(exc) else "qdrant"
                )
                return _answer_tool_result(
                    error=_dependency_error_detail(
                        DependencyUnavailableError(dependency=dependency, operation="MCP answer retrieval")
                    )
                )
            return _answer_tool_result(error=generation_unavailable_detail(exc, operation="MCP answer generation"))
        dt_ms = (time.perf_counter() - t0) * 1000.0

        if provider_info is None or not debug.llm_used:
            return _answer_tool_result(
                error=generation_unavailable_detail(
                    RuntimeError("answer completed without a generation provider"),
                    operation="MCP answer generation",
                )
            )
        # Note: The current /api/answer endpoint also reports tokens_used=0 (provider-specific).
        return _answer_tool_result(
            result=AnswerResponse(
                query=query,
                answer=text,
                sources=sources,
                model=provider_info.model,
                tokens_used=0,
                latency_ms=float(dt_ms),
                debug=debug,
            )
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
