from __future__ import annotations

from typing import Any

from server.gateway_catalog import LOCAL_GATEWAY_ALIAS
from server.models.tribrid_config_model import (
    ChatProviderInfo,
    ChunkingRuntimeCapabilities,
    EmbeddingRuntimeCapabilities,
    EmbeddingRuntimeProviderCapability,
    GenerationRuntimeCapabilities,
    IndexingRuntimeCapabilities,
    LearningAgentRuntimeCapability,
    LocalServingRuntimeCapability,
    RerankerRuntimeCapabilities,
    RuntimeCapabilitiesResponse,
    RuntimeOption,
    SearchRuntimeCapabilities,
    TrainingRuntimeCapabilities,
    TriBridConfig,
)
from server.retrieval.mlx_qwen3 import mlx_is_available

EMBEDDING_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="deterministic",
        label="Deterministic",
        description="Offline/test-friendly embedding path with synthetic vectors.",
    ),
    RuntimeOption(
        id="provider",
        label="Provider",
        description="Real embedding execution through a supported provider runtime backend.",
    ),
)

EMBEDDING_PROVIDER_OPTIONS: tuple[EmbeddingRuntimeProviderCapability, ...] = (
    EmbeddingRuntimeProviderCapability(
        provider="openai",
        label="OpenAI",
        description="Cloud API embeddings executed by server/indexing/embedder.py via the OpenAI client.",
        badge="cloud",
        model_config_field="embedding.embedding_model",
        tokenizer_strategies=["tiktoken"],
    ),
    EmbeddingRuntimeProviderCapability(
        provider="mlx",
        label="MLX",
        description="On-device MLX embeddings on Apple Silicon using embedding_model_mlx weights.",
        badge="local",
        model_config_field="embedding.embedding_model_mlx",
        tokenizer_strategies=["huggingface"],
    ),
    EmbeddingRuntimeProviderCapability(
        provider="local",
        label="Local",
        description="Local Python embedding runtime executing the explicit sentence-transformers path.",
        badge="local",
        model_config_field="embedding.embedding_model_local",
        tokenizer_strategies=["huggingface"],
    ),
    EmbeddingRuntimeProviderCapability(
        provider="huggingface",
        label="Hugging Face",
        description="Local Hugging Face embedding runtime sharing the sentence-transformers/local execution path.",
        badge="local",
        model_config_field="embedding.embedding_model_local",
        tokenizer_strategies=["huggingface"],
    ),
)

SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS: set[str] = {
    item.provider for item in EMBEDDING_PROVIDER_OPTIONS
}

PROVIDER_TOKENIZER_STRATEGIES: dict[str, set[str]] = {
    item.provider: set(item.tokenizer_strategies) for item in EMBEDDING_PROVIDER_OPTIONS
}

RERANKER_MODE_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(id="none", label="None", description="No reranking; retrieval order passes through unchanged."),
    RuntimeOption(
        id="learning",
        label="Learning",
        description="MLX Qwen3 LoRA learning reranker selected through training.* configuration.",
    ),
    RuntimeOption(
        id="cloud",
        label="Cloud",
        description="External API reranking through the currently supported cloud provider set.",
    ),
)

RERANKER_CLOUD_PROVIDER_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="litellm",
        label="LiteLLM gateway",
        description=(
            "Listwise reranking through a LiteLLM gateway alias (server/retrieval/gateway_reranker.py); "
            "uses the gateway credential, loads no local model."
        ),
    ),
    RuntimeOption(
        id="cohere",
        label="Cohere",
        description="Cloud reranking executed by server/retrieval/rerank.py via the Cohere SDK (COHERE_API_KEY).",
    ),
)

SUPPORTED_RERANKER_CLOUD_PROVIDERS: set[str] = {item.id for item in RERANKER_CLOUD_PROVIDER_OPTIONS}

RERANKER_LEARNING_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="mlx_qwen3",
        label="MLX Qwen3",
        description="Apple Silicon MLX learning reranker backend with LoRA adapter hot reload.",
    ),
)

SUPPORTED_LEARNING_RERANKER_BACKENDS: set[str] = {item.id for item in RERANKER_LEARNING_BACKEND_OPTIONS}

