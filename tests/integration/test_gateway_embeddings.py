"""Cloud Embedder through the existing opt-in pinned native gateway fixture.

No application or gateway API substitutes: both HTTP hops run for real. The
fixture retains its explicit Linux/Docker capability and loopback-only resources.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from server.indexing.embedder import Embedder
from server.indexing.embedding_gateway import EmbeddingGateway, EmbeddingGatewayError
from server.models.tribrid_config_model import EmbeddingConfig
from server.observability.run_census import RunCensusScope, RunIdentity
from tests.integration.test_native_gateway_policy import (
    _Gateway,
    native_policy_gateway,  # noqa: F401 - existing real native gateway pytest fixture
)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "rate_limit", "failure", "disconnect"])
async def test_cloud_embedding_preserves_upstream_vector_contract_and_exposes_hidden_retry_gap(
    native_policy_gateway: _Gateway, tmp_path: Path, mode: str,
) -> None:
    gateway = native_policy_gateway
    identity = RunIdentity("embedding-native-" + mode, "embedding-contract", "index_embeddings")
    checkpoint_path = tmp_path / "census.json"
    def persist(checkpoint):
        checkpoint_path.write_text(json.dumps(asdict(checkpoint)))
    scope = RunCensusScope(identity, persist)
    route = EmbeddingGateway(
        gateway.base_url + "/v1", "embedding", "text-embedding-3-small", 1536,
        identity, api_key=gateway.key, census_scope=scope,
    )
    config = EmbeddingConfig(
        embedding_backend="provider", embedding_type="openai", embedding_model="text-embedding-3-small",
        embedding_dim=128, embedding_retry_max=1, embed_text_prefix="document:", embed_text_suffix=":end",
    )
    with gateway.state.lock:
        gateway.state.mode = mode
        gateway.state.calls.clear()
        gateway.state.payloads.clear()
    embedder = Embedder(config, gateway=route)
    if mode == "success":
        vectors = await embedder.embed_batch(["calibration one", "calibration two"])
        assert vectors == [[0.1] * 128, [0.1] * 128]
    else:
        with pytest.raises(EmbeddingGatewayError):
            await embedder.embed_batch(["calibration one", "calibration two"])
    scope.finish_owner()
    checkpoint = json.loads(checkpoint_path.read_text())
    assert checkpoint["started_requests"] == checkpoint["completed_requests"] == 1
    with gateway.state.lock:
        payloads = list(gateway.state.payloads)
        calls = list(gateway.state.calls)
    expected_provider_attempts = 3 if gateway.sdk_retries == 2 and mode != "success" else 1
    assert len(calls) == len(payloads) == expected_provider_attempts
    for payload in payloads:
        assert payload["model"] == "text-embedding-3-small"
        assert payload["dimensions"] == 128
        assert payload["input"] == ["document:calibration one:end", "document:calibration two:end"]
    # Native public policy reads cannot establish the hidden SDK setting. The
    # app must not call either variant complete merely from a row/request count.
    policy = await gateway.reader().snapshot(models=frozenset({"embedding"}))
    assert policy.verified is False
    assert "provider_sdk_retry_policy_unobservable" in policy.reasons
