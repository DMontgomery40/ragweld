from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import os
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    dependency_unavailable_http_exception,
    raise_postgres_unavailable_if_applicable,
    raise_required_dependency_unavailable_if_applicable,
)
from server.api.retrieval_errors import (
    RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES,
)
from server.chat.prompt_budget import context_window_for_alias
from server.config import load_config as load_global_config
from server.config_control_plane import (
    allowed_secret_env_vars,
    build_config_readiness_response,
    build_config_registry_response,
)
from server.config_redaction import (
    SecretMarkerWriteError,
    redact_config_secrets,
    redact_registry_defaults,
    restore_config_secrets,
)
from server.db.postgres import PostgresClient
from server.dependency_errors import DependencyUnavailableError
from server.gateway_catalog import gateway_rows_snapshot
from server.indexing.generations import qdrant_collection_of
from server.lineage import ensure_current_bundle
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import (
    ConfigReadinessResponse,
    ConfigRegistryResponse,
    CorpusScope,
    DependencyUnavailableDetail,
    MCPConfig,
    MCPHTTPTransportStatus,
    MCPProbeRequest,
    MCPProbeResponse,
    MCPStatusResponse,
    MCPToolInfo,
    ModelValidationResult,
    ModelValidationWarning,
    RequiredRetrievalLegFailureDetail,
    RetrievalContractMismatchDetail,
    TriBridConfig,
)
from server.retrieval.contracts import (
    SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS,
    dense_contract_from_config,
    provider_requires_tokenizer,
    sparse_contract_from_config,
)
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.config_store import reset_config as reset_scoped_config
from server.services.config_store import save_config as save_scoped_config

router = APIRouter(tags=["config"], responses=DEPENDENCY_UNAVAILABLE_RESPONSES)

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()

_CONFIG_WRITE_LOCKS: dict[str | None, asyncio.Lock] = {}


async def _load_config_for_api(repo_id: str | None, *, boundary: str) -> TriBridConfig:
    try:
        return await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise


def _get_config_write_lock(repo_id: str | None) -> asyncio.Lock:
    # Serialize config writes per corpus to avoid lost updates when multiple PATCH
    # requests race across sections for the same corpus.
    lock = _CONFIG_WRITE_LOCKS.get(repo_id)
    if lock is None:
        lock = asyncio.Lock()
        _CONFIG_WRITE_LOCKS[repo_id] = lock
    return lock