_GENERATION_CATALOG_ONLY_REASON = (
    "Generation provider rows are pricing/candidate metadata; runtime selection comes from authenticated LiteLLM aliases."
)

CHUNKING_STRATEGY_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(id="ast", label="AST-aware", description="Preserve top-level code structure for supported languages."),
    RuntimeOption(id="hybrid", label="Hybrid", description="Prefer AST-aware chunking with runtime fallbacks."),
    RuntimeOption(id="greedy", label="Greedy", description="Legacy fixed-char windowing using the greedy fallback target."),
    RuntimeOption(id="fixed_chars", label="Fixed chars", description="Character window chunking with overlap."),
    RuntimeOption(id="fixed_tokens", label="Fixed tokens", description="Token-window chunking with token overlap."),
    RuntimeOption(id="recursive", label="Recursive", description="Separator-based chunking packed by token target."),
    RuntimeOption(id="markdown", label="Markdown", description="Heading-aware markdown chunking."),
    RuntimeOption(id="sentence", label="Sentence", description="Sentence-packed chunking for prose."),
    RuntimeOption(id="qa_blocks", label="Q/A blocks", description="Question/answer block detection with token packing."),
)

SUPPORTED_CHUNKING_STRATEGIES: set[str] = {item.id for item in CHUNKING_STRATEGY_OPTIONS}

GENERATION_ROUTING_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="litellm",
        label="LiteLLM gateway",
        description="Unified OpenAI-compatible gateway and router for self-hosted and cloud generation backends.",
    ),
)

GENERATION_SERVING_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="vllm",
        label="vLLM",
        description="OpenAI-compatible self-hosted serving runtime for owned generation models.",
    ),
)

INDEXING_DENSE_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="deterministic",
        label="Deterministic dense path",
        description="Synthetic dense vectors used for offline tests and deterministic runs.",
    ),
    RuntimeOption(
        id="provider",
        label="Provider dense path",
        description="Real dense embedding execution using one of the supported provider runtimes.",
    ),
)

INDEXING_STORAGE_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="postgres_chunk_rows",
        label="Postgres chunk rows",
        description="Chunk content, provenance, summaries, and caches as corpus control/state rows in Postgres.",
    ),
    RuntimeOption(
        id="qdrant_dense",
        label="Qdrant dense vectors",
        description="Dense chunk vectors in a per-corpus Qdrant generation written through the Haystack document store.",
    ),
    RuntimeOption(
        id="qdrant_sparse_idf",
        label="Qdrant sparse (IDF BM25)",
        description="IDF-modified BM25 sparse vectors (fastembed Qdrant/bm25) stored alongside the dense vectors in Qdrant.",
    ),
    RuntimeOption(
        id="neo4j_lexical_graph",
        label="Neo4j lexical graph",
        description="Optional lexical graph projection over documents and chunks.",
    ),
    RuntimeOption(
        id="neo4j_semantic_kg",
        label="Neo4j semantic KG",
        description="Optional semantic knowledge graph extraction and storage during indexing.",
    ),
)

SEARCH_VECTOR_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="qdrant_dense",
        label="Qdrant dense vectors",
        description="Dense vector retrieval against the corpus Qdrant generation (cosine similarity).",
    ),
)

SEARCH_SPARSE_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="qdrant_sparse_idf",
        label="Qdrant sparse (IDF BM25)",
        description="Sparse retrieval over Qdrant/bm25 sparse vectors using the corpus-recorded BM25/stemming contract.",
    ),
)

SEARCH_GRAPH_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="qdrant_neo4j_traversal",
        label="Qdrant-seeded Neo4j traversal",
        description="Dense Qdrant seeds joined to generation-scoped Neo4j entities and related chunks.",
    ),
)

_EMBEDDING_CATALOG_ONLY_REASON = (
    "Catalog entry only. Provider-backed embeddings currently execute only via openai, mlx, local, or huggingface."
)
_RERANKER_CATALOG_ONLY_REASON = (
    "Catalog entry only. The cloud reranker runtime supports the LiteLLM gateway (litellm) and cohere; the learning reranker is selected via training.* config rather than catalog rows."
)


LOCAL_SERVING_BACKEND: RuntimeOption = GENERATION_SERVING_BACKEND_OPTIONS[0]

