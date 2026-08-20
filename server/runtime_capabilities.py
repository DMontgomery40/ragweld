from __future__ import annotations

from typing import Any

from server.models.tribrid_config_model import (
    ChunkingRuntimeCapabilities,
    EmbeddingRuntimeCapabilities,
    EmbeddingRuntimeProviderCapability,
    GenerationRuntimeCapabilities,
    IndexingRuntimeCapabilities,
    RerankerRuntimeCapabilities,
    RuntimeCapabilitiesResponse,
    TriBridConfig,
    RuntimeOption,
    SearchRuntimeCapabilities,
    ChatProviderInfo,
)

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
        description="Local Python embedding runtime using sentence-transformers and optional MLX fast-paths.",
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
        id="cohere",
        label="Cohere",
        description="Cloud reranking executed today by server/retrieval/rerank.py via the Cohere SDK.",
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
        id="haystack_qdrant_local",
        label="Haystack/Qdrant local pilot",
        description="Local Qdrant-backed OSS pilot lane hydrated from the sidecar export contract.",
    ),
    RuntimeOption(
        id="postgres_pgvector",
        label="Postgres pgvector",
        description="Primary dense-vector storage and ANN search index in Postgres.",
    ),
    RuntimeOption(
        id="postgres_fts",
        label="Postgres FTS",
        description="Sparse lexical indexing and BM25-style retrieval using Postgres full-text search.",
    ),
    RuntimeOption(
        id="neo4j_lexical_graph",
        label="Neo4j lexical graph",
        description="Optional lexical graph projection over documents and chunks.",
    ),
    RuntimeOption(
        id="neo4j_chunk_vector",
        label="Neo4j chunk vectors",
        description="Optional Neo4j native vector index over Chunk nodes when dense embeddings are stored.",
    ),
    RuntimeOption(
        id="neo4j_semantic_kg",
        label="Neo4j semantic KG",
        description="Optional semantic knowledge graph extraction and storage during indexing.",
    ),
)

SEARCH_VECTOR_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="haystack_qdrant_local",
        label="Haystack/Qdrant local pilot",
        description="Local Qdrant vector retrieval driven through the Haystack pilot lane.",
    ),
    RuntimeOption(
        id="postgres_pgvector",
        label="Postgres pgvector",
        description="Dense vector retrieval against Postgres pgvector indexes.",
    ),
    RuntimeOption(
        id="neo4j_chunk_vector",
        label="Neo4j chunk vectors",
        description="Neo4j chunk-vector search when graph storage keeps dense embeddings.",
    ),
)

SEARCH_SPARSE_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="postgres_fts",
        label="Postgres FTS",
        description="Sparse search using Postgres full-text indexes and configured ts_config/tokenizer settings.",
    ),
)

SEARCH_GRAPH_BACKEND_OPTIONS: tuple[RuntimeOption, ...] = (
    RuntimeOption(
        id="neo4j_entity_chunk",
        label="Neo4j entity-chunk graph",
        description="Graph retrieval over linked entities, documents, and chunks in Neo4j.",
    ),
    RuntimeOption(
        id="neo4j_expand_chunks_via_entities",
        label="Neo4j entity expansion",
        description="Graph-based chunk expansion through entity adjacency and lexical/semantic links.",
    ),
)

_EMBEDDING_CATALOG_ONLY_REASON = (
    "Catalog entry only. Provider-backed embeddings currently execute only via openai, mlx, local, or huggingface."
)
_RERANKER_CATALOG_ONLY_REASON = (
    "Catalog entry only. Current cloud reranker runtime supports cohere only; the learning reranker is selected via training.* config rather than catalog rows."
)


def build_runtime_capabilities_response() -> RuntimeCapabilitiesResponse:
    return build_runtime_capabilities_response_for_config(TriBridConfig())


def build_runtime_capabilities_response_for_config(config: TriBridConfig) -> RuntimeCapabilitiesResponse:
    return RuntimeCapabilitiesResponse(
        generation=GenerationRuntimeCapabilities(
            routing_backends=list(GENERATION_ROUTING_BACKEND_OPTIONS),
            serving_backends=list(GENERATION_SERVING_BACKEND_OPTIONS),
            default_route=_default_generation_route(config),
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
    if "GEN" in components:
        roles.append("generation")
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
