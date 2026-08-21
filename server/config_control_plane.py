from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import httpx
from pydantic import BaseModel

from server.chat.gateway_runtime import (
    resolve_litellm_api_key,
    resolve_litellm_base_url,
    resolve_vllm_base_url,
)
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.dependency_errors import (
    DependencyUnavailableError,
    is_postgres_unavailable,
    is_transport_unavailable,
)
from server.indexing.oss_retrieval_pilot import build_retrieval_pilot_status
from server.models.tribrid_config_model import (
    ConfigFieldDescriptor,
    ConfigIntegrationContract,
    ConfigReadinessResponse,
    ConfigRegistryResponse,
    IntegrationReadiness,
    ObservabilityComponentStatus,
    SecretRequirement,
    SecretRequirementStatus,
    TraceExternalLink,
    TriBridConfig,
)
from server.observability.status import build_observability_status
from server.training.control_plane import build_agent_control_plane_status

_TIMEOUT = httpx.Timeout(2.5, connect=1.5)
_SERVER_ROOT = Path(__file__).resolve().parent
_SECRET_ENV_PATTERN = re.compile(r'os\.(?:getenv|environ\.get)\("([A-Z0-9_]+)"')


@dataclass(frozen=True)
class _SectionDefaults:
    scope: Literal["global", "corpus"]
    integration: str
    ui_surface: str
    exposure_level: Literal["basic", "advanced", "expert"]
    impact: Literal["live", "restart", "reindex", "redeploy"]


_SECTION_DEFAULTS: dict[str, _SectionDefaults] = {
    "retrieval": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "semantic_cache": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "scoring": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "layer_bonus": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "embedding": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "reindex"),
    "tokenization": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "reindex"),
    "chunking": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "reindex"),
    "indexing": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "reindex"),
    "graph_storage": _SectionDefaults("global", "neo4j", "graph", "basic", "restart"),
    "graph_indexing": _SectionDefaults("corpus", "neo4j", "graph", "advanced", "reindex"),
    "fusion": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "vector_search": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "sparse_search": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "graph_search": _SectionDefaults("corpus", "neo4j", "graph", "advanced", "live"),
    "reranking": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "generation": _SectionDefaults("corpus", "litellm", "runtime", "basic", "live"),
    "enrichment": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "reindex"),
    "chunk_summaries": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "expert", "reindex"),
    "keywords": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "reindex"),
    "tracing": _SectionDefaults("global", "otel_grafana_stack", "observability", "basic", "restart"),
    "training": _SectionDefaults("corpus", "unsloth", "training", "basic", "redeploy"),
    "ui": _SectionDefaults("global", "shell_ui", "shell", "basic", "live"),
    "chat": _SectionDefaults("corpus", "litellm", "runtime", "advanced", "live"),
    "hydration": _SectionDefaults("corpus", "tribrid_retrieval", "retrieval", "advanced", "live"),
    "evaluation": _SectionDefaults("corpus", "ragas", "eval", "basic", "live"),
    "system_prompts": _SectionDefaults("corpus", "promptfoo", "eval", "expert", "live"),
    "mcp": _SectionDefaults("global", "shell_ui", "shell", "advanced", "restart"),
    "synthetic": _SectionDefaults("corpus", "ragas", "eval", "advanced", "live"),
    "docker": _SectionDefaults("global", "shell_ui", "shell", "advanced", "restart"),
}

