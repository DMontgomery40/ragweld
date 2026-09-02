"""Real tests for the reranker module (no mocks)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import RerankingConfig, TriBridConfig
from server.retrieval.rerank import Reranker


@contextmanager
def _without_env(*names: str) -> Iterator[None]:
    """Run with the named variables absent from the real process environment, then restore them."""
    saved = {name: os.environ.pop(name, None) for name in names}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def make_chunk(chunk_id: str, *, score: float, content: str | None = None) -> ChunkMatch:
    return ChunkMatch(
        chunk_id=chunk_id,
        content=content or f"Content for {chunk_id}",
        file_path="test.py",
        start_line=1,
        end_line=10,
        language="python",
        score=float(score),
        source="vector",
        metadata={},
    )


@pytest.mark.asyncio
async def test_reranker_none_passthrough() -> None:
    config = RerankingConfig(reranker_mode="none")
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8), make_chunk("c3", score=0.7)]
    out = await reranker.rerank("How often is the Aurora salinity sensor array calibrated?", chunks)

    assert [c.chunk_id for c in out] == ["c1", "c2", "c3"]
    assert [c.score for c in out] == [0.9, 0.8, 0.7]


@pytest.mark.asyncio
async def test_reranker_learning_missing_trained_model_fails_closed() -> None:
    """A configured learning reranker with no trained model is a failure the request
    surfaces as ``reranker_failed``, never a silent skip to the fusion order."""
    config = RerankingConfig(reranker_mode="learning")
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    res = await reranker.try_rerank("Which team owns the Aurora incident playbook escalation steps?", chunks)

    assert res.ok is False
    assert res.applied is False
    assert res.skipped_reason == "missing_trained_model"
    assert res.error and "trained model" in res.error
    assert [c.chunk_id for c in res.chunks] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_reranker_cloud_missing_api_key_fails_closed() -> None:
    with _without_env("COHERE_API_KEY"):
        await _assert_cohere_fails_closed()


async def _assert_cohere_fails_closed() -> None:

    config = RerankingConfig(
        reranker_mode="cloud",
        reranker_cloud_provider="cohere",
        reranker_cloud_model="rerank-v3.5",
        reranker_cloud_top_n=10,
        reranker_timeout=5,
    )
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    res = await reranker.try_rerank("Which team owns the Aurora incident playbook escalation steps?", chunks)

    assert res.ok is False
    assert res.applied is False
    assert res.skipped_reason == "missing_api_key"
    assert res.error and "COHERE_API_KEY" in res.error
    assert [c.chunk_id for c in res.chunks] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_reranker_empty_input() -> None:
    config = RerankingConfig(reranker_mode="none")
    reranker = Reranker(config)
    out = await reranker.rerank("Which team owns the Aurora incident playbook escalation steps?", [])
    assert out == []



@pytest.mark.asyncio
async def test_reranker_cloud_litellm_without_a_gateway_fails_closed() -> None:
    """No authenticated gateway in the test process: the configured gateway reranker fails
    with the resolution reason, never fakes scores and never skips to the fusion order."""
    with _without_env("LITELLM_API_KEY"):
        await _assert_litellm_fails_closed()


async def _assert_litellm_fails_closed() -> None:
    config = RerankingConfig(
        reranker_mode="cloud",
        reranker_cloud_provider="litellm",
        reranker_cloud_model="openai.gpt-5.4-nano",
        reranker_cloud_top_n=10,
        reranker_timeout=5,
    )
    reranker = Reranker(config, gateway_config=TriBridConfig())

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    res = await reranker.try_rerank("Which plane management company did Barry Cohen consider switching to?", chunks)

    assert res.ok is False
    assert res.applied is False
    assert res.skipped_reason == "gateway_unavailable"
    assert res.error
    assert [c.chunk_id for c in res.chunks] == ["c1", "c2"]


def test_reranking_config_only_accepts_runnable_cloud_providers() -> None:
    assert RerankingConfig().reranker_cloud_provider == "litellm"
    assert RerankingConfig(reranker_cloud_provider="cohere").reranker_cloud_provider == "cohere"
    with pytest.raises(ValidationError):
        RerankingConfig(reranker_cloud_provider="voyage")


def test_cloud_scores_blend_with_fusion_and_keep_fusion_order_on_ties() -> None:
    config = RerankingConfig(reranker_mode="cloud", reranker_cloud_provider="litellm", tribrid_reranker_alpha=0.7)
    reranker = Reranker(config)
    candidates = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8), make_chunk("c3", score=0.7)]

    out = reranker._apply_cloud_scores(candidates=candidates, remainder=[], raw_scores=[2.0, 9.0, 9.0], provider="litellm")

    # c2 and c3 tie on the gateway score; the fusion score breaks the tie, never the chunk id.
    assert [c.chunk_id for c in out] == ["c2", "c3", "c1"]
    assert out[0].metadata["reranker_score_raw"] == 9.0
    assert out[0].metadata["reranker_cloud_provider"] == "litellm"
    assert out[0].score > out[1].score > out[2].score


def test_uniform_cloud_scores_are_neutral_and_preserve_fusion_scores() -> None:
    config = RerankingConfig(reranker_mode="cloud", reranker_cloud_provider="litellm", tribrid_reranker_alpha=1.0)
    reranker = Reranker(config)
    candidates = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    remainder = [make_chunk("c9", score=0.1)]

    out = reranker._apply_cloud_scores(candidates=candidates, remainder=remainder, raw_scores=[8.0, 8.0], provider="litellm")

    assert [c.chunk_id for c in out] == ["c1", "c2", "c9"]
    assert [c.score for c in out] == [0.9, 0.8, 0.1]
    assert out[0].metadata["reranker_neutral"] is True
    assert out[0].metadata["reranker_score_raw"] == 8.0

    single = reranker._apply_cloud_scores(candidates=[make_chunk("c1", score=0.9)], remainder=[], raw_scores=[8.0], provider="litellm")
    assert single[0].score == 0.9


def test_flat_config_reranking_defaults_match_the_typed_defaults_and_ignore_legacy_keys() -> None:
    # Codex pass 7: from_flat_dict({}) reconstructed cohere/rerank-v3.5 (the replaced defaults) and
    # still honored RERANKER_ACTIVE / RERANKER_BACKEND / RERANKER_PROVIDER / COHERE_RERANK_MODEL.
    typed = TriBridConfig().reranking
    flat = TriBridConfig.from_flat_dict({}).reranking
    assert (flat.reranker_mode, flat.reranker_cloud_provider, flat.reranker_cloud_model) == (
        typed.reranker_mode,
        typed.reranker_cloud_provider,
        typed.reranker_cloud_model,
    )
    legacy = TriBridConfig.from_flat_dict(
        {"RERANKER_ACTIVE": "cloud", "RERANKER_BACKEND": "cloud", "RERANKER_PROVIDER": "cohere", "COHERE_RERANK_MODEL": "rerank-v3.5"}
    ).reranking
    assert (legacy.reranker_mode, legacy.reranker_cloud_provider, legacy.reranker_cloud_model) == (
        typed.reranker_mode,
        typed.reranker_cloud_provider,
        typed.reranker_cloud_model,
    )
    canonical = TriBridConfig.from_flat_dict(
        {"RERANKER_MODE": "cloud", "RERANKER_CLOUD_PROVIDER": "cohere", "RERANKER_CLOUD_MODEL": "rerank-v3.5"}
    ).reranking
    assert (canonical.reranker_mode, canonical.reranker_cloud_provider, canonical.reranker_cloud_model) == (
        "cloud",
        "cohere",
        "rerank-v3.5",
    )
    # the flat projection round-trips through the canonical keys
    round_trip = TriBridConfig.from_flat_dict(TriBridConfig().to_flat_dict()).reranking
    assert round_trip == typed