def _deep_merge_dicts(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge nested PATCH payloads into a config section."""
    merged: dict[str, Any] = dict(base)
    for key, value in updates.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(current, value)
        else:
            merged[key] = value
    return merged


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

    model_core = raw
    scoped_provider = str(provider_hint or "").strip().lower() or None
    known_providers = {
        str(row.get("provider") or "").strip().lower()
        for row in catalog_models
        if str(row.get("provider") or "").strip()
    }
    if "/" in raw:
        pfx, model_name = raw.split("/", 1)
        pfx = pfx.strip().lower()
        # Treat provider/model only when the prefix is a known provider.
        # Do not split regular model ids that contain slashes (for example
        # mlx-community/all-MiniLM-L6-v2-4bit).
        if pfx and pfx in known_providers:
            model_core = model_name.strip()
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


def _resolve_embedding_model(config: TriBridConfig) -> str:
    provider = str(config.embedding.embedding_type or "").strip().lower()
    if provider == "voyage":
        return str(config.embedding.voyage_model or "")
    if provider == "mlx":
        return str(getattr(config.embedding, "embedding_model_mlx", "") or "")
    if provider in {"local", "huggingface", "ollama"}:
        return str(config.embedding.embedding_model_local or "")
    return str(config.embedding.embedding_model or "")


def _validate_capability(
    catalog_models: list[dict[str, Any]],
    *,
    field_name: str,
    model_value: str,
    required_component: str,
    provider_hint: str | None = None,
    strict_unknown: bool = False,
) -> None:
    model_str = str(model_value or "").strip()
    if not model_str:
        return

    caps = _catalog_capabilities_for_model(
        catalog_models,
        model_value=model_str,
        provider_hint=provider_hint,
    )
    if not caps:
        if strict_unknown:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown model for {field_name}: '{model_str}'. "
                    "Select a catalog model for this field."
                ),
            )
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
    _validate_embedding_runtime_support(config)
    _validate_embedding_tokenization_compat(config)

    for field_name, value in (
        ("generation.gen_model", config.generation.gen_model),
        ("generation.enrich_model", config.generation.enrich_model),
        ("generation.gen_model_http", config.generation.gen_model_http),
        ("generation.gen_model_mcp", config.generation.gen_model_mcp),
        ("generation.gen_model_cli", config.generation.gen_model_cli),
        ("chat.multimodal.vision_model_override", config.chat.multimodal.vision_model_override),
    ):
        alias = str(value or "").strip()
        if alias and re.fullmatch(r"[A-Za-z0-9._-]+", alias) is None:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid LiteLLM alias for {field_name}: '{alias}'. Use a configured gateway alias.",
            )

    catalog_models = _load_catalog_models_for_validation()
    if not catalog_models:
        return

    # Embedding fields (must be EMB-capable).
    embedding_provider = str(config.embedding.embedding_type or "").strip().lower() or None
    emb_model = _resolve_embedding_model(config)
    strict_unknown_embedding = str(
        config.embedding.embedding_backend or ""
    ).strip().lower() == "provider" and not getattr(config.indexing, "skip_dense", False)
    _validate_capability(
        catalog_models,
        field_name="embedding.*",
        model_value=emb_model,
        required_component="EMB",
        provider_hint=embedding_provider,
        strict_unknown=strict_unknown_embedding,
    )

    # Reranker fields (must be RERANK-capable).
    _validate_capability(
        catalog_models,
        field_name="reranking.reranker_cloud_model",
        model_value=str(config.reranking.reranker_cloud_model or ""),
        required_component="RERANK",
        provider_hint=str(config.reranking.reranker_cloud_provider or "").strip().lower() or None,
    )


def _validate_embedding_runtime_support(config: TriBridConfig) -> None:
    if getattr(config.indexing, "skip_dense", False):
        return
    backend = str(config.embedding.embedding_backend or "").strip().lower()
    provider = str(config.embedding.embedding_type or "").strip().lower()
    if backend != "provider":
        return
    if provider in SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS:
        return
    allowed = ", ".join(sorted(SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS))
    raise HTTPException(
        status_code=422,
        detail=(
            "Unsupported embedding provider for embedding_backend='provider': "
            f"'{provider}'. Allowed providers: [{allowed}]."
        ),
    )


def _validate_embedding_tokenization_compat(config: TriBridConfig) -> None:
    if getattr(config.indexing, "skip_dense", False):
        return
    backend = str(config.embedding.embedding_backend or "").strip().lower()
    if backend != "provider":
        return

    provider = str(config.embedding.embedding_type or "").strip().lower()
    strategy = str(config.tokenization.strategy or "").strip().lower()
    required = provider_requires_tokenizer(provider)
    if required is not None and strategy not in required:
        req_text = ", ".join(sorted(required))
        raise HTTPException(
            status_code=422,
            detail=(
                "Invalid tokenizer strategy for embedding provider: "
                f"provider='{provider}' requires tokenization.strategy in [{req_text}], got '{strategy}'."
            ),
        )

    if strategy == "tiktoken":
        enc = str(config.tokenization.tiktoken_encoding or "").strip()
        try:
            import tiktoken

            tiktoken.get_encoding(enc)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown tiktoken encoding '{enc}': {e}",
            ) from e


async def _enforce_index_contract_lock(
    *,
    repo_id: str | None,
    existing_config: TriBridConfig,
    new_config: TriBridConfig,
) -> None:
    rid = str(repo_id or "").strip()
    if not rid:
        return

    old_dense = dense_contract_from_config(existing_config)
    new_dense = dense_contract_from_config(new_config)
    old_sparse = sparse_contract_from_config(existing_config)
    new_sparse = sparse_contract_from_config(new_config)
    dense_changed = old_dense != new_dense
    sparse_changed = old_sparse != new_sparse
    if not dense_changed and not sparse_changed:
        return

    pg = PostgresClient(existing_config.indexing.postgres_url)
    try:
        await pg.connect()
        corpus = await pg.get_corpus(rid)
        if not corpus:
            return

        stats = await pg.get_index_stats(rid)
        total_chunks = int(getattr(stats, "total_chunks", 0) or 0)
        if total_chunks <= 0:
            return
        try:
            qdrant_status = await QdrantChunkStore(existing_config).status(
                rid, physical=qdrant_collection_of(await pg.get_generation(rid))
            )
        except DependencyUnavailableError as exc:
            # The lock cannot be evaluated without the vector store: refuse the
            # contract change instead of silently accepting it.
            raise dependency_unavailable_http_exception(
                exc.dependency, boundary="Config contract lock", exc=exc
            ) from exc
        has_dense_index = bool(qdrant_status is not None and qdrant_status.dense_points > 0)

        blocked_dense = bool(dense_changed and has_dense_index)
        blocked_sparse = bool(sparse_changed and total_chunks > 0)
        if not blocked_dense and not blocked_sparse:
            return

        changed_legs: list[str] = []
        if blocked_dense:
            changed_legs.append("dense")
        if blocked_sparse:
            changed_legs.append("sparse")

        raise HTTPException(
            status_code=409,
            detail={
                "code": "index_contract_change_requires_reindex",
                "corpus_id": rid,
                "changed_legs": changed_legs,
                "expected_contract": {
                    "dense": old_dense if blocked_dense else None,
                    "sparse": old_sparse if blocked_sparse else None,
                },
                "current_contract": {
                    "dense": new_dense if blocked_dense else None,
                    "sparse": new_sparse if blocked_sparse else None,
                },
                "required_action": (
                    "Run indexing with force_reindex=true (or delete the existing index first), "
                    "then apply contract changes."
                ),
            },
        )
    except HTTPException:
        raise
    except Exception:
        # Infra validation outage should not block all config writes.
        return
    finally:
        try:
            await pg.disconnect()
        except Exception:
            pass


def _collect_model_warnings(config: TriBridConfig) -> list[ModelValidationWarning]:
    """Collect soft warnings for model assignments against the catalog.

    Unlike _validate_model_capabilities (which raises HTTPException for hard errors),
    this function returns warnings for unknown/unrecognized models so the UI can
    surface non-blocking advice.
    """
    catalog_models = _load_catalog_models_for_validation()
    warnings: list[ModelValidationWarning] = []

    def _check(
        field_name: str, model_value: str, required_component: str, provider_hint: str | None = None
    ) -> None:
        raw = str(model_value or "").strip()
        if not raw:
            return
        caps = _catalog_capabilities_for_model(
            catalog_models, model_value=raw, provider_hint=provider_hint
        )
        if not caps:
            warnings.append(
                ModelValidationWarning(
                    field=field_name,
                    model_value=raw,
                    message=f"Model '{raw}' is not in the catalog. It may work but cannot be validated.",
                )
            )
        elif required_component not in caps:
            found = ", ".join(sorted(caps))
            warnings.append(
                ModelValidationWarning(
                    field=field_name,
                    model_value=raw,
                    message=f"Model '{raw}' supports [{found}] but this field requires [{required_component}].",
                )
            )

    gateway_aliases = gateway_rows_snapshot()
    for field_name, value in (
        ("chat.litellm.default_model", config.chat.litellm.default_model),
        ("generation.gen_model", config.generation.gen_model),
        ("generation.enrich_model", config.generation.enrich_model),
        ("generation.gen_model_http", config.generation.gen_model_http),
        ("generation.gen_model_mcp", config.generation.gen_model_mcp),
        ("generation.gen_model_cli", config.generation.gen_model_cli),
        ("chat.multimodal.vision_model_override", config.chat.multimodal.vision_model_override),
        (
            "graph_indexing.semantic_kg_llm_model",
            getattr(config.graph_indexing, "semantic_kg_llm_model", ""),
        ),
    ):
        alias = str(value or "").strip()
        if alias.startswith("litellm:"):
            alias = alias.split(":", 1)[1].strip()
        if not alias:
            continue
        if not gateway_aliases:
            warnings.append(
                ModelValidationWarning(
                    field=field_name,
                    model_value=alias,
                    message="Generation catalog is not loaded; gateway aliases cannot be verified and generation fails closed.",
                )
            )
        elif alias not in gateway_aliases:
            warnings.append(
                ModelValidationWarning(
                    field=field_name,
                    model_value=alias,
                    message=f"'{alias}' is not a gateway alias in data/models.json; generation with it fails closed.",
                )
            )

    if str(config.embedding.embedding_backend or "").strip().lower() == "provider" and not getattr(
        config.indexing, "skip_dense", False
    ):
        emb_provider = str(config.embedding.embedding_type or "").strip().lower()
        if emb_provider and emb_provider not in SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS:
            allowed = ", ".join(sorted(SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS))
            warnings.append(
                ModelValidationWarning(
                    field="embedding.embedding_type",
                    model_value=emb_provider,
                    message=f"Embedding provider '{emb_provider}' is not runtime-selectable today. Allowed providers: [{allowed}].",
                )
            )

    for field, alias, output_tokens in (
        (
            "chat.max_tokens",
            str(config.chat.litellm.default_model or "").strip(),
            int(config.chat.max_tokens),
        ),
        (
            "generation.gen_max_tokens",
            str(config.generation.gen_model or "").strip(),
            int(config.generation.gen_max_tokens),
        ),
    ):
        window = context_window_for_alias(alias) if alias else None
        if window is not None and output_tokens >= window // 2:
            warnings.append(
                ModelValidationWarning(
                    field=field,
                    model_value=str(output_tokens),
                    message=(
                        f"{field}={output_tokens} reserves at least half of alias '{alias}' {window}-token context window; "
                        "retrieved context will be trimmed aggressively and requests are refused once nothing fits."
                    ),
                )
            )

    return warnings


@router.get("/config/validate", response_model=ModelValidationResult)
async def validate_config(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> ModelValidationResult:
    """Validate current config model assignments against the catalog.

    Returns soft warnings (unknown models, capability mismatches) without
    blocking config saves. The PUT /api/config response is unchanged.
    """
    repo_id = scope.resolved_repo_id
    config = await _load_config_for_api(repo_id, boundary="Config validation API")

    warnings = _collect_model_warnings(config)
    return ModelValidationResult(valid=True, warnings=warnings)


@router.get("/config/registry", response_model=ConfigRegistryResponse)
async def get_config_registry() -> ConfigRegistryResponse:
    return redact_registry_defaults(build_config_registry_response())


@router.get("/config/readiness", response_model=ConfigReadinessResponse)
async def get_config_readiness(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> ConfigReadinessResponse:
    repo_id = scope.resolved_repo_id
    config = await _load_config_for_api(repo_id, boundary="Config readiness API")
    try:
        return await build_config_readiness_response(config, scope_id=repo_id)
    except DependencyUnavailableError as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Config readiness API")
        raise


@router.get("/config", response_model=TriBridConfig)
async def get_config(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    config = await _load_config_for_api(repo_id, boundary="Config API")
    return redact_config_secrets(config)


@router.put("/config", response_model=TriBridConfig)
async def update_config(
    config: TriBridConfig,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        async with _get_config_write_lock(repo_id):
            existing_config = await load_scoped_config(repo_id=repo_id)
            # The browser is holding the redacted document it was served; a marker means
            # "unchanged", never "set the password to the literal [redacted]".
            try:
                config = restore_config_secrets(config, existing_config)
            except SecretMarkerWriteError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            _validate_model_capabilities(config)
            await _enforce_index_contract_lock(
                repo_id=repo_id,
                existing_config=existing_config,
                new_config=config,
            )
            saved = await save_scoped_config(config, repo_id=repo_id)
            if repo_id:
                ensure_current_bundle(repo_id=repo_id, cfg=saved)
            return redact_config_secrets(saved)
    except HTTPException:
        raise
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise_postgres_unavailable_if_applicable(e, boundary="Config update API")
        raise


@router.patch("/config/{section}", response_model=TriBridConfig)
async def update_config_section(
    section: str,
    updates: dict[str, Any],
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    async with _get_config_write_lock(repo_id):
        config = await _load_config_for_api(repo_id, boundary="Config section update API")

        # Only allow patching known top-level sections
        if section not in TriBridConfig.model_fields:
            raise HTTPException(status_code=404, detail=f"Unknown config section: {section}")

        # Build a new config dict with patched section and re-validate (ensures Field constraints apply)
        base = config.model_dump()
        current_section = base.get(section)
        if not isinstance(current_section, dict):
            raise HTTPException(
                status_code=400, detail=f"Config section '{section}' is not patchable"
            )
        if not isinstance(updates, dict):
            raise HTTPException(status_code=422, detail="PATCH body must be a JSON object")

        merged = _deep_merge_dicts(current_section, updates)
        base[section] = merged

        try:
            new_config = TriBridConfig.model_validate(base)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        try:
            new_config = restore_config_secrets(new_config, config)
        except SecretMarkerWriteError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _validate_model_capabilities(new_config)
        await _enforce_index_contract_lock(
            repo_id=repo_id,
            existing_config=config,
            new_config=new_config,
        )

        try:
            saved = await save_scoped_config(new_config, repo_id=repo_id)
            if repo_id:
                ensure_current_bundle(repo_id=repo_id, cfg=saved)
            return redact_config_secrets(saved)
        except CorpusNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            raise_postgres_unavailable_if_applicable(e, boundary="Config section update API")
            raise


@router.post("/config/reset", response_model=TriBridConfig)
async def reset_config(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> TriBridConfig:
    repo_id = scope.resolved_repo_id
    try:
        async with _get_config_write_lock(repo_id):
            reset = await reset_scoped_config(repo_id=repo_id)
            if repo_id:
                ensure_current_bundle(repo_id=repo_id, cfg=reset)
            return redact_config_secrets(reset)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise_postgres_unavailable_if_applicable(e, boundary="Config reset API")
        raise


@router.get("/secrets/check")
async def check_secrets(
    keys: str = Query(..., description="Comma-separated env var names"),
) -> dict[str, bool]:
    """Return which secret env vars are configured (never returns values)."""
    names = [k.strip() for k in (keys or "").split(",") if k.strip()]
    if not names:
        return {}

    allowed = allowed_secret_env_vars()
    invalid = [name for name in names if name not in allowed]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported secret key(s): {', '.join(sorted(set(invalid)))}",
        )

    return {name: bool(os.getenv(name)) for name in names}




_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0")


def _request_host(request: Request) -> str:
    """The host a client actually used, as the deployment's proxy reports it."""
    forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    return forwarded or (request.headers.get("host") or "").strip()


def _is_loopback_host(host: str) -> bool:
    name = (host or "").strip().lower()
    if not name:
        return True
    if name.startswith("[") and "]" in name:
        name = name[: name.index("]") + 1]
    else:
        name = name.rsplit(":", 1)[0] if name.count(":") == 1 else name
    return name in _LOOPBACK_HOSTS or name.startswith("127.")


def _advertised_host_is_allowed(cfg: TriBridConfig, url: str) -> bool:
    """Would the transport accept a request whose Host header is this URL's host?

    Answered by the transport's own validator, constructed from the same settings
    `server/mcp/server.py` gives it. `enable_dns_rebinding_protection` defaults on and
    `allowed_hosts` defaults to loopback only, so pointing `public_base_url` at the
    deployment's public origin without also allowing that host swaps "redirected or
    plaintext" (M-91) for a 421 -- which is not a fix.
    """
    from mcp.server.transport_security import (
        TransportSecurityMiddleware,
        TransportSecuritySettings,
    )

    host = urlsplit(url).netloc
    if not host:
        return False
    if not cfg.mcp.enable_dns_rebinding_protection:
        return True
    validator = TransportSecurityMiddleware(
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(cfg.mcp.allowed_hosts),
            allowed_origins=list(cfg.mcp.allowed_origins),
        )
    )
    return bool(validator._validate_host(host))


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
    tools: list[MCPToolInfo] = []

    try:
        python_stdio_available = importlib.util.find_spec("mcp") is not None
    except Exception as e:
        python_stdio_available = False
        details.append(f"Error checking Python MCP package availability: {e}")

    if python_stdio_available:
        details.append("Python stdio MCP transport is available (client-spawned; no daemon).")
    else:
        details.append(
            "Python stdio MCP transport not available (Python package 'mcp' not installed)."
        )

    # Python Streamable HTTP transport is embedded under cfg.mcp.mount_path (same FastAPI app).
    try:
        cfg = load_global_config()
        if cfg.mcp.enabled:
            if python_stdio_available:
                # `host`/`port` describe the hop this request arrived on; they are reported
                # for diagnosis and are NOT what a client should connect to. Deriving the
                # advertised URL from the request advertised the proxy's internal hop --
                # `http://ragweld.dtmont.com:80/mcp/`, plain HTTP on an HTTPS-only
                # deployment (M-91). The connection URL comes from typed config.
                host = request.url.hostname or "127.0.0.1"
                port = request.url.port or (443 if request.url.scheme == "https" else 80)
                # Starlette mounts require a trailing slash for the mount root.
                # Advertise the canonical URL that does not redirect for POST.
                path = str(cfg.mcp.mount_path).rstrip("/") + "/"
                # Idempotent in the mount path. `public_base_url` is documented as an
                # ORIGIN and the mount path is appended here, but "the URL clients use" is
                # naturally written `https://host/mcp`, and that reading has already been
                # asked for once. Rather than let the two spellings disagree -- silently
                # advertising `/mcp/mcp/` -- a base that already ends in the mount path is
                # accepted and not doubled.
                #
                # Compared on the PATH component, not on the whole string: `https://mcp`
                # ends with "/mcp" only because of the second slash in "//", and stripping
                # it produced `https:/mcp/`. The mount is guaranteed non-empty by
                # `MCPConfig.mount_path`'s pattern, which is what keeps `base[:-0]` -- the
                # whole-slice trap that turned a "/" mount into an advertised "/" -- out of
                # reach here.
                base = str(cfg.mcp.public_base_url).rstrip("/")
                mount = path.rstrip("/")
                base_path = urlsplit(base).path.rstrip("/")
                if mount and base_path.endswith(mount):
                    base = base[: len(base) - len(mount)].rstrip("/")
                url = f"{base}{path}"

                # An unconfigured public origin is its own failure mode, and the quiet one.
                # `public_base_url` defaults to loopback; on a proxied deployment that
                # advertises an address no client on the public origin can reach, while the
                # `allowed_hosts` check happily passes because loopback IS allowed. So the
                # check is made against the host a client would really use.
                request_host = _request_host(request)
                public_base_url_configured = (
                    str(cfg.mcp.public_base_url) != MCPConfig().public_base_url
                    or _is_loopback_host(request_host)
                )
                # Asked of the transport's OWN validator rather than re-implemented here:
                # two copies of the rule would drift silently, and a wrong answer here is
                # an operator following a URL the server then answers 421 to.
                host_allowed = _advertised_host_is_allowed(
                    cfg, url if public_base_url_configured else f"//{request_host}/"
                )
                python_http = MCPHTTPTransportStatus(
                    host=str(host),
                    port=int(port),
                    path=path,
                    running=True,
                    url=url,
                    host_allowed=host_allowed,
                    public_base_url_configured=public_base_url_configured,
                    request_host=request_host,
                )
                from server.mcp.server import get_mcp_server

                tools = [
                    MCPToolInfo(name=str(tool.name), description=str(tool.description or ""))
                    for tool in await get_mcp_server().list_tools()
                ]
                details.append(
                    f"Python HTTP MCP transport is enabled and mounted at {cfg.mcp.mount_path} "
                    f"(connect to {url})."
                )
                if not public_base_url_configured:
                    details.append(
                        f"config.mcp.public_base_url is still the loopback default while "
                        f"this request arrived on {request_host}, so the advertised URL "
                        f"names an address no client on that origin can reach."
                    )
                elif not host_allowed:
                    details.append(
                        f"The advertised host is not in config.mcp.allowed_hosts, so the "
                        f"transport answers 421 to clients using {url}."
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
        tools=tools,
    )


