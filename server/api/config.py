from __future__ import annotations

import asyncio
import importlib.util
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from server.config import load_config as load_global_config
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import (
    CorpusScope,
    MCPHTTPTransportStatus,
    MCPRagSearchResponse,
    MCPRagSearchResult,
    MCPStatusResponse,
    TriBridConfig,
)
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.config_store import reset_config as reset_scoped_config
from server.services.config_store import save_config as save_scoped_config

router = APIRouter(tags=["config"])

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()

_SECRETS_CHECK_ALLOWLIST = {
    # Provider secrets
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "COHERE_API_KEY",
    "VOYAGE_API_KEY",
    "JINA_API_KEY",
    # Integrations (UI surfaces these; backend does not expose values)
    "LANGTRACE_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_API_KEY",
    "NETLIFY_API_KEY",
    "GRAFANA_API_KEY",
    "SLACK_WEBHOOK_URL",
    "DISCORD_WEBHOOK_URL",
}

_CONFIG_WRITE_LOCKS: dict[str | None, asyncio.Lock] = {}


def _get_config_write_lock(repo_id: str | None) -> asyncio.Lock:
    # Serialize config writes per corpus to avoid lost updates when multiple PATCH
    # requests race across sections for the same corpus.
    lock = _CONFIG_WRITE_LOCKS.get(repo_id)
    if lock is None:
        lock = asyncio.Lock()
        _CONFIG_WRITE_LOCKS[repo_id] = lock
    return lock


