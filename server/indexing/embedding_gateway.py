"""Native gateway transport for cloud embeddings; vector identity stays with Embedder."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIResponseValidationError, APIStatusError, AsyncOpenAI
from openai.types import CreateEmbeddingResponse
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import SecretStr, ValidationError

from server.chat.gateway_runtime import resolve_litellm_api_key, resolve_litellm_base_url
from server.gateway_catalog import gateway_rows_snapshot
from server.models.tribrid_config_model import TriBridConfig
from server.observability.run_census import (
    CensusAsyncTransport,
    RunCensusScope,
    RunIdentity,
    native_request_headers,
)


class EmbeddingGatewayError(RuntimeError):
    """Cloud embedding failed without changing provider, model or vector contract."""


@dataclass(frozen=True, slots=True)
class EmbeddingGateway:
    """Captured route and billing identity. A missing census never claims completeness."""

    base_url: str
    alias: str
    provider_model: str
    max_dimensions: int
    identity: RunIdentity
    api_key: SecretStr | None = field(default=None, repr=False)
    census_scope: RunCensusScope | None = field(default=None, repr=False)
    trace_headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        url = urlsplit(self.base_url)
        if (url.scheme not in {"http", "https"} or not url.netloc
                or url.path.rstrip("/") != "/v1" or url.query or url.fragment or url.username or url.password):
            raise ValueError("Embedding gateway requires an explicit absolute /v1 URL")
        if not self.alias or not self.provider_model or self.max_dimensions <= 0:
            raise ValueError("Embedding gateway requires a model route and dimensions")
        if self.identity.lane not in {"index_embeddings", "retrieval_embeddings", "cache_embeddings"}:
            raise ValueError("New embedding requests require an explicit embedding call-site lane")
        if self.census_scope is not None and self.census_scope.identity != self.identity:
            raise ValueError("Embedding route and durable census identities must match")
        object.__setattr__(self, "trace_headers", MappingProxyType(dict(self.trace_headers)))

    async def embed(
        self, texts: list[str], *, model: str, dimensions: int,
        timeout_s: float, max_attempts: int,
    ) -> list[list[float]]:
        if model != self.provider_model:
            raise EmbeddingGatewayError("Embedding gateway route does not match the selected model")
        if dimensions <= 0 or dimensions > self.max_dimensions:
            raise EmbeddingGatewayError("Requested embedding dimensions exceed the selected model's capability")
        if not texts:
            return []
        # Resolve only the app-to-gateway key, at actual cache-miss dispatch. A
        # complete cache hit needs neither provider credentials nor an SDK client.
        key = self.api_key.get_secret_value() if self.api_key is not None else resolve_litellm_api_key()
        headers = {**self.trace_headers, **native_request_headers(self.identity)}
        transport = CensusAsyncTransport(self.census_scope) if self.census_scope is not None else None
        http_client = httpx.AsyncClient(transport=transport, headers=headers, trust_env=False)
        async with http_client, AsyncOpenAI(
            base_url=self.base_url, api_key=key, max_retries=0,
            http_client=http_client, timeout=timeout_s,
        ) as client:
            for attempt in range(max(1, max_attempts)):
                try:
                    response = await client.embeddings.create(
                        model=self.alias, input=texts, dimensions=dimensions, encoding_format="float",
                        timeout=timeout_s,
                        extra_body={"num_retries": 0, "max_retries": 0, "disable_fallbacks": True},
                    )
                except (json.JSONDecodeError, APIResponseValidationError) as error:
                    raise EmbeddingGatewayError("Embedding gateway returned an invalid response") from error
                except (APIConnectionError, APIStatusError) as error:
                    status = error.status_code if isinstance(error, APIStatusError) else None
                    retryable = status is None or status in {408, 409, 429} or status >= 500
                    if not retryable or attempt + 1 >= max(1, max_attempts):
                        detail = f"HTTP {status}" if status is not None else "connection or timeout"
                        raise EmbeddingGatewayError(f"Embedding gateway request failed ({detail})") from error
                    await asyncio.sleep(min(2.0, 0.25 * (2 ** attempt)))
                    continue

                # The official SDK owns the external response DTO. Validate the
                # semantic batch contract before assigning or caching any vector.
                try:
                    response = CreateEmbeddingResponse.model_validate(response.model_dump(), strict=True)
                except ValidationError as error:
                    raise EmbeddingGatewayError("Embedding gateway returned an invalid response") from error
                if len(response.data) != len(texts) or {item.index for item in response.data} != set(range(len(texts))):
                    raise EmbeddingGatewayError("Embedding gateway returned invalid batch indices or vector count")
                vectors: list[list[float]] = []
                for item in sorted(response.data, key=lambda row: row.index):
                    if not isinstance(item.embedding, list) or len(item.embedding) != dimensions:
                        raise EmbeddingGatewayError("Embedding gateway returned incorrect vector dimensions")
                    try:
                        vector = [float(value) for value in item.embedding]
                    except (TypeError, ValueError) as error:
                        raise EmbeddingGatewayError("Embedding gateway returned invalid vector values") from error
                    if not all(math.isfinite(value) for value in vector):
                        raise EmbeddingGatewayError("Embedding gateway returned non-finite vector values")
                    vectors.append(vector)
                return vectors
        raise EmbeddingGatewayError("Embedding gateway exhausted its request attempts")


def embedding_gateway_for_config(
    config: TriBridConfig, *, identity: RunIdentity, census_scope: RunCensusScope | None = None,
) -> EmbeddingGateway | None:
    """Resolve the selected cloud model through its exact EMB catalog alias."""
    embedding = config.embedding
    if embedding.embedding_backend != "provider" or embedding.embedding_type != "openai":
        return None
    candidates = [row for row in gateway_rows_snapshot(capability="EMB").values()
                  if row.provider == "openai" and row.model == embedding.effective_model]
    if len(candidates) != 1:
        raise EmbeddingGatewayError("Selected OpenAI embedding model has no unique loaded gateway alias")
    row = candidates[0]
    if row.dimensions is None:
        raise EmbeddingGatewayError("Selected embedding gateway alias has no dimensional capability")
    carrier: dict[str, str] = {}
    # An index owner captures its run trace before the background task starts.
    # Let its census transport supply that trace, even when it has no trace,
    # rather than overriding it with the initiating HTTP request's context.
    if census_scope is None:
        TraceContextTextMapPropagator().inject(carrier)
    return EmbeddingGateway(
        base_url=resolve_litellm_base_url(configured_url=config.chat.litellm.base_url),
        alias=row.alias, provider_model=row.model, max_dimensions=row.dimensions,
        identity=identity, census_scope=census_scope, trace_headers=carrier,
    )