def _describe_exception(exc: BaseException) -> str:
    """Flatten anyio ExceptionGroups so the operator sees the real failure, not 'unhandled errors in a TaskGroup'."""
    if isinstance(exc, BaseExceptionGroup):
        parts = [_describe_exception(sub) for sub in exc.exceptions]
        return "; ".join(dict.fromkeys(p for p in parts if p))
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


@router.post(
    "/mcp/probe",
    response_model=MCPProbeResponse,
    responses=RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES,
)
async def mcp_probe(
    payload: MCPProbeRequest,
    request: Request,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> MCPProbeResponse:
    """Invoke the MCP `search` tool the way an MCP client does: a real ClientSession over the mounted transport.

    This is the only search path the MCP subtab probes; there is no HTTP shortcut
    that bypasses the tool (the former /api/mcp/rag_search always enabled every
    retrieval leg and ignored mcp.default_mode).
    """
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import TextContent

    from server.mcp.server import mounted_state

    corpus_id = str(payload.corpus_id or scope.resolved_repo_id or "").strip()
    if not corpus_id:
        raise HTTPException(status_code=422, detail="corpus_id is required")
    question = str(payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")
    enabled, mount_path = mounted_state()
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail="The MCP Streamable HTTP transport is not mounted in this process",
        )

    cfg = load_global_config()
    # Same typed boundary as every stateful route: a reachable store proves the
    # corpus exists (404) and an unreachable one is the structured 503, before a
    # tool session is opened.
    try:
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        try:
            corpus = await pg.get_corpus(corpus_id)
        finally:
            with contextlib.suppress(Exception):
                await pg.disconnect()
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="MCP probe corpus validation")
        raise
    if corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {corpus_id}")
    resolved_mode = str(payload.mode or cfg.mcp.default_mode)
    resolved_top_k = int(payload.top_k or cfg.mcp.default_top_k)
    host = request.url.hostname or "127.0.0.1"
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    transport_url = f"http://{host}:{port}{mount_path.rstrip('/')}/"

    # Same process, real transport: the MCP session manager runs in this app's lifespan.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app), base_url=f"http://{host}:{port}"
    ) as http_client:
        try:
            async with streamable_http_client(transport_url, http_client=http_client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    arguments: dict[str, Any] = {"query": question, "corpus_id": corpus_id}
                    if payload.mode:
                        arguments["mode"] = payload.mode
                    if payload.top_k:
                        arguments["top_k"] = int(payload.top_k)
                    result = await session.call_tool("search", arguments)
        except HTTPException:
            raise
        except Exception as exc:
            raise_required_dependency_unavailable_if_applicable(exc, boundary="MCP probe")
            raise HTTPException(
                status_code=503,
                detail=f"MCP probe failed on the mounted transport: {_describe_exception(exc)}",
            ) from exc

    if result.isError:
        structured = result.structuredContent
        raw_error = structured.get("error") if isinstance(structured, dict) else None
        if isinstance(raw_error, dict):
            code = str(raw_error.get("code") or "")
            if code == "dependency_unavailable":
                detail = DependencyUnavailableDetail.model_validate(raw_error)
                raise HTTPException(status_code=503, detail=detail.model_dump(mode="json"))
            if code == "required_retrieval_leg_failed":
                leg_failure = RequiredRetrievalLegFailureDetail.model_validate(raw_error)
                raise HTTPException(status_code=503, detail=leg_failure.model_dump(mode="json"))
            if code in {"embedding_contract_mismatch", "sparse_contract_mismatch"}:
                mismatch = RetrievalContractMismatchDetail.model_validate(raw_error)
                raise HTTPException(status_code=409, detail=mismatch.model_dump(mode="json"))
        text = " ".join(c.text for c in result.content if isinstance(c, TextContent)).strip()
        lowered = text.lower()
        if "corpus not found" in lowered or "not found" in lowered:
            raise HTTPException(status_code=404, detail=text or f"Corpus not found: {corpus_id}")
        raise HTTPException(
            status_code=502, detail=f"MCP search tool returned an error: {text or 'no detail'}"
        )
    structured = result.structuredContent
    rows = structured.get("result") if isinstance(structured, dict) else structured
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="MCP search tool returned no structured result")
    return MCPProbeResponse(
        tool="search",
        transport_url=transport_url,
        corpus_id=corpus_id,
        mode=resolved_mode,
        top_k=resolved_top_k,
        results=[ChunkMatch.model_validate(row) for row in rows],
    )