_FIELD_OVERRIDES: dict[str, dict[str, Any]] = {
    "generation.gen_model": {"integration": "litellm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.temperature": {"integration": "litellm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.max_tokens": {"integration": "litellm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.vllm.enabled": {"integration": "vllm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.vllm.base_url": {"integration": "vllm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.vllm.default_model": {"integration": "vllm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.litellm.enabled": {"integration": "litellm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.litellm.base_url": {"integration": "litellm", "ui_surface": "runtime", "exposure_level": "basic"},
    "chat.litellm.default_model": {"integration": "litellm", "ui_surface": "runtime", "exposure_level": "basic"},
    "retrieval.final_k": {"integration": "tribrid_retrieval", "ui_surface": "retrieval", "exposure_level": "basic"},
    "retrieval.multi_query_m": {"integration": "tribrid_retrieval", "ui_surface": "retrieval", "exposure_level": "basic"},
    "chunking.chunking_strategy": {"integration": "tribrid_retrieval", "ui_surface": "retrieval", "exposure_level": "basic"},
    "embedding.embedding_backend": {"integration": "tribrid_retrieval", "ui_surface": "retrieval", "exposure_level": "basic"},
    "reranking.reranker_mode": {"integration": "tribrid_retrieval", "ui_surface": "retrieval", "exposure_level": "basic"},
    "vector_search.enabled": {"integration": "tribrid_retrieval", "ui_surface": "retrieval", "exposure_level": "basic"},
    "sparse_search.enabled": {"integration": "tribrid_retrieval", "ui_surface": "retrieval", "exposure_level": "basic"},
    "graph_search.enabled": {"integration": "neo4j", "ui_surface": "graph", "exposure_level": "basic"},
    "training.ragweld_agent_workflow_backend": {"integration": "flyte", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_flyte_admin_base_url": {"integration": "flyte", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_flyte_console_base_url": {"integration": "flyte", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_flyte_project": {"integration": "flyte", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_flyte_domain": {"integration": "flyte", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_flyte_launchplan": {"integration": "flyte", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_tracking_backend": {"integration": "mlflow", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_mlflow_tracking_url": {"integration": "mlflow", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_mlflow_experiment_name": {"integration": "mlflow", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_backend": {"integration": "unsloth", "ui_surface": "training", "exposure_level": "basic"},
    "training.ragweld_agent_unsloth_image": {"integration": "unsloth", "ui_surface": "training", "exposure_level": "basic"},
    "tracing.langfuse_enabled": {"integration": "langfuse", "ui_surface": "observability", "exposure_level": "basic"},
    "tracing.langfuse_base_url": {"integration": "langfuse", "ui_surface": "observability", "exposure_level": "basic"},
    "tracing.langfuse_project": {"integration": "langfuse", "ui_surface": "observability", "exposure_level": "basic"},
    "ui.grafana_base_url": {"integration": "otel_grafana_stack", "ui_surface": "observability", "exposure_level": "basic"},
    "ui.grafana_embed_enabled": {"integration": "otel_grafana_stack", "ui_surface": "observability", "exposure_level": "basic"},
    "ui.grafana_dashboard_uid": {"integration": "otel_grafana_stack", "ui_surface": "observability", "exposure_level": "basic"},
    "ui.grafana_dashboard_slug": {"integration": "otel_grafana_stack", "ui_surface": "observability", "exposure_level": "basic"},
    "ui.grafana_auth_mode": {"integration": "otel_grafana_stack", "ui_surface": "observability", "exposure_level": "advanced"},
    "evaluation.eval_dataset_path": {"integration": "ragas", "ui_surface": "eval", "exposure_level": "basic"},
    "evaluation.baseline_path": {"integration": "promptfoo", "ui_surface": "eval", "exposure_level": "basic"},
    "system_prompts.eval_analysis": {"integration": "ragas", "ui_surface": "eval", "exposure_level": "expert"},
    "system_prompts.synthetic_judge": {"integration": "promptfoo", "ui_surface": "eval", "exposure_level": "expert"},
}

_LOCKED_INTEGRATION_CONTRACTS: tuple[ConfigIntegrationContract, ...] = (
    ConfigIntegrationContract(
        id="litellm",
        label="LiteLLM",
        summary="Gateway and routing surface for model/provider traffic.",
        ui_surface="runtime",
        required_config_paths=["chat.litellm.enabled", "chat.litellm.base_url", "chat.litellm.default_model"],
        required_secret_ids=["litellm_api_key"],
        readiness_checks=["enabled", "base_url_present", "default_model_present", "required_secret_present", "http_probe"],
        blocked_surfaces=["runtime", "chat", "benchmark"],
    ),
    ConfigIntegrationContract(
        id="vllm",
        label="vLLM",
        summary="Self-hosted serving lane for owned generation models.",
        ui_surface="runtime",
        required_config_paths=["chat.vllm.enabled", "chat.vllm.base_url", "chat.vllm.default_model"],
        required_secret_ids=[],
        readiness_checks=["enabled", "base_url_present", "default_model_present", "http_probe"],
        blocked_surfaces=["runtime", "chat", "benchmark"],
    ),
    ConfigIntegrationContract(
        id="flyte",
        label="Flyte",
        summary="Workflow orchestration control plane for Learning Agent runs.",
        ui_surface="training",
        required_config_paths=[
            "training.ragweld_agent_workflow_backend",
            "training.ragweld_agent_flyte_admin_base_url",
            "training.ragweld_agent_flyte_project",
            "training.ragweld_agent_flyte_domain",
            "training.ragweld_agent_flyte_launchplan",
        ],
        required_secret_ids=[],
        readiness_checks=["backend_selected", "required_fields_present", "admin_probe"],
        blocked_surfaces=["training"],
    ),
    ConfigIntegrationContract(
        id="tribrid_retrieval",
        label="Tri-brid Retrieval (Postgres + Neo4j)",
        summary="Canonical retrieval/indexing lane: pgvector dense, Postgres FTS sparse, and Neo4j graph legs.",
        ui_surface="retrieval",
        required_config_paths=["indexing.postgres_url", "vector_search.enabled", "sparse_search.enabled"],
        required_secret_ids=[],
        readiness_checks=["postgres_probe", "graph_probe_when_enabled"],
        blocked_surfaces=["retrieval", "chat"],
    ),
    ConfigIntegrationContract(
        id="haystack_docling_qdrant",
        label="Haystack + Docling + Qdrant",
        summary="Bounded OSS retrieval/indexing lane and its provenance-preserving pilot.",
        ui_surface="retrieval",
        required_config_paths=["embedding.embedding_backend", "chunking.chunking_strategy", "indexing.skip_dense"],
        required_secret_ids=[],
        readiness_checks=["corpus_selected", "pilot_export_present", "pilot_packages_present", "pilot_execution_ready"],
        blocked_surfaces=["retrieval"],
    ),
    ConfigIntegrationContract(
        id="neo4j",
        label="Neo4j",
        summary="Graph parity substrate for entity/chunk search and corpus graph state.",
        ui_surface="graph",
        required_config_paths=["graph_storage.neo4j_uri", "graph_storage.neo4j_user", "graph_storage.neo4j_database"],
        required_secret_ids=["neo4j_password"],
        readiness_checks=["required_fields_present", "password_present", "neo4j_probe"],
        blocked_surfaces=["graph", "retrieval"],
    ),
    ConfigIntegrationContract(
        id="unsloth",
        label="Unsloth",
        summary="Training execution backend for the Learning Agent target lane.",
        ui_surface="training",
        required_config_paths=["training.ragweld_agent_backend", "training.ragweld_agent_unsloth_image"],
        required_secret_ids=[],
        readiness_checks=["backend_selected", "image_present"],
        blocked_surfaces=["training"],
    ),
    ConfigIntegrationContract(
        id="mlflow",
        label="MLflow",
        summary="Run, artifact, and experiment truth for training/eval workflows.",
        ui_surface="training",
        required_config_paths=[
            "training.ragweld_agent_tracking_backend",
            "training.ragweld_agent_mlflow_tracking_url",
            "training.ragweld_agent_mlflow_experiment_name",
        ],
        required_secret_ids=[],
        readiness_checks=["backend_selected", "required_fields_present", "experiment_probe"],
        blocked_surfaces=["training", "eval"],
    ),
    ConfigIntegrationContract(
        id="ragas",
        label="Ragas",
        summary="Eval scoring substrate for retrieval and generation quality loops.",
        ui_surface="eval",
        required_config_paths=["evaluation.eval_dataset_path", "system_prompts.eval_analysis"],
        required_secret_ids=[],
        readiness_checks=["dataset_present", "prompt_present"],
        blocked_surfaces=["eval"],
    ),
    ConfigIntegrationContract(
        id="promptfoo",
        label="Promptfoo",
        summary="Regression and prompt-comparison substrate for evaluation workflows.",
        ui_surface="eval",
        required_config_paths=["evaluation.baseline_path", "system_prompts.synthetic_judge"],
        required_secret_ids=[],
        readiness_checks=["baseline_present", "judge_prompt_present"],
        blocked_surfaces=["eval"],
    ),
    ConfigIntegrationContract(
        id="langfuse",
        label="Langfuse",
        summary="LLM-native tracing and prompt observability substrate.",
        ui_surface="observability",
        required_config_paths=["tracing.langfuse_enabled", "tracing.langfuse_base_url", "tracing.langfuse_project"],
        required_secret_ids=["langfuse_public_key", "langfuse_secret_key"],
        readiness_checks=["enabled", "required_fields_present", "required_secrets_present", "http_probe"],
        blocked_surfaces=["observability", "eval"],
    ),
    ConfigIntegrationContract(
        id="otel_grafana_stack",
        label="OpenTelemetry + Grafana Stack",
        summary="OTLP export, Grafana embeds, Tempo, and Alloy-backed operator drilldown.",
        ui_surface="observability",
        required_config_paths=[
            "tracing.tracing_mode",
            "tracing.otlp_endpoint",
            "tracing.tempo_base_url",
            "tracing.alloy_base_url",
            "ui.grafana_base_url",
        ],
        required_secret_ids=[],
        readiness_checks=["mode_selected", "required_fields_present", "component_probes"],
        blocked_surfaces=["observability", "grafana"],
    ),
    ConfigIntegrationContract(
        id="shell_ui",
        label="Workbench Shell",
        summary="Operator-facing dock, config, and shell controls that must stay truthful during the migration.",
        ui_surface="shell",
        required_config_paths=["ui.runtime_mode", "ui.theme_mode"],
        required_secret_ids=[],
        readiness_checks=["config_surface_registered"],
        blocked_surfaces=["shell", "admin"],
    ),
)

_SECRET_REQUIREMENTS: tuple[SecretRequirement, ...] = (
    SecretRequirement(
        id="openai_api_key",
        env_var="OPENAI_API_KEY",
        label="OpenAI API Key",
        description="OpenAI access for the preserved provider-backed embedding boundary.",
        integrations=["tribrid_retrieval"],
        optional=True,
        ui_surface="retrieval",
    ),
    SecretRequirement(
        id="litellm_api_key",
        env_var="LITELLM_API_KEY",
        label="LiteLLM API Key",
        description="Required API-to-LiteLLM client credential. Upstream provider keys remain gateway-owned.",
        integrations=["litellm"],
        optional=False,
        ui_surface="runtime",
    ),
    SecretRequirement(
        id="cohere_api_key",
        env_var="COHERE_API_KEY",
        label="Cohere API Key",
        description="Cloud reranker credential used by the retrieval lane.",
        integrations=["haystack_docling_qdrant", "ragas"],
        optional=True,
        ui_surface="retrieval",
    ),
    SecretRequirement(
        id="voyage_api_key",
        env_var="VOYAGE_API_KEY",
        label="Voyage API Key",
        description="Embedding provider credential for provider-backed indexing and retrieval.",
        integrations=["tribrid_retrieval"],
        optional=True,
        ui_surface="retrieval",
    ),
    SecretRequirement(
        id="jina_api_key",
        env_var="JINA_API_KEY",
        label="Jina API Key",
        description="Optional retrieval/rerank provider credential when Jina-backed routes are selected.",
        integrations=["tribrid_retrieval"],
        optional=True,
        ui_surface="retrieval",
    ),
    SecretRequirement(
        id="langfuse_public_key",
        env_var="LANGFUSE_PUBLIC_KEY",
        label="Langfuse Public Key",
        description="Langfuse public key required for generation trace export.",
        integrations=["langfuse"],
        ui_surface="observability",
    ),
    SecretRequirement(
        id="langfuse_secret_key",
        env_var="LANGFUSE_SECRET_KEY",
        label="Langfuse Secret Key",
        description="Langfuse secret key required for generation trace export.",
        integrations=["langfuse"],
        ui_surface="observability",
    ),
    SecretRequirement(
        id="grafana_api_key",
        env_var="GRAFANA_API_KEY",
        label="Grafana API Key",
        description="Optional Grafana API credential for authenticated deployments.",
        integrations=["otel_grafana_stack"],
        optional=True,
        ui_surface="observability",
    ),
    SecretRequirement(
        id="slack_webhook_url",
        env_var="SLACK_WEBHOOK_URL",
        label="Slack Webhook URL",
        description="Optional outbound alert target for operator notifications.",
        integrations=["otel_grafana_stack", "shell_ui"],
        optional=True,
        ui_surface="shell",
    ),
    SecretRequirement(
        id="discord_webhook_url",
        env_var="DISCORD_WEBHOOK_URL",
        label="Discord Webhook URL",
        description="Optional outbound alert target for operator notifications.",
        integrations=["otel_grafana_stack", "shell_ui"],
        optional=True,
        ui_surface="shell",
    ),
    SecretRequirement(
        id="netlify_api_key",
        env_var="NETLIFY_API_KEY",
        label="Netlify API Key",
        description="Optional deployment credential for shell/admin helper flows.",
        integrations=["shell_ui"],
        optional=True,
        ui_surface="shell",
    ),
    SecretRequirement(
        id="neo4j_password",
        env_var="NEO4J_PASSWORD",
        label="Neo4j Password",
        description="Required password for the Neo4j graph substrate.",
        integrations=["neo4j"],
        ui_surface="graph",
    ),
    SecretRequirement(
        id="mcp_api_key",
        env_var="MCP_API_KEY",
        label="MCP API Key",
        description="Optional bearer token required when the embedded MCP HTTP transport is locked down.",
        integrations=["shell_ui"],
        optional=True,
        ui_surface="shell",
    ),
    SecretRequirement(
        id="postgres_password",
        env_var="POSTGRES_PASSWORD",
        label="Postgres Password",
        description="Local-dev password used when Postgres DSN is assembled from env vars.",
        integrations=["tribrid_retrieval"],
        optional=True,
        ui_surface="retrieval",
    ),
)

_FIELD_TREE_ERROR = "Field registry generation only supports BaseModel-backed TriBridConfig sections."
_ACRONYM_TOKENS = {
    "api": "API",
    "url": "URL",
    "uri": "URI",
    "ui": "UI",
    "rag": "RAG",
    "ragweld": "ragweld",
    "mlflow": "MLflow",
    "ragas": "Ragas",
    "otlp": "OTLP",
    "otel": "OTel",
    "grafana": "Grafana",
    "neo4j": "Neo4j",
    "qdrant": "Qdrant",
    "vllm": "vLLM",
    "litellm": "LiteLLM",
    "langfuse": "Langfuse",
    "flyte": "Flyte",
    "mcp": "MCP",
    "fps": "FPS",
    "json": "JSON",
    "llm": "LLM",
}


def _clean_url(url: str | None) -> str:
    return str(url or "").strip().rstrip("/")


async def _probe_url(url: str | None) -> tuple[bool | None, str | None]:
    target = _clean_url(url)
    if not target:
        return None, None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(target)
        return response.status_code < 500, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _probe_model_api(url: str, *, api_key: str | None = None) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{url.rstrip('/')}/models", headers=headers)
        return response.status_code == 200, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, type(exc).__name__


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        try:
            return value.value
        except Exception:
            return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _strip_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    if str(origin) in {"typing.Union", "types.UnionType"}:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return _strip_optional(args[0])
    return annotation


def _is_model_type(annotation: Any) -> bool:
    candidate = _strip_optional(annotation)
    try:
        return isinstance(candidate, type) and issubclass(candidate, BaseModel)
    except TypeError:
        return False


def _normalized_field_type(annotation: Any) -> tuple[str, list[str]]:
    candidate = _strip_optional(annotation)
    origin = get_origin(candidate)
    if origin is Literal:
        return "enum", [str(value) for value in get_args(candidate)]
    if isinstance(candidate, type) and issubclass(candidate, bool):
        return "boolean", []
    if candidate is int:
        return "integer", []
    if candidate is float:
        return "number", []
    if candidate is str:
        return "string", []
    if origin in {list, tuple, set}:
        return "array", []
    if origin in {dict}:
        return "object", []
    if _is_model_type(candidate):
        return "object", []
    return "string", []


def _label_for_path(path: str) -> str:
    leaf = path.split(".")[-1]
    parts = [part for part in leaf.split("_") if part]
    if not parts:
        return path
    rendered: list[str] = []
    for part in parts:
        lower = part.lower()
        rendered.append(_ACRONYM_TOKENS.get(lower, part.replace("-", " ").title()))
    return " ".join(rendered)


def _infer_exposure_level(path: str, field_type: str, enum_values: list[str], fallback: str) -> Literal["basic", "advanced", "expert"]:
    if path.startswith("system_prompts.") or path.endswith("_json") or path.endswith("_headers"):
        return "expert"
    if field_type in {"array", "object"}:
        return "expert"
    if any(token in path for token in ("target_modules", "dockview_layout_json", "intent_matrix", "path_boosts")):
        return "expert"
    basic_hints = (
        "enabled",
        "base_url",
        "default_model",
        "backend",
        "project",
        "domain",
        "launchplan",
        "tracking_url",
        "experiment_name",
        "unsloth_image",
        "neo4j_uri",
        "neo4j_user",
        "neo4j_database",
        "neo4j_database_mode",
        "tracing_mode",
        "otlp_endpoint",
        "langfuse_base_url",
        "langfuse_project",
        "grafana_base_url",
        "grafana_embed_enabled",
        "theme_mode",
        "runtime_mode",
    )
    if any(path.endswith(token) for token in basic_hints):
        return "basic"
    if enum_values and len(enum_values) <= 5 and fallback == "basic":
        return "basic"
    return fallback  # type: ignore[return-value]


def _secret_dependencies_for_path(path: str) -> list[str]:
    if path.startswith("chat.litellm."):
        return ["litellm_api_key"]
    if path.startswith("graph_storage."):
        return ["neo4j_password"]
    if path.startswith("tracing.langfuse_"):
        return ["langfuse_public_key", "langfuse_secret_key"]
    if path.startswith("ui.grafana_"):
        return ["grafana_api_key"]
    if path.startswith("reranking.reranker_cloud_"):
        return ["cohere_api_key", "voyage_api_key", "jina_api_key"]
    if path.startswith("mcp.") and (path.endswith("require_api_key") or path.endswith("enabled")):
        return ["mcp_api_key"]
    return []


def _apply_field_overrides(path: str, metadata: dict[str, Any]) -> dict[str, Any]:
    overrides = _FIELD_OVERRIDES.get(path)
    if overrides:
        metadata.update(overrides)
    secret_deps = _secret_dependencies_for_path(path)
    if secret_deps:
        metadata["secret_dependency_ids"] = secret_deps
    if path.startswith("tracing.langfuse_"):
        metadata["impact"] = "restart"
    elif path.startswith("tracing.") or path.startswith("graph_storage.") or path.startswith("mcp.") or path.startswith("docker."):
        metadata["impact"] = "restart"
    elif path.startswith("training.ragweld_agent_flyte_") or path.startswith("training.ragweld_agent_mlflow_") or path.startswith("training.ragweld_agent_unsloth_"):
        metadata["impact"] = "redeploy"
    return metadata


def _iter_leaf_fields(model_cls: type[BaseModel], *, prefix: str = "") -> list[tuple[str, Any, Any]]:
    rows: list[tuple[str, Any, Any]] = []
    for name, field in model_cls.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        annotation = _strip_optional(field.annotation)
        if _is_model_type(annotation):
            nested_cls = annotation
            rows.extend(_iter_leaf_fields(nested_cls, prefix=path))
            continue
        rows.append((path, field, annotation))
    return rows


@lru_cache(maxsize=1)
def list_config_leaf_paths() -> list[str]:
    return [path for path, _, _ in _iter_leaf_fields(TriBridConfig)]


@lru_cache(maxsize=1)
def list_secret_requirements() -> list[SecretRequirement]:
    return list(_SECRET_REQUIREMENTS)


@lru_cache(maxsize=1)
def list_integration_contracts() -> list[ConfigIntegrationContract]:
    return list(_LOCKED_INTEGRATION_CONTRACTS)


@lru_cache(maxsize=1)
def build_config_field_descriptors() -> list[ConfigFieldDescriptor]:
    descriptors: list[ConfigFieldDescriptor] = []
    for path, field, annotation in _iter_leaf_fields(TriBridConfig):
        section = path.split(".", 1)[0]
        defaults = _SECTION_DEFAULTS.get(section)
        if defaults is None:
            raise RuntimeError(f"{_FIELD_TREE_ERROR} Missing defaults for section '{section}'.")
        field_type, enum_values = _normalized_field_type(annotation)
        metadata: dict[str, Any] = {
            "path": path,
            "section": section,
            "label": _label_for_path(path),
            "type": field_type,
            "default": _jsonable(field.get_default(call_default_factory=True)),
            "description": str(field.description or "").strip() or None,
            "scope": defaults.scope,
            "integration": defaults.integration,
            "exposure_level": _infer_exposure_level(path, field_type, enum_values, defaults.exposure_level),
            "impact": defaults.impact,
            "secret_dependency_ids": [],
            "ui_surface": defaults.ui_surface,
            "enum_values": enum_values,
            "read_only": False,
        }
        metadata = _apply_field_overrides(path, metadata)
        descriptors.append(ConfigFieldDescriptor(**metadata))
    descriptors.sort(key=lambda item: item.path)
    return descriptors


def build_config_registry_response() -> ConfigRegistryResponse:
    return ConfigRegistryResponse(
        fields=build_config_field_descriptors(),
        integrations=list_integration_contracts(),
        secrets=list_secret_requirements(),
    )


def get_secret_requirement(env_var: str) -> SecretRequirement | None:
    target = str(env_var or "").strip()
    for requirement in list_secret_requirements():
        if requirement.env_var == target:
            return requirement
    return None


def allowed_secret_env_vars() -> set[str]:
    return {requirement.env_var for requirement in list_secret_requirements()}


def _config_value(config: TriBridConfig, path: str) -> Any:
    current: Any = config
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(current, BaseModel):
            current = getattr(current, part, None)
            continue
        if isinstance(current, dict):
            current = current.get(part)
            continue
        return None
    return current


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _integration_contract_map() -> dict[str, ConfigIntegrationContract]:
    return {contract.id: contract for contract in list_integration_contracts()}


def _build_integration_readiness(
    contract: ConfigIntegrationContract,
    *,
    state: Literal["ready", "degraded", "unconfigured", "disabled"],
    enabled: bool,
    configured: bool,
    reachable: bool | None = None,
    missing_config_paths: list[str] | None = None,
    missing_secret_ids: list[str] | None = None,
    failing_checks: list[str] | None = None,
    operator_hint: str | None = None,
    links: list[TraceExternalLink] | None = None,
) -> IntegrationReadiness:
    not_ready = state != "ready"
    return IntegrationReadiness(
        id=contract.id,
        label=contract.label,
        ui_surface=contract.ui_surface,
        state=state,
        enabled=enabled,
        configured=configured,
        reachable=reachable,
        missing_config_paths=missing_config_paths or [],
        missing_secret_ids=missing_secret_ids or [],
        failing_checks=failing_checks or [],
        blocked_surfaces=list(contract.blocked_surfaces) if not_ready else [],
        operator_hint=operator_hint,
        links=links or [],
    )


async def _resolve_corpus_path(corpus_id: str | None, postgres_dsn: str) -> str | None:
    target = str(corpus_id or "").strip()
    if not target:
        return None
    pg = PostgresClient(postgres_dsn, schema_mode="control")
    try:
        await pg.connect()
        corpus = await pg.get_corpus(target)
    except Exception as exc:
        if is_postgres_unavailable(exc) or is_transport_unavailable(exc):
            raise DependencyUnavailableError("postgres", "Config retrieval readiness") from exc
        return None
    finally:
        try:
            await pg.disconnect()
        except Exception:
            pass
    if not isinstance(corpus, dict):
        return None
    path = str(corpus.get("path") or "").strip()
    return path or None


def _component_map(items: list[ObservabilityComponentStatus]) -> dict[str, ObservabilityComponentStatus]:
    return {item.id: item for item in items}


async def _build_runtime_integration_readiness(config: TriBridConfig, contract: ConfigIntegrationContract) -> IntegrationReadiness:
    if contract.id == "litellm":
        enabled = bool(config.chat.litellm.enabled)
        missing = [path for path in contract.required_config_paths[1:] if _is_missing(_config_value(config, path))]
        missing_secret_ids = [
            secret_id
            for secret_id in contract.required_secret_ids
            if not os.getenv(get_secret_requirement_by_id(secret_id).env_var, "").strip()
        ]
        if not enabled:
            return _build_integration_readiness(
                contract,
                state="disabled",
                enabled=False,
                configured=not missing,
                missing_config_paths=missing,
                missing_secret_ids=missing_secret_ids,
                failing_checks=["enabled"],
                operator_hint="Enable LiteLLM and point it at the gateway URL before treating the runtime lane as migrated.",
            )
        if missing_secret_ids:
            return _build_integration_readiness(
                contract,
                state="unconfigured",
                enabled=True,
                configured=False,
                reachable=None,
                missing_config_paths=missing,
                missing_secret_ids=missing_secret_ids,
                failing_checks=["required_secret_present"],
                operator_hint="Set the API-to-LiteLLM client key before using generation surfaces.",
            )
        try:
            runtime_url = resolve_litellm_base_url(configured_url=config.chat.litellm.base_url)
            runtime_key = resolve_litellm_api_key()
            reachable, detail = await _probe_model_api(runtime_url, api_key=runtime_key)
        except RuntimeError as exc:
            runtime_url = str(config.chat.litellm.base_url or "")
            reachable, detail = False, str(exc)
        state: Literal["ready", "degraded", "unconfigured", "disabled"] = "ready"
        failing_checks: list[str] = []
        if missing:
            state = "unconfigured"
            failing_checks.extend(["base_url_present", "default_model_present"])
        elif reachable is False:
            state = "degraded"
            failing_checks.append("http_probe")
        return _build_integration_readiness(
            contract,
            state=state,
            enabled=True,
            configured=not missing,
            reachable=reachable,
            missing_config_paths=missing,
            missing_secret_ids=[],
            failing_checks=failing_checks,
            operator_hint=detail if state == "degraded" else "LiteLLM is selected as the gateway/routing layer.",
            links=[
                TraceExternalLink(
                    label="LiteLLM Gateway",
                    kind="custom",
                    url=runtime_url,
                    detail="Gateway routing endpoint",
                )
            ]
            if runtime_url
            else [],
        )

    enabled = bool(config.chat.vllm.enabled)
    missing = [path for path in contract.required_config_paths[1:] if _is_missing(_config_value(config, path))]
    if not enabled:
        return _build_integration_readiness(
            contract,
            state="disabled",
            enabled=False,
            configured=not missing,
            missing_config_paths=missing,
            failing_checks=["enabled"],
            operator_hint="Enable vLLM and configure its base URL/default model before cutting the serving lane over.",
        )
    try:
        runtime_url = resolve_vllm_base_url(configured_url=config.chat.vllm.base_url)
        reachable, detail = await _probe_model_api(runtime_url)
    except RuntimeError as exc:
        runtime_url = str(config.chat.vllm.base_url or "")
        reachable, detail = False, str(exc)
    state = "ready"
    failing_checks: list[str] = []
    if missing:
        state = "unconfigured"
        failing_checks.extend(["base_url_present", "default_model_present"])
    elif reachable is False:
        state = "degraded"
        failing_checks.append("http_probe")
    return _build_integration_readiness(
        contract,
        state=state,
        enabled=True,
        configured=not missing,
        reachable=reachable,
        missing_config_paths=missing,
        failing_checks=failing_checks,
        operator_hint=detail if state == "degraded" else "vLLM is selected as the serving lane.",
        links=[
            TraceExternalLink(
                label="vLLM Endpoint",
                kind="custom",
                url=runtime_url,
                detail="Serving endpoint",
            )
        ]
        if runtime_url
        else [],
    )


async def _build_training_integration_readiness(
    config: TriBridConfig,
    contract: ConfigIntegrationContract,
    *,
    scope_id: str | None,
) -> IntegrationReadiness:
    status = await build_agent_control_plane_status(config)
    component = next((item for item in status.components if item.kind == contract.id), None)
    if component is None:
        return _build_integration_readiness(
            contract,
            state="unconfigured",
            enabled=False,
            configured=False,
            failing_checks=["component_missing"],
            operator_hint="Training control-plane component metadata is missing.",
        )
    missing_config = [path for path in contract.required_config_paths[1:] if _is_missing(_config_value(config, path))]
    return _build_integration_readiness(
        contract,
        state=str(component.state or "unconfigured"),  # type: ignore[arg-type]
        enabled=bool(component.enabled),
        configured=bool(component.configured) and not missing_config,
        reachable=True if str(component.state or "") == "ready" else None if str(component.state or "") == "disabled" else False,
        missing_config_paths=missing_config,
        failing_checks=[] if str(component.state or "") == "ready" else list(contract.readiness_checks),
        operator_hint=component.detail or status.operator_hint,
        links=list(component.links or []),
    )


async def _build_tribrid_retrieval_readiness(
    config: TriBridConfig,
    contract: ConfigIntegrationContract,
    *,
    scope_id: str | None,
) -> IntegrationReadiness:
    """Functional readiness for the canonical Postgres/Neo4j retrieval lane."""

    failing_checks: list[str] = []
    operator_hint: str | None = None

    pg = PostgresClient(config.indexing.postgres_url, schema_mode="control")
    postgres_ok = False
    try:
        await pg.connect()
        postgres_ok = True
    except Exception:
        failing_checks.append("postgres_probe")
        operator_hint = "Postgres is unreachable; dense and sparse retrieval legs cannot run."
    finally:
        try:
            await pg.disconnect()
        except Exception:
            pass

    graph_enabled = bool(config.graph_search.enabled)
    neo4j_ok: bool | None = None
    if graph_enabled:
        neo4j = Neo4jClient(
            config.graph_storage.neo4j_uri,
            config.graph_storage.neo4j_user,
            config.graph_storage.resolve_password(),
            database=config.graph_storage.resolve_database(scope_id),
        )
        try:
            await neo4j.connect()
            neo4j_ok = True
        except Exception:
            neo4j_ok = False
            failing_checks.append("graph_probe_when_enabled")
            operator_hint = operator_hint or "Neo4j is unreachable; the graph retrieval leg cannot run."
        finally:
            try:
                await neo4j.disconnect()
            except Exception:
                pass

    ready = postgres_ok and (neo4j_ok is not False)
    return _build_integration_readiness(
        contract,
        state="ready" if ready else "degraded",
        enabled=True,
        configured=True,
        reachable=ready,
        failing_checks=failing_checks,
        operator_hint=operator_hint
        or "Canonical tri-brid retrieval lane (pgvector dense, Postgres FTS sparse, Neo4j graph) is functional.",
    )


async def _build_retrieval_integration_readiness(
    config: TriBridConfig,
    contract: ConfigIntegrationContract,
    *,
    scope_id: str | None,
) -> IntegrationReadiness:
    repo_path = await _resolve_corpus_path(scope_id, config.indexing.postgres_url)
    if not scope_id or not repo_path:
        return _build_integration_readiness(
            contract,
            state="unconfigured",
            enabled=True,
            configured=False,
            missing_config_paths=["corpus.path"],
            failing_checks=["corpus_selected"],
            operator_hint="Select a corpus to inspect the Haystack/Docling/Qdrant pilot lane.",
        )
    status = await build_retrieval_pilot_status(corpus_id=scope_id, repo_path=repo_path)
    missing_packages = [item.label for item in status.package_status if not item.available]
    failing_checks: list[str] = []
    state: Literal["ready", "degraded", "unconfigured", "disabled"] = "ready"
    if not status.export_exists:
        state = "unconfigured"
        failing_checks.append("pilot_export_present")
    elif missing_packages or not status.execution_ready:
        state = "degraded"
        if missing_packages:
            failing_checks.append("pilot_packages_present")
        if not status.execution_ready:
            failing_checks.append("pilot_execution_ready")
    return _build_integration_readiness(
        contract,
        state=state,
        enabled=True,
        configured=status.export_exists,
        reachable=True if status.execution_ready else None,
        failing_checks=failing_checks,
        operator_hint=status.operator_hint,
        links=[
            TraceExternalLink(
                label="Pilot Export",
                kind="custom",
                url=f"file://{status.export_dir}",
                detail="Local retrieval pilot artifacts",
            )
        ],
    )


async def _build_neo4j_integration_readiness(
    config: TriBridConfig,
    contract: ConfigIntegrationContract,
    *,
    scope_id: str | None,
) -> IntegrationReadiness:
    missing_config = [path for path in contract.required_config_paths if _is_missing(_config_value(config, path))]
    password = config.graph_storage.resolve_password()
    missing_secret_ids = [] if password else ["neo4j_password"]
    if missing_config or missing_secret_ids:
        return _build_integration_readiness(
            contract,
            state="unconfigured",
            enabled=True,
            configured=False,
            missing_config_paths=missing_config,
            missing_secret_ids=missing_secret_ids,
            failing_checks=["required_fields_present", "password_present"],
            operator_hint="Populate Neo4j connection settings and set NEO4J_PASSWORD in the environment.",
        )
    db_name = config.graph_storage.resolve_database(scope_id)
    neo4j = Neo4jClient(
        config.graph_storage.neo4j_uri,
        config.graph_storage.neo4j_user,
        password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        await neo4j.ping()
    except Exception as exc:
        return _build_integration_readiness(
            contract,
            state="degraded",
            enabled=True,
            configured=True,
            reachable=False,
            failing_checks=["neo4j_probe"],
            operator_hint=f"{type(exc).__name__}: {exc}",
        )
    finally:
        try:
            await neo4j.disconnect()
        except Exception:
            pass
    return _build_integration_readiness(
        contract,
        state="ready",
        enabled=True,
        configured=True,
        reachable=True,
        links=[
            TraceExternalLink(
                label="Neo4j",
                kind="custom",
                url=str(config.graph_storage.neo4j_uri or ""),
                detail=f"Database {db_name}",
            )
        ],
    )


async def _build_observability_integration_readiness(
    config: TriBridConfig,
    contract: ConfigIntegrationContract,
) -> IntegrationReadiness:
    status = await build_observability_status(config)
    components = _component_map(status.components)

    if contract.id == "langfuse":
        component = components.get("langfuse")
        missing_secret_ids = [
            secret_id
            for secret_id in contract.required_secret_ids
            if not os.getenv(get_secret_requirement_by_id(secret_id).env_var, "").strip()
        ]
        missing_config = [path for path in contract.required_config_paths[1:] if _is_missing(_config_value(config, path))]
        if component is None:
            return _build_integration_readiness(
                contract,
                state="unconfigured",
                enabled=bool(config.tracing.langfuse_enabled),
                configured=False,
                missing_config_paths=missing_config,
                missing_secret_ids=missing_secret_ids,
                failing_checks=["component_missing"],
                operator_hint="Langfuse status is unavailable.",
            )
        state: Literal["ready", "degraded", "unconfigured", "disabled"] = "ready"
        failing_checks: list[str] = []
        if not bool(config.tracing.langfuse_enabled):
            state = "disabled"
            failing_checks.append("enabled")
        elif missing_config or missing_secret_ids or not bool(component.configured):
            state = "unconfigured"
            failing_checks.extend(["required_fields_present", "required_secrets_present"])
        elif component.reachable is False:
            state = "degraded"
            failing_checks.append("http_probe")
        return _build_integration_readiness(
            contract,
            state=state,
            enabled=bool(config.tracing.langfuse_enabled),
            configured=not missing_config and not missing_secret_ids and bool(component.configured),
            reachable=component.reachable,
            missing_config_paths=missing_config,
            missing_secret_ids=missing_secret_ids,
            failing_checks=failing_checks,
            operator_hint=component.detail or status.operator_hint,
            links=list(status.links),
        )

    relevant_ids = {"local_trace_buffer", "otlp_export", "alloy", "tempo", "grafana"}
    relevant = [components[item_id] for item_id in relevant_ids if item_id in components]
    enabled = any(item.enabled for item in relevant)
    missing_config = [path for path in contract.required_config_paths[1:] if _is_missing(_config_value(config, path))]
    failing_checks: list[str] = []
    state = "ready"
    reachable: bool | None = True if relevant else None
    if not enabled:
        state = "disabled"
        failing_checks.append("mode_selected")
    elif missing_config:
        state = "unconfigured"
        failing_checks.append("required_fields_present")
    elif any(item.reachable is False for item in relevant if item.enabled):
        state = "degraded"
        failing_checks.append("component_probes")
        reachable = False
    elif not relevant:
        state = "unconfigured"
        failing_checks.append("component_probes")
        reachable = None
    return _build_integration_readiness(
        contract,
        state=state,
        enabled=enabled,
        configured=enabled and not missing_config,
        reachable=reachable,
        missing_config_paths=missing_config,
        failing_checks=failing_checks,
        operator_hint=status.operator_hint,
        links=list(status.links),
    )


def _build_eval_integration_readiness(config: TriBridConfig, contract: ConfigIntegrationContract) -> IntegrationReadiness:
    missing_config = [path for path in contract.required_config_paths if _is_missing(_config_value(config, path))]
    state: Literal["ready", "degraded", "unconfigured", "disabled"] = "ready"
    if missing_config:
        state = "unconfigured"
    return _build_integration_readiness(
        contract,
        state=state,
        enabled=True,
        configured=not missing_config,
        missing_config_paths=missing_config,
        failing_checks=[] if not missing_config else list(contract.readiness_checks),
        operator_hint=(
            None
            if not missing_config
            else f"Populate {', '.join(missing_config)} before treating {contract.label} as an eval substrate."
        ),
    )


def _build_shell_ui_readiness(config: TriBridConfig, contract: ConfigIntegrationContract) -> IntegrationReadiness:
    missing_config = [path for path in contract.required_config_paths if _is_missing(_config_value(config, path))]
    return _build_integration_readiness(
        contract,
        state="ready" if not missing_config else "unconfigured",
        enabled=True,
        configured=not missing_config,
        missing_config_paths=missing_config,
        failing_checks=[] if not missing_config else list(contract.readiness_checks),
        operator_hint="Workbench configuration surfaces are registered and driven from the config control plane.",
    )


def get_secret_requirement_by_id(secret_id: str) -> SecretRequirement:
    target = str(secret_id or "").strip()
    for requirement in list_secret_requirements():
        if requirement.id == target:
            return requirement
    raise KeyError(secret_id)


async def build_config_readiness_response(config: TriBridConfig, *, scope_id: str | None = None) -> ConfigReadinessResponse:
    contracts = list_integration_contracts()
    integrations: list[IntegrationReadiness] = []
    for contract in contracts:
        if contract.id in {"litellm", "vllm"}:
            integrations.append(await _build_runtime_integration_readiness(config, contract))
        elif contract.id in {"flyte", "mlflow", "unsloth"}:
            integrations.append(await _build_training_integration_readiness(config, contract, scope_id=scope_id))
        elif contract.id == "tribrid_retrieval":
            integrations.append(await _build_tribrid_retrieval_readiness(config, contract, scope_id=scope_id))
        elif contract.id == "haystack_docling_qdrant":
            integrations.append(await _build_retrieval_integration_readiness(config, contract, scope_id=scope_id))
        elif contract.id == "neo4j":
            integrations.append(await _build_neo4j_integration_readiness(config, contract, scope_id=scope_id))
        elif contract.id in {"langfuse", "otel_grafana_stack"}:
            integrations.append(await _build_observability_integration_readiness(config, contract))
        elif contract.id in {"ragas", "promptfoo"}:
            integrations.append(_build_eval_integration_readiness(config, contract))
        else:
            integrations.append(_build_shell_ui_readiness(config, contract))

    blocker_map: dict[str, list[str]] = {}
    for readiness in integrations:
        if readiness.state == "ready":
            continue
        for secret_id in readiness.missing_secret_ids:
            blocker_map.setdefault(secret_id, []).append(readiness.id)

    secrets = [
        SecretRequirementStatus(
            requirement=requirement,
            configured=bool(os.getenv(requirement.env_var, "").strip()),
            blocker_for_integrations=blocker_map.get(requirement.id, []),
        )
        for requirement in list_secret_requirements()
    ]

    failing = [item for item in integrations if item.state != "ready"]
    operator_hint = None
    if failing:
        labels = ", ".join(item.label for item in failing[:4])
        operator_hint = f"Resolve {labels} before relying on the blocked operator surfaces."
    else:
        operator_hint = "Configuration control plane is ready. Use Basic, Advanced, and Raw views to inspect or adjust the live stack."

    return ConfigReadinessResponse(
        ok=not failing,
        integrations=integrations,
        secrets=secrets,
        operator_hint=operator_hint,
    )


def validate_config_field_registry() -> list[str]:
    errors: list[str] = []
    leaf_paths = list_config_leaf_paths()
    descriptors = build_config_field_descriptors()
    descriptor_paths = [descriptor.path for descriptor in descriptors]
    missing = sorted(set(leaf_paths) - set(descriptor_paths))
    extra = sorted(set(descriptor_paths) - set(leaf_paths))
    duplicates = sorted({path for path in descriptor_paths if descriptor_paths.count(path) > 1})
    if missing:
        errors.append(f"Missing field descriptors: {', '.join(missing)}")
    if extra:
        errors.append(f"Unexpected field descriptors: {', '.join(extra)}")
    if duplicates:
        errors.append(f"Duplicate field descriptors: {', '.join(duplicates)}")
    contract_ids = {contract.id for contract in list_integration_contracts()}
    for descriptor in descriptors:
        if descriptor.integration not in contract_ids:
            errors.append(f"{descriptor.path}: integration '{descriptor.integration}' has no contract")
    return errors


def validate_secret_registry() -> list[str]:
    errors: list[str] = []
    requirement_ids = {requirement.id for requirement in list_secret_requirements()}
    requirement_env_vars = {requirement.env_var for requirement in list_secret_requirements()}
    for descriptor in build_config_field_descriptors():
        missing = [secret_id for secret_id in descriptor.secret_dependency_ids if secret_id not in requirement_ids]
        if missing:
            errors.append(f"{descriptor.path}: unknown secret dependency ids {missing!r}")

    found_secret_env_vars: set[str] = set()
    for path in _SERVER_ROOT.rglob("*.py"):
        path_str = str(path)
        if any(marker in path_str for marker in ("/tests/", "/.venv/", "/node_modules/")):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in _SECRET_ENV_PATTERN.findall(content):
            if re.search(r"(_KEY|_PASSWORD|_TOKEN|_WEBHOOK_URL)$", match):
                found_secret_env_vars.add(match)
    undeclared = sorted(found_secret_env_vars - requirement_env_vars)
    if undeclared:
        errors.append(f"Undeclared secret env vars referenced in server code: {', '.join(undeclared)}")
    return errors


def validate_integration_contracts() -> list[str]:
    errors: list[str] = []
    contracts = list_integration_contracts()
    ids = [contract.id for contract in contracts]
    duplicates = sorted({contract_id for contract_id in ids if ids.count(contract_id) > 1})
    if duplicates:
        errors.append(f"Duplicate integration contracts: {', '.join(duplicates)}")
    expected_ids = {
        "litellm",
        "vllm",
        "flyte",
        "haystack_docling_qdrant",
        "neo4j",
        "unsloth",
        "mlflow",
        "ragas",
        "promptfoo",
        "langfuse",
        "otel_grafana_stack",
        "shell_ui",
    }
    missing_ids = sorted(expected_ids - set(ids))
    if missing_ids:
        errors.append(f"Missing locked integration contracts: {', '.join(missing_ids)}")
    missing_surfaces = sorted(contract.id for contract in contracts if not contract.ui_surface or not contract.blocked_surfaces)
    if missing_surfaces:
        errors.append(f"Contracts missing protected UI metadata: {', '.join(missing_surfaces)}")
    return errors
