"""Real tests for the reranker module (no mocks)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.models.tribrid_config_model import RerankingConfig
from server.models.retrieval import ChunkMatch
from server.retrieval.rerank import Reranker, resolve_reranker_device


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


def _build_tiny_cross_encoder_model(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from transformers import BertConfig, BertForSequenceClassification, BertTokenizerFast

    torch.manual_seed(0)

    vocab = [
        "[PAD]",
        "[UNK]",
        "[CLS]",
        "[SEP]",
        "[MASK]",
        "query",
        "auth",
        "login",
        "token",
        "flow",
        "content",
        "for",
        "c0",
        "c1",
        "c2",
        "c3",
        "c4",
        "c5",
        "c6",
        "c7",
        "c8",
        "c9",
        "zzz",
    ]
    (out_dir / "vocab.txt").write_text("\n".join(vocab) + "\n", encoding="utf-8")

    tokenizer = BertTokenizerFast(vocab_file=str(out_dir / "vocab.txt"), do_lower_case=True)
    tokenizer.save_pretrained(str(out_dir))

    cfg = BertConfig(
        vocab_size=len(vocab),
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=64,
        max_position_embeddings=128,
        type_vocab_size=2,
        num_labels=1,
    )
    model = BertForSequenceClassification(cfg)
    model.eval()
    model.save_pretrained(str(out_dir))

    return out_dir


@pytest.fixture(scope="session")
def tiny_cross_encoder_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tiny_cross_encoder")
    return _build_tiny_cross_encoder_model(out)


def test_resolve_reranker_device_matches_torch_availability() -> None:
    import torch

    has_mps = False
    mps_backend = getattr(torch.backends, "mps", None)
    if mps_backend is not None and callable(getattr(mps_backend, "is_available", None)):
        has_mps = bool(mps_backend.is_available())

    expected = "cuda" if torch.cuda.is_available() else ("mps" if has_mps else "cpu")
    assert resolve_reranker_device() == expected


@pytest.mark.asyncio
async def test_reranker_none_passthrough() -> None:
    config = RerankingConfig(reranker_mode="none")
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8), make_chunk("c3", score=0.7)]
    out = await reranker.rerank("test query", chunks)

    assert [c.chunk_id for c in out] == ["c1", "c2", "c3"]
    assert [c.score for c in out] == [0.9, 0.8, 0.7]


@pytest.mark.asyncio
async def test_reranker_local_reranks_and_sets_scores(tiny_cross_encoder_dir: Path) -> None:
    config = RerankingConfig(
        reranker_mode="local",
        reranker_local_model=str(tiny_cross_encoder_dir),
        tribrid_reranker_topn=10,
        tribrid_reranker_alpha=1.0,
        tribrid_reranker_batch=4,
        tribrid_reranker_maxlen=128,
        rerank_input_snippet_chars=200,
        transformers_trust_remote_code=0,
    )
    reranker = Reranker(config)

    query = "auth login flow"
    chunks = [
        make_chunk(f"c{i}", score=0.9 - (i * 0.01), content=("auth " * i) + "zzz")
        for i in range(10)
    ]

    out = await reranker.rerank(query, chunks)
    assert len(out) == 10
    assert all(0.0 <= float(c.score) <= 1.0 for c in out)
    assert all(float(out[i].score) >= float(out[i + 1].score) for i in range(len(out) - 1))
    assert all("reranker_score_raw" in (c.metadata or {}) for c in out)


@pytest.mark.asyncio
async def test_reranker_local_respects_topn_without_truncation(tiny_cross_encoder_dir: Path) -> None:
    config = RerankingConfig(
        reranker_mode="local",
        reranker_local_model=str(tiny_cross_encoder_dir),
        tribrid_reranker_topn=10,
        tribrid_reranker_alpha=1.0,
        tribrid_reranker_batch=4,
        tribrid_reranker_maxlen=128,
        rerank_input_snippet_chars=200,
        transformers_trust_remote_code=0,
    )
    reranker = Reranker(config)

    query = "auth login flow"
    chunks = [make_chunk(f"c{i}", score=1.0 - (i * 0.01), content=("auth " * i) + "zzz") for i in range(15)]

    out = await reranker.rerank(query, chunks)
    assert len(out) == 15

    # Only the top-N candidates are reranked; the remainder is appended unchanged.
    assert [c.chunk_id for c in out[-5:]] == [f"c{i}" for i in range(10, 15)]
    assert all("reranker_score_raw" not in (c.metadata or {}) for c in out[-5:])


@pytest.mark.asyncio
async def test_reranker_local_missing_model_reports_skipped() -> None:
    config = RerankingConfig(
        reranker_mode="local",
        reranker_local_model="",
        tribrid_reranker_topn=10,
        tribrid_reranker_alpha=1.0,
        tribrid_reranker_batch=4,
        tribrid_reranker_maxlen=128,
        rerank_input_snippet_chars=200,
        transformers_trust_remote_code=0,
    )
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    res = await reranker.try_rerank("auth login", chunks)

    assert res.ok is True
    assert res.applied is False
    assert res.skipped_reason == "missing_model"
    assert res.error is None
    assert [c.chunk_id for c in res.chunks] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_reranker_cloud_missing_api_key_reports_skipped() -> None:
    # Ensure no key is present for this test.
    os.environ.pop("COHERE_API_KEY", None)

    config = RerankingConfig(
        reranker_mode="cloud",
        reranker_cloud_provider="cohere",
        reranker_cloud_model="rerank-3.5",
        reranker_cloud_top_n=10,
        reranker_timeout=5,
    )
    reranker = Reranker(config)

    chunks = [make_chunk("c1", score=0.9), make_chunk("c2", score=0.8)]
    res = await reranker.try_rerank("auth login", chunks)

    assert res.ok is True
    assert res.applied is False
    assert res.skipped_reason == "missing_api_key"
    assert res.error is None
    assert [c.chunk_id for c in res.chunks] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_reranker_empty_input() -> None:
    config = RerankingConfig(reranker_mode="none")
    reranker = Reranker(config)
    out = await reranker.rerank("test query", [])
    assert out == []