def _norm_components(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        c = str(item or "").strip().upper()
        if c in {"GEN", "EMB", "RERANK"}:
            out.add(c)
    return out


def _load_catalog_models_for_validation() -> list[dict[str, Any]]:
    try:
        from server.api.models import _catalog_models, _load_catalog

        return _catalog_models(_load_catalog())
    except Exception:
        return []


def _catalog_capabilities_for_model(
    catalog_models: list[dict[str, Any]],
    *,
    model_value: str,
    provider_hint: str | None = None,
) -> set[str]:
    raw = str(model_value or "").strip()
    if not raw:
        return set()

    # Ragweld uses an in-process generation route.
    if raw.lower().startswith("ragweld:"):
        return {"GEN"}

    # Prefix-based route override format (local:/openrouter:).
    if ":" in raw:
        prefix, rest = raw.split(":", 1)
        p = prefix.strip().lower()
        if p == "ragweld":
            return {"GEN"}
        if p in {"local", "openrouter"}:
            raw = rest.strip()

    model_core = raw
    scoped_provider = str(provider_hint or "").strip().lower() or None
    if "/" in raw:
        pfx, model_name = raw.split("/", 1)
        pfx = pfx.strip().lower()
        model_core = model_name.strip()
        if pfx:
            scoped_provider = pfx

    if not model_core:
        return set()

    caps: set[str] = set()
    if scoped_provider:
        for row in catalog_models:
            provider = str(row.get("provider") or "").strip().lower()
            model = str(row.get("model") or "").strip()
            if provider == scoped_provider and model == model_core:
                caps |= _norm_components(row.get("components"))
    if caps:
        return caps

    # Fallback: model-only lookup (for unqualified model ids).
    for row in catalog_models:
        model = str(row.get("model") or "").strip()
        if model == model_core:
            caps |= _norm_components(row.get("components"))
    return caps


def _validate_capability(
    catalog_models: list[dict[str, Any]],
    *,
    field_name: str,
    model_value: str,
    required_component: str,
    provider_hint: str | None = None,
) -> None:
    model_str = str(model_value or "").strip()
    if not model_str:
        return

    caps = _catalog_capabilities_for_model(
        catalog_models,
        model_value=model_str,
        provider_hint=provider_hint,
    )
    # Unknown/custom models are allowed; we only reject known-incompatible assignments.
    if not caps:
        return
    if required_component in caps:
        return

    found = ", ".join(sorted(caps))
    raise HTTPException(
        status_code=422,
        detail=(
            f"Invalid model capability for {field_name}: "
            f"'{model_str}' supports [{found}] but this field requires [{required_component}]."
        ),
    )


def _validate_model_capabilities(config: TriBridConfig) -> None:
    catalog_models = _load_catalog_models_for_validation()
    if not catalog_models:
        return

    # Generation fields (must be GEN-capable).
    _validate_capability(
        catalog_models,
        field_name="generation.gen_model",
        model_value=str(config.generation.gen_model or ""),
        required_component="GEN",
    )
    _validate_capability(
        catalog_models,
        field_name="generation.enrich_model",
        model_value=str(config.generation.enrich_model or ""),
        required_component="GEN",
    )
    _validate_capability(
        catalog_models,
        field_name="generation.enrich_model_ollama",
        model_value=str(config.generation.enrich_model_ollama or ""),
        required_component="GEN",
    )
    _validate_capability(
        catalog_models,
        field_name="generation.gen_model_http",
        model_value=str(config.generation.gen_model_http or ""),
        required_component="GEN",
    )
    _validate_capability(
        catalog_models,
        field_name="generation.gen_model_mcp",
        model_value=str(config.generation.gen_model_mcp or ""),
        required_component="GEN",
    )
    _validate_capability(
        catalog_models,
        field_name="generation.gen_model_cli",
        model_value=str(config.generation.gen_model_cli or ""),
        required_component="GEN",
    )
    _validate_capability(
        catalog_models,
        field_name="chat.multimodal.vision_model_override",
        model_value=str(config.chat.multimodal.vision_model_override or ""),
        required_component="GEN",
    )

    # Embedding fields (must be EMB-capable).
    embedding_provider = str(config.embedding.embedding_type or "").strip().lower() or None
    if embedding_provider == "voyage":
        emb_model = str(config.embedding.voyage_model or "")
    elif embedding_provider == "mlx":
        emb_model = str(getattr(config.embedding, "embedding_model_mlx", "") or "")
    elif embedding_provider in {"local", "huggingface", "ollama"}:
        emb_model = str(config.embedding.embedding_model_local or "")
    else:
        emb_model = str(config.embedding.embedding_model or "")
    _validate_capability(
        catalog_models,
        field_name="embedding.*",
        model_value=emb_model,
        required_component="EMB",
        provider_hint=embedding_provider,
    )

    # Reranker fields (must be RERANK-capable).
    _validate_capability(
        catalog_models,
        field_name="reranking.reranker_cloud_model",
        model_value=str(config.reranking.reranker_cloud_model or ""),
        required_component="RERANK",
        provider_hint=str(config.reranking.reranker_cloud_provider or "").strip().lower() or None,
    )


@router.get("/config", response_model=TriBridConfig)
async def get_config(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        return await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/config", response_model=TriBridConfig)
async def update_config(
    config: TriBridConfig,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        async with _get_config_write_lock(repo_id):
            _validate_model_capabilities(config)
            return await save_scoped_config(config, repo_id=repo_id)
    except HTTPException:
        raise
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/config/{section}", response_model=TriBridConfig)
async def update_config_section(
    section: str,
    updates: dict[str, Any],
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    async with _get_config_write_lock(repo_id):
        try:
            config = await load_scoped_config(repo_id=repo_id)
        except CorpusNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

        # Only allow patching known top-level sections
        if section not in TriBridConfig.model_fields:
            raise HTTPException(status_code=404, detail=f"Unknown config section: {section}")

        # Build a new config dict with patched section and re-validate (ensures Field constraints apply)
        base = config.model_dump()
        current_section = base.get(section)
        if not isinstance(current_section, dict):
            raise HTTPException(status_code=400, detail=f"Config section '{section}' is not patchable")
        if not isinstance(updates, dict):
            raise HTTPException(status_code=422, detail="PATCH body must be a JSON object")

        merged = {**current_section, **updates}
        base[section] = merged

        try:
            new_config = TriBridConfig.model_validate(base)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        _validate_model_capabilities(new_config)

        try:
            return await save_scoped_config(new_config, repo_id=repo_id)
        except CorpusNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/config/reset", response_model=TriBridConfig)
async def reset_config(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        async with _get_config_write_lock(repo_id):
            return await reset_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/secrets/check")
async def check_secrets(keys: str = Query(..., description="Comma-separated env var names")) -> dict[str, bool]:
    """Return which secret env vars are configured (never returns values)."""
    names = [k.strip() for k in (keys or "").split(",") if k.strip()]
    if not names:
        return {}

    invalid = [name for name in names if name not in _SECRETS_CHECK_ALLOWLIST]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported secret key(s): {', '.join(sorted(set(invalid)))}",
        )

    # Use explicit getenv calls (no dynamic env lookups) to keep env usage auditable/"LAW"-compliant.
    status = {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "OPENROUTER_API_KEY": bool(os.getenv("OPENROUTER_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
        "GOOGLE_API_KEY": bool(os.getenv("GOOGLE_API_KEY")),
        "COHERE_API_KEY": bool(os.getenv("COHERE_API_KEY")),
        "VOYAGE_API_KEY": bool(os.getenv("VOYAGE_API_KEY")),
        "JINA_API_KEY": bool(os.getenv("JINA_API_KEY")),
        "LANGTRACE_API_KEY": bool(os.getenv("LANGTRACE_API_KEY")),
        "LANGCHAIN_API_KEY": bool(os.getenv("LANGCHAIN_API_KEY")),
        "LANGSMITH_API_KEY": bool(os.getenv("LANGSMITH_API_KEY")),
        "NETLIFY_API_KEY": bool(os.getenv("NETLIFY_API_KEY")),
        "GRAFANA_API_KEY": bool(os.getenv("GRAFANA_API_KEY")),
        "SLACK_WEBHOOK_URL": bool(os.getenv("SLACK_WEBHOOK_URL")),
        "DISCORD_WEBHOOK_URL": bool(os.getenv("DISCORD_WEBHOOK_URL")),
    }

    return {name: status[name] for name in names}


@router.get("/mcp/status", response_model=MCPStatusResponse)
async def mcp_status(request: Request) -> MCPStatusResponse:
    """Return status for MCP transports built into TriBridRAG.

    Notes:
    - The stdio transport is typically client-spawned (no always-on daemon).
    - HTTP transports may be added later; this endpoint is forward-compatible.
    """
    details: list[str] = []
    python_stdio_available = False
    python_http: MCPHTTPTransportStatus | None = None

    try:
        python_stdio_available = importlib.util.find_spec("mcp") is not None
    except Exception as e:
        python_stdio_available = False
        details.append(f"Error checking Python MCP package availability: {e}")

    if python_stdio_available:
        details.append("Python stdio MCP transport is available (client-spawned; no daemon).")
    else:
        details.append("Python stdio MCP transport not available (Python package 'mcp' not installed).")

    # Python Streamable HTTP transport is embedded under cfg.mcp.mount_path (same FastAPI app).
    try:
        cfg = load_global_config()
        if cfg.mcp.enabled:
            if python_stdio_available:
                host = request.url.hostname or "127.0.0.1"
                port = request.url.port or (443 if request.url.scheme == "https" else 80)
                # Starlette mounts require a trailing slash for the mount root.
                # Advertise the canonical URL that does not redirect for POST.
                path = str(cfg.mcp.mount_path).rstrip("/") + "/"
                python_http = MCPHTTPTransportStatus(
                    host=str(host),
                    port=int(port),
                    path=path,
                    running=True,
                )
                details.append(
                    f"Python HTTP MCP transport is enabled and mounted at {cfg.mcp.mount_path} "
                    f"(connect to http://{host}:{port}{path})."
                )
            else:
                details.append(
                    "Python HTTP MCP transport is configured as enabled, but the 'mcp' package is not installed."
                )
        else:
            details.append("Python HTTP MCP transport is disabled (config.mcp.enabled=false).")
    except Exception as e:
        details.append(f"Error resolving MCP HTTP status: {e}")

    return MCPStatusResponse(
        python_http=python_http,
        node_http=None,
        python_stdio_available=python_stdio_available,
        details=details,
    )


@router.get("/mcp/rag_search", response_model=MCPRagSearchResponse)
async def mcp_rag_search(
    q: str = Query(..., description="Search query"),
    top_k: int | None = Query(default=None, ge=1, le=100, description="Number of results to return"),
    force_local: bool = Query(False, description="Legacy flag (ignored)"),
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> MCPRagSearchResponse:
    """Legacy debug endpoint: run tri-brid search and return compact results.

    Notes:
    - This endpoint exists for UI/debug tooling migrated from the legacy JS modules.
    - It returns HTTP 200 with an `error` field on failure (so callers can display the message).
    """
    _ = force_local  # ignored (legacy param)
    repo_id = scope.resolved_repo_id
    if not repo_id:
        return MCPRagSearchResponse(
            results=[],
            error="Missing corpus_id/repo_id (pass ?repo=... or ?corpus_id=...)",
        )
    if not q.strip():
        return MCPRagSearchResponse(results=[], error="Query must not be empty")

    try:
        # Validate corpus exists (avoid implicitly creating new corpora/configs).
        global_cfg = load_global_config()
        pg = PostgresClient(global_cfg.indexing.postgres_url)
        await pg.connect()
        corpus = await pg.get_corpus(repo_id)
        if corpus is None:
            return MCPRagSearchResponse(results=[], error=f"Corpus not found: {repo_id}")

        cfg = await load_scoped_config(repo_id=repo_id)
        fusion = TriBridFusion(vector=None, sparse=None, graph=None)
        effective_top_k = int(top_k or cfg.mcp.default_top_k)
        matches = await fusion.search(
            [repo_id],
            q,
            cfg.fusion,
            include_vector=True,
            include_sparse=True,
            include_graph=True,
            top_k=effective_top_k,
        )

        results = [
            MCPRagSearchResult(
                file_path=m.file_path,
                start_line=int(m.start_line),
                end_line=int(m.end_line),
                rerank_score=float(m.score),
            )
            for m in matches
        ]
        return MCPRagSearchResponse(results=results, error=None)
    except Exception as e:
        return MCPRagSearchResponse(results=[], error=str(e))