# Learning Agent execution backends that run in-process on the API host, with the
# runtime they need there. Anything else (unsloth) executes inside a Flyte task image.
_HOST_EXECUTED_TRAINING_BACKENDS: dict[str, str] = {"mlx_qwen3": "MLX (mlx + mlx_lm)"}


def local_serving_runtime_capability(config: TriBridConfig) -> LocalServingRuntimeCapability:
    """The local generation lane exactly as the effective config switches it on this host."""
    vllm = config.chat.vllm
    return LocalServingRuntimeCapability(
        alias=LOCAL_GATEWAY_ALIAS,
        backend=LOCAL_SERVING_BACKEND.id,
        backend_label=LOCAL_SERVING_BACKEND.label,
        enabled=bool(vllm.enabled),
        model=str(vllm.default_model or "").strip(),
    )


def learning_agent_runtime_capability(
    config: TriBridConfig, *, mlx_available: bool
) -> LearningAgentRuntimeCapability:
    """Resolve the configured Learning Agent execution backend against this host.

    ``mlx_available`` is the probe result for the MLX runtime, passed in so the
    resolution itself is pure; callers use :func:`mlx_is_available` for the real host.
    """
    training = config.training
    backend = str(training.ragweld_agent_backend or "").strip()
    base_model = str(training.ragweld_agent_base_model or "").strip()
    artifact_path = str(training.ragweld_agent_model_path or "").strip()

    if backend == "unsloth":
        return LearningAgentRuntimeCapability(
            execution_backend=backend,
            execution_locus="flyte_task",
            host_available=False,
            availability_detail=(
                "Unsloth executes inside the Flyte task image, not on this host; "
                "the Training Control Plane reports lane readiness."
            ),
            base_model=base_model,
            artifact_path=artifact_path,
        )

    runtime_label = _HOST_EXECUTED_TRAINING_BACKENDS.get(backend)
    if runtime_label is None:
        return LearningAgentRuntimeCapability(
            execution_backend=backend,
            execution_locus="host",
            host_available=False,
            availability_detail=(
                f"Training backend {backend or '(unset)'} is not a supported execution backend; "
                "runs will fail closed."
            ),
            base_model=base_model,
            artifact_path=artifact_path,
        )

    if mlx_available:
        detail = f"Training backend {backend} runs on this host ({runtime_label} is importable)."
    else:
        detail = f"Training backend {backend} is not available on this host; runs will fail closed."
    return LearningAgentRuntimeCapability(
        execution_backend=backend,
        execution_locus="host",
        host_available=mlx_available,
        availability_detail=detail,
        base_model=base_model,
        artifact_path=artifact_path,
    )


def build_runtime_capabilities_response(*, mlx_available: bool | None = None) -> RuntimeCapabilitiesResponse:
    return build_runtime_capabilities_response_for_config(TriBridConfig(), mlx_available=mlx_available)


def build_runtime_capabilities_response_for_config(
    config: TriBridConfig, *, mlx_available: bool | None = None
) -> RuntimeCapabilitiesResponse:
    """Build the capability matrix for ``config`` on this host.

    ``mlx_available`` defaults to the real MLX probe (a cached child-process import);
    pass it explicitly to describe a hypothetical host without probing. Blocking on the
    first probe; call from a worker thread inside async handlers.
    """
    mlx_present = mlx_is_available() if mlx_available is None else bool(mlx_available)
    return RuntimeCapabilitiesResponse(
        generation=GenerationRuntimeCapabilities(
            routing_backends=list(GENERATION_ROUTING_BACKEND_OPTIONS),
            serving_backends=list(GENERATION_SERVING_BACKEND_OPTIONS),
            default_route=_default_generation_route(config),
            local_serving=local_serving_runtime_capability(config),
        ),
        embedding=EmbeddingRuntimeCapabilities(
            backends=list(EMBEDDING_BACKEND_OPTIONS),
            providers=list(EMBEDDING_PROVIDER_OPTIONS),
        ),
        reranker=RerankerRuntimeCapabilities(
            modes=list(RERANKER_MODE_OPTIONS),
            cloud_providers=list(RERANKER_CLOUD_PROVIDER_OPTIONS),
            learning_backends=list(RERANKER_LEARNING_BACKEND_OPTIONS),
        ),
        chunking=ChunkingRuntimeCapabilities(strategies=list(CHUNKING_STRATEGY_OPTIONS)),
        indexing=IndexingRuntimeCapabilities(
            dense_backends=list(INDEXING_DENSE_BACKEND_OPTIONS),
            storage_backends=list(INDEXING_STORAGE_BACKEND_OPTIONS),
        ),
        search=SearchRuntimeCapabilities(
            vector_backends=list(SEARCH_VECTOR_BACKEND_OPTIONS),
            sparse_backends=list(SEARCH_SPARSE_BACKEND_OPTIONS),
            graph_backends=list(SEARCH_GRAPH_BACKEND_OPTIONS),
        ),
        training=TrainingRuntimeCapabilities(
            learning_agent=learning_agent_runtime_capability(config, mlx_available=mlx_present),
        ),
    )


def _default_generation_route(config: TriBridConfig) -> ChatProviderInfo | None:
    litellm_base_url = str(getattr(config.chat.litellm, "base_url", "") or "").strip().rstrip("/")
    if getattr(config.chat.litellm, "enabled", False) and litellm_base_url:
        return ChatProviderInfo(
            kind="litellm",
            provider_name="LiteLLM",
            model=str(getattr(config.chat.litellm, "default_model", "") or "").strip(),
            base_url=litellm_base_url,
        )

    return None


def provider_requires_tokenizer(provider: str) -> set[str] | None:
    key = str(provider or "").strip().lower()
    req = PROVIDER_TOKENIZER_STRATEGIES.get(key)
    if req is None:
        return None
    return set(req)


def _normalized_components(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for value in raw:
        comp = str(value or "").strip().upper()
        if comp:
            out.append(comp)
    return out


def selection_metadata_for_catalog_row(row: dict[str, Any]) -> dict[str, Any]:
    components = _normalized_components(row.get("components"))
    provider = str(row.get("provider") or "").strip().lower()

    roles: list[str] = []
    if "EMB" in components and provider in SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS:
        roles.append("embedding_provider")
    if "RERANK" in components and provider in SUPPORTED_RERANKER_CLOUD_PROVIDERS:
        roles.append("reranker_cloud")

    if roles:
        return {
            "selection_roles": roles,
            "selection_status": "runtime_selectable",
            "selection_reason": None,
        }

    reasons: list[str] = []
    if "GEN" in components:
        reasons.append(_GENERATION_CATALOG_ONLY_REASON)
    if "EMB" in components:
        reasons.append(_EMBEDDING_CATALOG_ONLY_REASON)
    if "RERANK" in components:
        reasons.append(_RERANKER_CATALOG_ONLY_REASON)

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "selection_roles": [],
        "selection_status": "catalog_only",
        "selection_reason": " ".join(unique_reasons) if unique_reasons else None,
    }


def apply_selection_metadata_to_row(row: dict[str, Any]) -> dict[str, Any]:
    updated = dict(row)
    updated.update(selection_metadata_for_catalog_row(updated))
    return updated


def apply_selection_metadata_to_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    updated = dict(catalog)
    raw_models = updated.get("models")
    if not isinstance(raw_models, list):
        updated["models"] = []
        return updated
    updated["models"] = [
        apply_selection_metadata_to_row(row)
        for row in raw_models
        if isinstance(row, dict)
    ]
    return updated


def validate_catalog_selection_metadata(models: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for row in models:
        provider = str(row.get("provider") or "").strip()
        model = str(row.get("model") or "").strip()
        expected = selection_metadata_for_catalog_row(row)
        actual_roles = [str(x or "") for x in (row.get("selection_roles") or [])]
        actual_status = str(row.get("selection_status") or "").strip()
        actual_reason = row.get("selection_reason")

        if actual_roles != expected["selection_roles"]:
            errors.append(
                f"{provider}/{model}: selection_roles mismatch (expected {expected['selection_roles']!r}, got {actual_roles!r})"
            )
        if actual_status != expected["selection_status"]:
            errors.append(
                f"{provider}/{model}: selection_status mismatch (expected {expected['selection_status']!r}, got {actual_status!r})"
            )
        if actual_reason != expected["selection_reason"]:
            errors.append(
                f"{provider}/{model}: selection_reason mismatch (expected {expected['selection_reason']!r}, got {actual_reason!r})"
            )
    return errors
